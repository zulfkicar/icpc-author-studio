"""Loopback-only server for the ICPC Author Agent.

Run: python -m author_studio --port 8787
Then open http://127.0.0.1:8787/
"""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import pathlib
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from author_studio.classic import agent
from author_studio import config
from author_studio.classic import graph_agent
from author_studio.judging import isolate_client
from author_studio import job_lifecycle
from author_studio import studio
from author_studio import studio_sample
from author_studio.judging import judge0_adapter
from author_studio import mcp_consent
from author_studio import mcp_server
from author_studio.judging import verify
from author_studio import winutil
from author_studio.packages import workspace
from engine.model import SingleRequestOpenAIAdapter
from engine.policy import PolicyDenied
from engine.service import EngineService
from engine.store import IdempotencyConflict, LedgerError
from engine.worker import FakeWorker, IsolateWorker

ROOT = config.ROOT
WEB = ROOT / "web"
JOBS: dict[str, dict] = {}
JOB_LOCK = threading.Lock()
CHAT_LOCK = threading.Lock()
ACTIVE_CHATS: set[str] = set()
WORKSPACE_LOCKS: dict[str, threading.Lock] = {}
WORKSPACE_LOCKS_GUARD = threading.Lock()
JOB_TIMEOUT_SECONDS = 20 * 60
JOB_STOP_GRACE_SECONDS = 60
ENGINE_SERVICE: EngineService | None = None
CHAT_SERVICE = None
ENGINE_LOCK = threading.Lock()


def mcp_probe(slug: str, tool: str, arguments: dict) -> dict:
    """Act as an MCP host: spawn the scoped server and call one tool."""
    if not tool:
        raise ValueError("Choose a tool to test")
    process = subprocess.Popen(
        [sys.executable, "-m", "author_studio.mcp_server", "--slug", slug,
         "--consent", mcp_consent.consent_path(slug)],
        cwd=ROOT,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        def request(message: dict) -> dict:
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()
            line = process.stdout.readline()
            if not line:
                raise RuntimeError("MCP server closed the connection")
            return json.loads(line)

        request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        response = request({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": tool, "arguments": arguments if isinstance(arguments, dict) else {}},
        })
        return {"ok": not response.get("result", {}).get("isError"), "response": response}
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def workspace_lock(slug: str) -> threading.Lock:
    with WORKSPACE_LOCKS_GUARD:
        return WORKSPACE_LOCKS.setdefault(workspace.safe_slug(slug), threading.Lock())


def now() -> str:
    return time.strftime("%H:%M:%S")


def _signal_job_stop(job: dict) -> None:
    if job["workerActive"] and job.get("slug") and job.get("chatId"):
        graph_agent.cancel_turn(job["slug"], job["chatId"])


def request_job_cancel(job_id: str) -> dict | None:
    with JOB_LOCK:
        job = JOBS.get(job_id)
        if job is None:
            return None
        accepted = job_lifecycle.transition(job, "cancel")
        if accepted:
            _signal_job_stop(job)
        return {"ok": True, "jobId": job_id, "accepted": accepted, "phase": job["phase"]}


def start_job(title: str, slug: str | None, fn, chat_id: str | None = None, *, owns_chat: bool = False,
              studio_request: dict | None = None) -> dict:
    request_id = (studio_request or {}).get("studioRequestId")
    if request_id is not None and (not isinstance(request_id, str) or not re.fullmatch(r"[a-f0-9-]{36}", request_id)):
        raise ValueError("Invalid Studio job request ID")
    fingerprint = hashlib.sha256(json.dumps(studio_request, sort_keys=True).encode()).hexdigest() if request_id else None
    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "title": title, "slug": slug, "chatId": chat_id, "state": "running",
           "phase": "queued", "workerActive": False,
           "cancelRequested": False, "createdAt": now(), "events": [], "nextSeq": 1,
           "result": None, "error": None}
    if request_id:
        job.update(requestId=request_id, requestHash=fingerprint)

    def append_event(kind: str, data) -> None:
        job["events"].append({"seq": job["nextSeq"], "at": now(), "kind": kind, "data": data})
        job["nextSeq"] += 1
        if len(job["events"]) > 600:
            job["events"] = job["events"][-600:]

    def emit(kind: str, data) -> None:
        with JOB_LOCK:
            if job["state"] == "running":
                append_event(kind, data)

    def cancelled() -> bool:
        return bool(job.get("cancelRequested"))

    run_lock = workspace_lock(slug) if slug else None
    finished = threading.Event()

    def record_timeout() -> None:
        job["error"] = "Job exceeded the 20-minute limit."

    def run() -> None:
        acquired = False
        result = error = None
        try:
            if run_lock is not None:
                while not cancelled() and not acquired:
                    acquired = run_lock.acquire(timeout=0.1)
            with JOB_LOCK:
                job["workerActive"] = not cancelled() and job_lifecycle.transition(job, "start")
            if job["workerActive"] and not cancelled():
                result = fn(emit, cancelled)
        except Exception as exc:  # noqa: BLE001 - job reports its own failure
            if not cancelled():
                traceback.print_exc()
            error = f"{type(exc).__name__}: {exc}"
        finally:
            with JOB_LOCK:
                job["workerActive"] = False
                if owns_chat:
                    with CHAT_LOCK:
                        ACTIVE_CHATS.discard(slug)
                if acquired:
                    run_lock.release()
                if job_lifecycle.settle(job, result, error):
                    if job["phase"] == "timed_out":
                        record_timeout()
                    elif job["phase"] == "cancelled":
                        append_event("cancelled", {})
                    elif job["phase"] == "failed":
                        append_event("error", {"error": error})
            finished.set()

    with JOB_LOCK:
        if request_id:
            prior = next((item for item in JOBS.values() if item.get("requestId") == request_id), None)
            if prior:
                if (prior["slug"], prior["title"], prior["requestHash"]) != (slug, title, fingerprint):
                    raise studio.EditConflict("This job request belongs to a different package or action.")
                return json.loads(json.dumps(prior))
        JOBS[job_id] = job
        if len(JOBS) > 80:
            for key in list(JOBS)[:20]:
                if JOBS[key]["state"] in ("done", "error", "cancelled") and not JOBS[key]["workerActive"]:
                    JOBS.pop(key, None)

    def watchdog() -> None:
        if finished.wait(JOB_TIMEOUT_SECONDS):
            return
        with JOB_LOCK:
            if not job_lifecycle.transition(job, "deadline"):
                return
            append_event("timeout", {"message": "Job exceeded the time limit. Cancellation was requested."})
            _signal_job_stop(job)
        if finished.wait(JOB_STOP_GRACE_SECONDS):
            return
        with JOB_LOCK:
            if job_lifecycle.transition(job, "grace_elapsed"):
                record_timeout()

    queued = {**job, "events": []}
    threading.Thread(target=run, daemon=True).start()
    threading.Thread(target=watchdog, daemon=True).start()
    return queued


def engine_service() -> EngineService:
    """Lazy engine service.

    Demo mode is explicit (``AUTHOR_AGENT_ENGINE_DEMO=1``).  Without a live
    model configuration or an explicit demo switch the service uses a visible
    unconfigured adapter, so chat explains the missing model instead of
    silently substituting the scripted demo.
    """
    global ENGINE_SERVICE
    with ENGINE_LOCK:
        if ENGINE_SERVICE is not None:
            return ENGINE_SERVICE
        root = pathlib.Path(os.environ.get("AUTHOR_AGENT_ENGINE_ROOT") or (ROOT / ".author-agent" / "engine"))
        fixture_dir = str(ROOT / "qa" / "engine_contracts" / "fixtures" / "candidates")
        model = None
        demo = os.environ.get("AUTHOR_AGENT_ENGINE_DEMO") == "1"
        decision = None
        provider_models = {}
        cfg = config.load()
        live_override = os.environ.get("AUTHOR_AGENT_ENGINE_LIVE_MODEL")
        live = live_override == "1" if live_override is not None else (
            not demo and cfg.get("engineLiveModel") is True
        )
        if live:
            try:
                context_windows = json.loads(os.environ.get("AUTHOR_AGENT_CONTEXT_WINDOWS") or "{}")
            except ValueError:
                context_windows = {}
            if not isinstance(context_windows, dict):
                context_windows = {}
            output_limit = max(1, min(
                int(os.environ.get("AUTHOR_AGENT_ENGINE_MAX_OUTPUT_TOKENS") or 4096),
                int(cfg.get("maxOutputTokens") or 4096),
            ))
            if cfg.get("openrouterApiKey"):
                router_model = cfg.get("openrouterModel") or config.OPENROUTER_DEFAULT_MODEL
                provider_models["openrouter"] = SingleRequestOpenAIAdapter(
                    model=router_model,
                    api_key=cfg["openrouterApiKey"],
                    base_url="https://openrouter.ai/api/v1",
                    max_output_tokens=output_limit,
                    openrouter_flash=router_model == config.OPENROUTER_DEFAULT_MODEL,
                    context_window=context_windows.get(router_model),
                )
            if cfg.get("opencodeApiKey"):
                for provider, path in (("opencode", "inference"), ("opencode-go", "inference/go")):
                    provider_models[provider] = SingleRequestOpenAIAdapter(
                        model="glm-5.3-flash", api_key=str(cfg["opencodeApiKey"]),
                        base_url=f"https://opencode.ai/{path}/openai/v1",
                        max_output_tokens=output_limit, opencode=True,
                        context_window=context_windows.get("glm-5.3-flash"),
                    )
            if cfg.get("apiKey"):
                compatible_model = str(cfg.get("model") or config.OPENAI_COMPATIBLE_DEFAULT_MODEL)
                model = SingleRequestOpenAIAdapter(
                    model=compatible_model,
                    api_key=str(cfg["apiKey"]),
                    base_url=str(cfg.get("baseUrl") or "") or None,
                    max_output_tokens=output_limit,
                    context_window=context_windows.get(compatible_model),
                )
                demo = False
            decision_model = str(os.environ.get("AUTHOR_AGENT_DECISION_MODEL") or "").strip()
            decision_key = str(os.environ.get("AUTHOR_AGENT_DECISION_API_KEY")
                               or cfg.get("apiKey") or "").strip()
            if decision_model and decision_key:
                from engine.decisions import ModelDecisionAdapter
                decision = ModelDecisionAdapter(SingleRequestOpenAIAdapter(
                    model=decision_model,
                    api_key=decision_key,
                    base_url=str(os.environ.get("AUTHOR_AGENT_DECISION_BASE_URL")
                                 or cfg.get("baseUrl") or "") or None,
                    max_output_tokens=output_limit,
                    context_window=context_windows.get(decision_model),
                ))
        worker = IsolateWorker() if isolate_client.configured() else FakeWorker()
        budget_limits = None
        if os.environ.get("AUTHOR_AGENT_ENGINE_MODEL_ATTEMPT_LIMIT"):
            try:
                budget_limits = {"model_attempts_limit": max(
                    0, int(os.environ["AUTHOR_AGENT_ENGINE_MODEL_ATTEMPT_LIMIT"]))}
            except ValueError:
                budget_limits = None
        ENGINE_SERVICE = EngineService(root, model_adapter=model, worker=worker,
                                       fixture_dir=fixture_dir, demo=demo,
                                       decision_adapter=decision,
                                       default_budget_limits=budget_limits,
                                       provider_models=provider_models)
        return ENGINE_SERVICE


def chat_service() -> "ChatService":
    """One conversation facade per engine service (rebuilt if tests swap it)."""
    global CHAT_SERVICE
    service = engine_service()
    with ENGINE_LOCK:
        if CHAT_SERVICE is None or CHAT_SERVICE.service is not service:
            from engine.chat import ChatService
            CHAT_SERVICE = ChatService(service)
        return CHAT_SERVICE


def engine_error(exc: Exception, *, status: int = 400) -> tuple[dict, int]:
    if isinstance(exc, PolicyDenied):
        if exc.code == "bad_schema":
            return {"error": str(exc), "code": exc.code, "supported": False}, 422
        if exc.code == "oversized":
            return {"error": str(exc), "code": exc.code, "supported": False}, 413
        return {"error": str(exc), "code": exc.code, "supported": False}, 403
    if isinstance(exc, IdempotencyConflict):
        return {"error": str(exc), "code": "idempotency_conflict"}, 409
    if isinstance(exc, LedgerError):
        return {"error": str(exc), "code": "ledger_error"}, (404 if "Unknown" in str(exc) else 409)
    if isinstance(exc, ValueError):
        return {"error": str(exc), "code": "invalid_request"}, 422
    return {"error": str(exc), "code": "internal_error"}, 500


class Handler(BaseHTTPRequestHandler):
    server_version = "AuthorAgent/0.1"

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    def _allowed_hosts(self) -> set[str]:
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        extra = os.environ.get("AUTHOR_AGENT_ALLOWED_HOSTS", "")
        hosts.update(host.strip() for host in extra.split(",") if host.strip())
        return hosts

    def _host_ok(self) -> bool:
        return self.headers.get("Host", "") in self._allowed_hosts()

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        allowed = {f"http://{host}" for host in self._allowed_hosts()}
        allowed.update(f"https://{host}" for host in self._allowed_hosts())
        return origin in allowed

    def end_headers(self):
        # Monaco's AMD loader compiles module factories with the Function
        # constructor. Keep the policy same-origin only; do not add remote
        # script hosts. The worker is a same-origin script, not a blob.
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-eval'; worker-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'self'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, data, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, message: str, status: int = 400) -> None:
        self.send_json({"error": message}, status)

    def read_json(self, limit: int = 6 * 1024 * 1024) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0 or length > limit:
            raise ValueError("A JSON body is required")
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            raise ValueError("Content-Type must be application/json")
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("A JSON object is required")
        return value

    def drain_body(self, limit: int = 6 * 1024 * 1024) -> None:
        """Consume an ignored request body before an early response.

        Leaving unread bytes on a loopback connection makes Windows return an
        RST while the client reads the response.
        """
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return
        if length > limit:
            self.close_connection = True
            return
        self.rfile.read(length)

    def optional_json(self) -> dict:
        return self.read_json() if int(self.headers.get("Content-Length", "0")) else {}

    def send_package_download(self, slug, expected):
        with workspace_lock(slug):
            root = workspace.ws_path(slug)
            if not root.is_dir():
                return self.send_error_json("Workspace not found", 404)
            target = root / ".agent" / "export" / workspace.export_filename(slug)
            if not target.is_file():
                return self.send_error_json("No export exists yet", 404)
            workflow = workspace.summary(slug)["workflow"]
            if not workflow["canExport"]:
                return self.send_error_json(workflow["blocker"], 409)
            if expected is not None and expected != workflow["snapshot"]:
                return self.send_error_json("The saved package changed. Open Export ZIP for the current revision.", 409)
            if workspace.archive_status(slug, workflow)["status"] != "ready":
                return self.send_error_json("Generate a ZIP for the current revision before downloading.", 409)
            data = target.read_bytes()
        if target.name.isascii():
            disposition = f'attachment; filename="{target.name}"'
        else:
            fallback = workspace.safe_slug(slug) + "-domjudge.zip"
            disposition = f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{urllib.parse.quote(target.name)}'
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", disposition)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def static_file(self, path: str) -> None:
        rel = {"/": "studio.html", "": "studio.html", "/workbench": "index.html"}.get(path, path.lstrip("/"))
        target = (WEB / rel).resolve()
        if not target.is_relative_to(WEB.resolve()) or not target.is_file():
            self.send_error_json("Not found", 404)
            return
        body = target.read_bytes()
        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if mime.startswith("text/") or mime in ("application/javascript", "application/json"):
            mime += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_statement_pdf(self, slug: str, rel: str, thumbnail: bool = False) -> None:
        if rel not in ("problem.pdf", "problem_statement/problem.en.pdf", "statement/problem.en.pdf"):
            return self.send_error_json("Select a generated statement PDF.", 404)
        target = workspace.resolve(slug, rel)
        with target.open("rb") as handle:
            data = handle.read(32 * 1024 * 1024 + 1)
        if len(data) > 32 * 1024 * 1024:
            return self.send_error_json("The statement PDF exceeds the 32 MiB preview limit.", 413)
        if not data.startswith(b"%PDF-"):
            return self.send_error_json("The saved statement is not a PDF. Run Verify to rebuild it.", 422)
        mime = "application/pdf"
        if thumbnail:
            converter = shutil.which("pdftocairo")
            if not converter:
                return self.send_error_json("Install Poppler for a first-page preview, or open the PDF separately.", 503)
            try:
                page = subprocess.run([converter, "-png", "-singlefile", "-f", "1", "-l", "1",
                                       "-scale-to", "1400", "-", "-"], input=data,
                                      capture_output=True, timeout=8, check=False)
            except (OSError, subprocess.TimeoutExpired):
                return self.send_error_json("The first page could not be rendered.", 503)
            if page.returncode or not page.stdout.startswith(b"\x89PNG\r\n\x1a\n"):
                return self.send_error_json("The first page could not be rendered.", 422)
            data, mime = page.stdout, "image/png"
        self.send_response(200)
        self.send_header("Content-Type", mime)
        if not thumbnail:
            self.send_header("Content-Disposition", 'inline; filename="problem.pdf"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._host_ok():
            return self.send_error_json("Invalid Host", 403)
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if path == "/api/health":
                return self.send_json({"ok": True, "version": "0.1"})
            if path == "/api/state":
                return self.send_json({
                    "workspaces": workspace.list_workspaces(),
                    "settings": config.public(),
                    "tools": {
                        "python": sys.executable,
                        "gpp": shutil.which("g++") or "",
                        "pdflatex": shutil.which("pdflatex") or "",
                        "javac": shutil.which("javac") or "",
                    },
                })
            if path == "/api/settings":
                return self.send_json(config.public())
            if path == "/api/engine/capabilities":
                return self.send_json(engine_service().capabilities())
            if path == "/api/engine/runs":
                return self.send_json({"runs": engine_service().list_runs()})
            if path == "/api/engine/chat/receipt":
                return self.send_json(chat_service().receipt(
                    query.get("requestId", [""])[0], query.get("runId", [None])[0]))
            if path.startswith("/api/engine/runs/"):
                parts = [p for p in path.split("/") if p]
                if len(parts) < 4:
                    return self.send_error_json("Unknown engine route", 404)
                run_id = parts[3]
                if len(parts) == 4:
                    return self.send_json(chat_service().view(run_id))
                if len(parts) == 5 and parts[4] == "view":
                    return self.send_json(chat_service().view(run_id, studio=query.get("studio") == ["1"]))
                if len(parts) == 5 and parts[4] == "studio-sample":
                    return self.send_json(studio_sample.fix(engine_service(), run_id))
                if len(parts) == 5 and parts[4] == "studio-package":
                    return self.send_json(studio.package_link(engine_service(), run_id))
                if len(parts) == 5 and parts[4] == "events":
                    try:
                        after = max(0, int((query.get("after") or ["0"])[0]))
                    except ValueError:
                        after = 0
                    return self.send_json(engine_service().events(run_id, after))
                if len(parts) == 5 and parts[4] == "capabilities":
                    return self.send_json(engine_service().capabilities(run_id))
                if len(parts) == 6 and parts[4] == "campaigns":
                    try:
                        return self.send_json(engine_service().campaign_receipt(run_id, parts[5]))
                    except LedgerError as exc:
                        return self.send_error_json(str(exc), 404)
                if len(parts) == 5 and parts[4] == "chat":
                    try:
                        after = max(0, int((query.get("after") or ["0"])[0]))
                    except ValueError:
                        after = 0
                    before = int(query["before"][0]) if "before" in query else None
                    if before is not None and not 1 <= before < 2**63:
                        raise ValueError("Invalid transcript cursor")
                    return self.send_json(chat_service().transcript(run_id, after=after, before=before))
                if len(parts) == 5 and parts[4] == "artifacts":
                    store = engine_service().store(run_id)
                    return self.send_json({"artifacts": [
                        {"id": a["id"], "kind": a["kind"], "path": a["path"],
                         "blobHash": a["blob_hash"], "revision": a["revision"],
                         "sourceTurn": a["source_turn"], "current": a["current"],
                         "generation": a["generation"], "validity": a["validity"],
                         "validityReason": a["validity_reason"]}
                        for a in store.list_artifacts(run_id)
                    ]})
                if len(parts) == 5 and parts[4] == "decisions":
                    store = engine_service().store(run_id)
                    return self.send_json({"decisions": store.list_decision_records(run_id)})
                if len(parts) == 6 and parts[4] == "decisions":
                    store = engine_service().store(run_id)
                    try:
                        return self.send_json(store.get_decision_record(parts[5]))
                    except LedgerError as exc:
                        return self.send_error_json(str(exc), 404)
                if len(parts) == 6 and parts[4] == "artifacts":
                    store = engine_service().store(run_id)
                    try:
                        artifact = store.get_artifact(parts[5])
                        body = store.artifact_body(parts[5]).decode("utf-8", "replace")
                    except LedgerError as exc:
                        return self.send_error_json(str(exc), 404)
                    return self.send_json({**artifact, "text": body})
                if len(parts) == 6 and parts[4] == "responses":
                    from engine.store import LedgerError as _LE
                    try:
                        store = engine_service().store(run_id)
                        return self.send_json(store.get_response(parts[5]))
                    except _LE as exc:
                        return self.send_error_json(str(exc), 404)
                return self.send_error_json("Unknown engine route", 404)
            if path.startswith("/api/jobs/") and path.endswith("/events"):
                parts = [p for p in path.split("/") if p]
                job_id = parts[2] if len(parts) > 2 else ""
                try:
                    since = max(0, int((query.get("since") or ["0"])[0]))
                except ValueError:
                    since = 0
                with JOB_LOCK:
                    job = JOBS.get(job_id)
                    events = [event for event in (job or {}).get("events", []) if int(event.get("seq") or 0) > since]
                    next_seq = int((job or {}).get("nextSeq") or 1)
                    state = (job or {}).get("state")
                    phase = (job or {}).get("phase")
                if job is None:
                    return self.send_json({"error": "Job not found"}, 404)
                return self.send_json({"jobId": job_id, "state": state, "phase": phase,
                                       "events": events, "nextSeq": next_seq})
            if path.startswith("/api/jobs/"):
                job_id = path.split("/")[-1]
                with JOB_LOCK:
                    job = JOBS.get(job_id)
                    snapshot = json.loads(json.dumps(job)) if job else None
                return self.send_json(snapshot or {"error": "Job not found"}, 200 if snapshot else 404)
            if path.startswith("/api/workspaces/"):
                parts = [p for p in path.split("/") if p]
                slug = parts[2] if len(parts) > 2 else ""
                if len(parts) == 3:
                    return self.send_json(workspace.summary(slug))
                if len(parts) == 4 and parts[3] == "studio":
                    with workspace_lock(slug):
                        info = workspace.summary(slug)
                        return self.send_json({**info, "archive": workspace.archive_status(slug, info["workflow"])})
                if len(parts) == 4 and parts[3] == "studio-review":
                    with workspace_lock(slug):
                        return self.send_json(workspace.studio_review(slug, (query.get("snapshot") or [None])[0],
                                                                      (query.get("path") or [None])[0]))
                if len(parts) == 4 and parts[3] == "studio-job":
                    request_id = (query.get("requestId") or [None])[0]
                    with JOB_LOCK:
                        job = next((job for job in JOBS.values() if request_id and job.get("requestId") == request_id
                                    and job["slug"] == slug), None)
                        saved = json.loads(json.dumps(job)) if job else None
                    return self.send_json(saved or {"error": "Job receipt unavailable"}, 200 if saved else 404)
                if len(parts) == 4 and parts[3] == "answer-plan":
                    with workspace_lock(slug):
                        snapshot = workspace.require_snapshot(slug, (query.get("snapshot") or [None])[0])
                        return self.send_json({**verify.answer_plan(slug), "snapshot": snapshot})
                if len(parts) == 4 and parts[3] == "tree":
                    return self.send_json({"tree": workspace.tree(slug)})
                if len(parts) == 4 and parts[3] == "file":
                    rel = (query.get("path") or [""])[0]
                    with workspace_lock(slug):
                        return self.send_json({**workspace.read_text(slug, rel), "hash": studio.file_hash(slug, rel)})
                if len(parts) == 4 and parts[3] == "statement-pdf":
                    return self.send_statement_pdf(slug, (query.get("path") or [""])[0],
                                                   query.get("preview") == ["first-page"])
                if len(parts) == 4 and parts[3] == "changes":
                    return self.send_json({"changes": workspace.changes(slug)})
                if len(parts) == 6 and parts[3] == "changes" and parts[5] == "diff":
                    entry = next((c for c in workspace.changes(slug) if c["id"] == parts[4]), None)
                    if entry is None:
                        return self.send_error_json("Change not found", 404)
                    if entry.get("reverted"):
                        body = "(change reverted)"
                    else:
                        body = workspace.diff(entry.get("before") or "", entry.get("after") or "", entry["path"])
                    return self.send_json({
                        "id": entry["id"],
                        "path": entry["path"],
                        "diff": body,
                        "before": entry.get("before") or "",
                        "after": entry.get("after") or "",
                    })
                if len(parts) == 4 and parts[3] == "chats":
                    return self.send_json(workspace.list_chats(slug))
                if len(parts) == 5 and parts[3] == "chats":
                    return self.send_json(workspace.get_chat(slug, parts[4]))
                if len(parts) == 6 and parts[3] == "chats" and parts[5] == "plan":
                    return self.send_json(workspace.get_plan(slug, parts[4]))
                if len(parts) == 6 and parts[3] == "chats" and parts[5] == "history":
                    return self.send_json({"history": graph_agent.list_history(slug, parts[4])})
                if len(parts) == 4 and parts[3] == "snapshots":
                    chat_id = (query.get("chatId") or [""])[0]
                    return self.send_json({"snapshots": workspace.list_snapshots(slug, chat_id)})
                if len(parts) == 4 and parts[3] == "mcp":
                    return self.send_json({
                        "tools": mcp_server.TOOLS,
                        "consent": mcp_consent.state(slug),
                        "protocol": mcp_server.PROTOCOL,
                        "server": "icpc-author-mcp",
                    })
                if len(parts) == 6 and parts[3] == "changes" and parts[5] == "hunks":
                    entry = next((c for c in workspace.changes(slug) if c["id"] == parts[4]), None)
                    if entry is None:
                        return self.send_error_json("Change not found", 404)
                    return self.send_json({"id": entry["id"], "path": entry["path"], "hunks": workspace.parse_hunks(workspace.diff(entry.get("before") or "", entry.get("after") or "", entry["path"]))})
                if len(parts) == 4 and parts[3] == "conversation":
                    active = workspace.list_chats(slug).get("activeChat")
                    chat_id = (query.get("chatId") or [active])[0]
                    return self.send_json(workspace.get_chat(slug, chat_id))
                if len(parts) == 4 and parts[3] == "report":
                    return self.send_json(workspace.state(slug).get("lastReport") or {"status": "none"})
                if len(parts) == 4 and parts[3] == "download":
                    return self.send_package_download(slug, query.get("snapshot", [None])[0])
                return self.send_error_json("Unknown workspace route", 404)
            return self.static_file(path)
        except FileNotFoundError as exc:
            return self.send_error_json(str(exc), 404)
        except (PolicyDenied, IdempotencyConflict, LedgerError) as exc:
            payload, status = engine_error(exc)
            return self.send_json(payload, status)
        except (ValueError, KeyError) as exc:
            return self.send_error_json(str(exc), 400)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            return self.send_error_json(str(exc), 500)

    def do_PATCH(self):
        if not self._host_ok() or not self._same_origin():
            self.drain_body()
            return self.send_error_json("Invalid origin", 403)
        path = urllib.parse.urlparse(self.path).path
        parts = [p for p in path.split("/") if p]
        try:
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "workspaces" and parts[3] == "chats":
                slug, chat_id = workspace.safe_slug(parts[2]), parts[4]
                with CHAT_LOCK:
                    if slug in ACTIVE_CHATS:
                        return self.send_error_json("A chat turn is already running for this problem", 409)
                body = self.read_json()
                return self.send_json(workspace.rename_chat(slug, chat_id, body.get("title")))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "workspaces" and parts[3] == "files":
                body = self.read_json()
                with workspace_lock(parts[2]):
                    return self.send_json(workspace.rename_entry(parts[2], body.get("path"), body.get("newPath")))
            return self.send_error_json("Not found", 404)
        except FileNotFoundError as exc:
            return self.send_error_json(str(exc), 404)
        except ValueError as exc:
            return self.send_error_json(str(exc), 400)

    def do_DELETE(self):
        if not self._host_ok() or not self._same_origin():
            self.drain_body()
            return self.send_error_json("Invalid origin", 403)
        path = urllib.parse.urlparse(self.path).path
        parts = [p for p in path.split("/") if p]
        try:
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "workspaces" and parts[3] == "chats":
                slug, chat_id = workspace.safe_slug(parts[2]), parts[4]
                with CHAT_LOCK:
                    if slug in ACTIVE_CHATS:
                        return self.send_error_json("A chat turn is already running for this problem", 409)
                workspace.delete_chat(slug, chat_id)
                graph_agent.delete_thread(slug, chat_id)
                return self.send_json(workspace.list_chats(slug))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "workspaces" and parts[3] == "files":
                query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                rel = (query.get("path") or [""])[0]
                with workspace_lock(parts[2]):
                    return self.send_json(workspace.delete_entry(parts[2], rel))
            return self.send_error_json("Not found", 404)
        except FileNotFoundError as exc:
            return self.send_error_json(str(exc), 404)
        except ValueError as exc:
            return self.send_error_json(str(exc), 400)

    def do_POST(self):
        if not self._host_ok() or not self._same_origin():
            self.drain_body()
            return self.send_error_json("Invalid origin", 403)
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/api/studio/editor-tool":
                return self.send_json(studio.editor_tool(self.read_json()))
            if path == "/api/studio/sample":
                body = self.read_json()
                return self.send_json(studio_sample.create(chat_service(), body.get("clientRequestId"), workspace_lock), 201)
            if path == "/api/engine/chat":
                body = self.read_json()
                result = chat_service().start(
                    str(body.get("message") or body.get("idea") or ""),
                    client_request_id=body.get("clientRequestId"),
                    model_provider=body.get("provider", "custom"),
                    title=body.get("title"),
                )
                return self.send_json(result, 201)
            if path == "/api/engine/runs":
                body = self.read_json()
                service = engine_service()
                created = service.create_run(
                    workspace_id=str(body.get("workspaceId") or "local"),
                    idea=str(body.get("idea") or body.get("goal") or ""),
                    client_request_id=body.get("clientRequestId"),
                )
                service.request_pump(created["runId"])
                return self.send_json({**created, "capabilities": service.capabilities(created["runId"])}, 201)
            if path.startswith("/api/engine/runs/"):
                parts = [p for p in path.split("/") if p]
                run_id = parts[3] if len(parts) > 3 else ""
                service = engine_service()
                if len(parts) == 5 and parts[4] == "title":
                    return self.send_json(studio.rename_problem(service, run_id, self.read_json(), workspace_lock))
                if len(parts) == 5 and parts[4] in ("title-preview", "studio-package-preview"):
                    return self.send_json(studio.problem_preview(
                        service, run_id, self.read_json(), workspace_lock, linking=parts[4] == "studio-package-preview"))
                if len(parts) == 5 and parts[4] == "studio-package":
                    return self.send_json(studio.link_package(service, run_id, self.read_json(), workspace_lock), 201)
                if len(parts) == 5 and parts[4] == "inputs":
                    body = self.read_json()
                    return self.send_json(service.submit_input(run_id, body), 202)
                if len(parts) == 5 and parts[4] == "messages":
                    body = self.read_json()
                    return self.send_json(chat_service().message(
                        run_id, str(body.get("message") or ""),
                        client_request_id=body.get("clientRequestId"),
                        recover_input_id=body.get("recoverInputId"),
                        expected_interaction_id=body.get("expectedInteractionId"),
                    ), 200)
                if len(parts) == 5 and parts[4] == "contributions":
                    # Contributions must enter through the durable input/inbox
                    # path so the barrier and idempotency apply before ack.
                    self.drain_body()
                    return self.send_error_json(
                        "Use POST inputs with kind=contribute; direct contribution writes are not accepted",
                        422)
                if len(parts) == 7 and parts[4] == "interactions" and parts[6] == "responses":
                    body = self.read_json()
                    receipt = service.submit_response(run_id, parts[5], body)
                    if receipt.get("status") == "conflict":
                        return self.send_json(receipt, 409)
                    return self.send_json(receipt, 200)
                if len(parts) == 5 and parts[4] in ("exports", "restores", "approve-export",
                                                    "export", "restore"):
                    self.drain_body()
                    return self.send_json(service.refuse(run_id, parts[4]), 501)
                self.drain_body()
                return self.send_error_json("Unknown engine route", 404)
            if path.startswith("/api/jobs/") and path.endswith("/cancel"):
                self.drain_body()
                parts = [p for p in path.split("/") if p]
                job_id = parts[2] if len(parts) > 2 else ""
                receipt = request_job_cancel(job_id)
                if receipt is None:
                    return self.send_error_json("Job not found", 404)
                return self.send_json(receipt)
            if path == "/api/settings":
                body = self.read_json()
                update = {}
                for key in ("baseUrl", "model", "temperature", "maxToolRounds", "reviewWrites", "contextBudgetTokens", "modelWindowTokens", "maxOutputTokens", "summaryTriggerTokens", "summaryKeepMessages", "inputPricePerMillion", "outputPricePerMillion", "fallbackModel", "fallbackBaseUrl", "fallbackApiKey", "maxRetries", "requestTimeoutSeconds", "judge0Url"):
                    if key in body:
                        update[key] = body[key]
                if "engineLiveModel" in body:
                    if not isinstance(body["engineLiveModel"], bool):
                        return self.send_error_json("Live model setting must be true or false.", 422)
                    update["engineLiveModel"] = body["engineLiveModel"]
                if body.get("clearKey"):
                    update["apiKey"] = ""
                elif str(body.get("apiKey") or "").strip():
                    update["apiKey"] = str(body["apiKey"]).strip()
                for field, clear_field, label in (
                    ("opencodeApiKey", "clearOpenCodeKey", "OpenCode"),
                    ("openrouterApiKey", "clearOpenRouterKey", "OpenRouter"),
                ):
                    if body.get(clear_field) is True:
                        update[field] = ""
                    elif str(body.get(field) or "").strip():
                        key = str(body[field]).strip()
                        if len(key) > 512 or any(char.isspace() for char in key):
                            return self.send_error_json(f"Enter a single {label} API key.", 422)
                        update[field] = key
                if "openrouterModel" in body:
                    model = str(body["openrouterModel"] or "").strip()
                    if model and (
                        len(model) > 160 or not re.fullmatch(r"[\w.-]+/[\w.:-]+", model, re.ASCII)
                    ):
                        return self.send_error_json("Enter an OpenRouter model ID in provider/model form.", 422)
                    update["openrouterModel"] = model or config.OPENROUTER_DEFAULT_MODEL
                config.save(update)
                return self.send_json(config.public())
            if path == "/api/workspaces":
                body = self.read_json()
                result = workspace.create(
                    body.get("name", ""), body.get("idea", ""),
                    {k: body.get(k) for k in ("author", "shortName", "timeLimit", "memoryMb", "source", "license", "rightsOwner", "color")},
                )
                return self.send_json(result, 201)
            if path.startswith("/api/workspaces/"):
                parts = [p for p in path.split("/") if p]
                slug = workspace.safe_slug(parts[2])
                if len(parts) == 4 and parts[3] == "files":
                    body = self.read_json()
                    with workspace_lock(slug):
                        if str(body.get("kind") or "file") == "dir":
                            return self.send_json(workspace.create_folder(slug, str(body.get("path") or "")))
                        return self.send_json(workspace.create_file(slug, str(body.get("path") or "")))
                if len(parts) == 4 and parts[3] == "file":
                    body = self.read_json()
                    rel = body.get("path", "")
                    with workspace_lock(slug):
                        if "expectedHash" in body and body["expectedHash"] != studio.file_hash(slug, rel):
                            return self.send_error_json("This file changed on disk. Your draft has been kept.", 409)
                        origin = body.get("artifactOrigin")
                        if origin is None:
                            result = workspace.write_text(slug, rel, body.get("content", ""), source="user")
                        else:
                            service = engine_service()
                            if not isinstance(origin, dict) or not isinstance(origin.get("runId"), str):
                                raise ValueError("Invalid artifact origin")
                            run_id = origin["runId"]
                            store = service.store(run_id)
                            with store.tx() as conn:
                                artifact = conn.execute(
                                    "SELECT current, validity, revision FROM artifacts WHERE id=? AND run_id=?",
                                    (origin.get("artifactId"), run_id),
                                ).fetchone()
                                if (not artifact or not artifact["current"] or artifact["validity"] not in ("current", "revalidated")
                                        or artifact["revision"] != origin.get("revision")):
                                    return self.send_error_json("The conversation artifact changed. Your draft was kept.", 409)
                                result = workspace.write_text(slug, rel, body.get("content", ""), source="artifact copy",
                                                              artifact_origin={key: origin[key] for key in ("runId", "artifactId", "revision")})
                        return self.send_json({**result, "hash": studio.file_hash(slug, rel)})
                if len(parts) == 4 and parts[3] == "review":
                    body = self.optional_json()
                    with workspace_lock(slug):
                        try:
                            reviewed = workspace.mark_reviewed(slug, body.get("expectedSnapshot"))
                        except workspace.SnapshotConflict as exc:
                            return self.send_error_json(str(exc), 409)
                        return self.send_json(reviewed)
                if len(parts) == 4 and parts[3] == "mcp":
                    body = self.read_json()
                    return self.send_json(mcp_consent.update(slug, body))
                if len(parts) == 5 and parts[3] == "mcp" and parts[4] == "test":
                    body = self.read_json()
                    return self.send_json(mcp_probe(slug, str(body.get("tool") or ""), body.get("arguments") or {}))
                if len(parts) == 6 and parts[3] == "changes" and parts[5] == "revert":
                    return self.send_json(workspace.revert(slug, parts[4]))
                if len(parts) == 6 and parts[3] == "changes" and parts[5] == "apply-hunks":
                    body = self.read_json()
                    with workspace_lock(slug):
                        return self.send_json(workspace.apply_hunks(slug, parts[4], body.get("selected")))
                if len(parts) == 4 and parts[3] == "chats":
                    return self.send_json(workspace.create_chat(slug), 201)
                if len(parts) == 4 and parts[3] == "chat":
                    body = self.read_json()
                    message = str(body.get("message") or "").strip()
                    if not message:
                        raise ValueError("Write a message first")
                    chat_id = str(body.get("chatId") or "").strip()
                    if not chat_id:
                        chat_id = workspace.list_chats(slug).get("activeChat")
                    workspace.get_chat(slug, chat_id)
                    workspace.set_active_chat(slug, chat_id)
                    mode = str(body.get("mode") or "author")
                    selected_context = body.get("context") if isinstance(body.get("context"), list) else []
                    with CHAT_LOCK:
                        if slug in ACTIVE_CHATS:
                            raise ValueError("A chat turn is already running for this problem")
                        ACTIVE_CHATS.add(slug)

                    def run_chat(emit, cancelled):
                        return graph_agent.run_turn(
                            slug, chat_id, message, emit, cancelled,
                            mode=mode, selected_context=selected_context,
                        )

                    return self.send_json(start_job("Agent turn", slug, run_chat, chat_id=chat_id, owns_chat=True))
                if len(parts) == 8 and parts[3] == "chats" and parts[5] == "history" and parts[7] == "restore":
                    chat_id, checkpoint = parts[4], parts[6]
                    with CHAT_LOCK:
                        if slug in ACTIVE_CHATS:
                            raise ValueError("A chat turn is already running")
                    return self.send_json(graph_agent.restore_history(slug, chat_id, checkpoint))
                if len(parts) == 5 and parts[3] == "snapshots" and parts[4] == "restore":
                    body = self.read_json()
                    with workspace_lock(slug):
                        return self.send_json(workspace.restore_snapshot(slug, str(body.get("chatId") or ""), str(body.get("snapshotId") or "")))
                if len(parts) == 6 and parts[3] == "chats" and parts[5] == "resume":
                    body = self.read_json()
                    chat_id = parts[4]
                    decisions = body.get("decisions")
                    clarification = body.get("clarification")
                    if clarification is None and "answers" in body:
                        clarification = {"answers": body.get("answers")}
                    if not decisions and clarification is None:
                        raise ValueError("Approval decisions or clarification answers are required")
                    workspace.get_chat(slug, chat_id)
                    with CHAT_LOCK:
                        if slug in ACTIVE_CHATS:
                            raise ValueError("A chat turn is already running for this problem")
                        ACTIVE_CHATS.add(slug)

                    def run_resume(emit, cancelled):
                        return graph_agent.resume_turn(slug, chat_id, decisions, emit, cancelled, clarification=clarification)

                    return self.send_json(start_job("Resume approval", slug, run_resume, chat_id=chat_id, owns_chat=True))
                if len(parts) == 5 and parts[3] == "chat" and parts[4] == "reset":
                    return self.send_json(workspace.create_chat(slug), 201)
                if len(parts) == 4 and parts[3] == "verify":
                    body = self.read_json()
                    write_answers = bool(body.get("writeAnswers"))

                    def run_verify(emit, cancelled):
                        if "expectedSnapshot" in body:
                            studio.require_snapshot(slug, body)
                        report = verify.verify(slug, write_answers=write_answers, cancelled=cancelled)
                        emit("report", report)
                        return report

                    return self.send_json(start_job("Package verification", slug, run_verify, studio_request=body))
                if len(parts) == 4 and parts[3] == "export":
                    body = self.optional_json()
                    def run_export(emit, cancelled):
                        studio.require_snapshot(slug, body)
                        result = verify.export_package(slug)
                        emit("export", result)
                        return result

                    return self.send_json(start_job("Package export", slug, run_export, studio_request=body))
                if len(parts) == 4 and parts[3] == "answers":
                    body = self.optional_json()
                    def run_answers(emit, cancelled):
                        if "expectedSnapshot" in body:
                            studio.require_snapshot(slug, body)
                        result = verify.build_answers(slug, cancelled=cancelled)
                        emit("answers", result)
                        return result

                    return self.send_json(start_job("Generate answers", slug, run_answers, studio_request=body))
                if len(parts) == 4 and parts[3] == "run":
                    body = self.read_json()
                    rel, stdin = str(body.get("path") or ""), str(body.get("stdin") or "")
                    if body.get("asJob") is True:
                        def run_code(emit, cancelled):
                            snapshot = studio.require_snapshot(slug, body)
                            return verify.run_case(slug, rel, body, snapshot)
                        return self.send_json(start_job("Run code", slug, run_code, studio_request=body))
                    return self.send_json(verify.run_source(slug, rel, stdin))
                if len(parts) == 5 and parts[3] == "isolate" and parts[4] == "run":
                    body = self.read_json()
                    return self.send_json(isolate_client.run_file(
                        slug, str(body.get("path") or ""), str(body.get("stdin") or ""),
                        time_limit=2.0, memory_mb=256, fsize_mb=8,
                    ))
                if len(parts) == 5 and parts[3] == "judge0" and parts[4] == "run":
                    body = self.read_json()
                    cfg = config.load()
                    if not cfg.get("judge0Url"):
                        raise ValueError("Judge0 is not configured in Settings")
                    return self.send_json(judge0_adapter.run_file(
                        slug, str(body.get("path") or ""), str(body.get("stdin") or ""),
                        base_url=str(cfg.get("judge0Url") or ""),
                        token=str(cfg.get("judge0Token") or ""),
                        time_limit=2.0, memory_mb=256,
                    ))
                if len(parts) == 4 and parts[3] == "measure-limits":
                    body = self.optional_json()
                    def run_limits(emit, cancelled):
                        if "expectedSnapshot" in body:
                            studio.require_snapshot(slug, body)
                        result = verify.measure_limits(slug, cancelled=cancelled)
                        emit("limits", result)
                        return result

                    return self.send_json(start_job("Measure limits", slug, run_limits, studio_request=body))
            self.drain_body()
            return self.send_error_json("Unknown route", 404)
        except FileNotFoundError as exc:
            return self.send_error_json(str(exc), 404)
        except studio.EditConflict as exc:
            return self.send_error_json(str(exc), 409)
        except (PolicyDenied, IdempotencyConflict, LedgerError) as exc:
            payload, status = engine_error(exc)
            return self.send_json(payload, status)
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            return self.send_error_json(str(exc), 400)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            return self.send_error_json(str(exc), 500)


def main() -> None:
    parser = argparse.ArgumentParser(description="ICPC Author Agent")
    parser.add_argument("--host", default=os.environ.get("AUTHOR_AGENT_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    winutil.prepare()
    config.load()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    shown = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    print(f"ICPC Author Agent http://{shown}:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
