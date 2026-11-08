"""Loopback-only server for the ICPC Author Agent.

Run: python server.py --port 8787
Then open http://127.0.0.1:8787/
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import pathlib
import shutil
import sys
import threading
import time
import traceback
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import agent
import config
import graph_agent
import verify
import winutil
import workspace

ROOT = pathlib.Path(__file__).resolve().parent
WEB = ROOT / "web"
JOBS: dict[str, dict] = {}
JOB_LOCK = threading.Lock()
CHAT_LOCK = threading.Lock()
ACTIVE_CHATS: set[str] = set()
WORKSPACE_LOCKS: dict[str, threading.Lock] = {}
WORKSPACE_LOCKS_GUARD = threading.Lock()


def workspace_lock(slug: str) -> threading.Lock:
    with WORKSPACE_LOCKS_GUARD:
        return WORKSPACE_LOCKS.setdefault(slug, threading.Lock())


def now() -> str:
    return time.strftime("%H:%M:%S")


def start_job(title: str, slug: str | None, fn, chat_id: str | None = None) -> dict:
    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "title": title, "slug": slug, "chatId": chat_id, "state": "running",
           "cancelRequested": False, "createdAt": now(), "events": [], "result": None, "error": None}

    def emit(kind: str, data) -> None:
        with JOB_LOCK:
            job["events"].append({"at": now(), "kind": kind, "data": data})
            if len(job["events"]) > 600:
                job["events"] = job["events"][-600:]

    def cancelled() -> bool:
        return bool(job.get("cancelRequested"))

    run_lock = workspace_lock(slug) if slug else None

    def run() -> None:
        if run_lock is not None:
            run_lock.acquire()
        try:
            result = fn(emit, cancelled)
            with JOB_LOCK:
                if job.get("cancelRequested"):
                    job["state"] = "cancelled"
                elif isinstance(result, dict) and result.get("paused"):
                    job["state"] = "paused"
                else:
                    job["state"] = "done"
                job["result"] = result
        except Exception as exc:  # noqa: BLE001 - job reports its own failure
            if job.get("cancelRequested"):
                with JOB_LOCK:
                    job["state"] = "cancelled"
                    job["events"].append({"at": now(), "kind": "cancelled", "data": {}})
                return
            traceback.print_exc()
            with JOB_LOCK:
                job["state"] = "error"
                job["error"] = f"{type(exc).__name__}: {exc}"
                job["events"].append({"at": now(), "kind": "error", "data": {"error": job["error"]}})
        finally:
            if run_lock is not None:
                run_lock.release()

    with JOB_LOCK:
        JOBS[job_id] = job
        if len(JOBS) > 80:
            for key in list(JOBS)[:20]:
                if JOBS[key]["state"] in ("done", "error", "cancelled"):
                    JOBS.pop(key, None)

    def watchdog() -> None:
        time.sleep(20 * 60)
        with JOB_LOCK:
            if job["state"] != "running":
                return
            job["cancelRequested"] = True
            job["events"].append({
                "at": now(), "kind": "timeout",
                "data": {"message": "Job exceeded the 20-minute limit and was stopped."},
            })
        time.sleep(60)
        with JOB_LOCK:
            if job["state"] == "running":
                job["state"] = "error"
                job["error"] = "Job exceeded the 20-minute limit."

    threading.Thread(target=run, daemon=True).start()
    threading.Thread(target=watchdog, daemon=True).start()
    return job


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
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'self'")
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

    def static_file(self, path: str) -> None:
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
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
                if len(parts) == 4 and parts[3] == "tree":
                    return self.send_json({"tree": workspace.tree(slug)})
                if len(parts) == 4 and parts[3] == "file":
                    rel = (query.get("path") or [""])[0]
                    return self.send_json(workspace.read_text(slug, rel))
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
                    return self.send_json({"id": entry["id"], "path": entry["path"], "diff": body})
                if len(parts) == 4 and parts[3] == "chats":
                    return self.send_json(workspace.list_chats(slug))
                if len(parts) == 5 and parts[3] == "chats":
                    return self.send_json(workspace.get_chat(slug, parts[4]))
                if len(parts) == 6 and parts[3] == "chats" and parts[5] == "plan":
                    return self.send_json(workspace.get_plan(slug, parts[4]))
                if len(parts) == 4 and parts[3] == "conversation":
                    active = workspace.list_chats(slug).get("activeChat")
                    chat_id = (query.get("chatId") or [active])[0]
                    return self.send_json(workspace.get_chat(slug, chat_id))
                if len(parts) == 4 and parts[3] == "report":
                    return self.send_json(workspace.state(slug).get("lastReport") or {"status": "none"})
                if len(parts) == 4 and parts[3] == "download":
                    target = workspace.ws_path(slug) / ".agent" / "export" / f"{workspace.safe_slug(slug)}-domjudge.zip"
                    if not target.is_file():
                        return self.send_error_json("No export exists yet", 404)
                    body = target.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/zip")
                    self.send_header("Content-Disposition", f'attachment; filename="{target.name}"')
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                return self.send_error_json("Unknown workspace route", 404)
            return self.static_file(path)
        except FileNotFoundError as exc:
            return self.send_error_json(str(exc), 404)
        except (ValueError, KeyError) as exc:
            return self.send_error_json(str(exc), 400)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            return self.send_error_json(str(exc), 500)

    def do_POST(self):
        if not self._host_ok() or not self._same_origin():
            return self.send_error_json("Invalid origin", 403)
        path = urllib.parse.urlparse(self.path).path
        try:
            if path.startswith("/api/jobs/") and path.endswith("/cancel"):
                parts = [p for p in path.split("/") if p]
                job_id = parts[2] if len(parts) > 2 else ""
                with JOB_LOCK:
                    job = JOBS.get(job_id)
                    if job is not None:
                        job["cancelRequested"] = True
                if job is None:
                    return self.send_error_json("Job not found", 404)
                return self.send_json({"ok": True, "jobId": job_id})
            if path == "/api/settings":
                body = self.read_json()
                update = {}
                for key in ("baseUrl", "model", "temperature", "maxToolRounds", "reviewWrites"):
                    if key in body:
                        update[key] = body[key]
                if body.get("clearKey"):
                    update["apiKey"] = ""
                elif str(body.get("apiKey") or "").strip():
                    update["apiKey"] = str(body["apiKey"]).strip()
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
                slug = parts[2]
                if len(parts) == 4 and parts[3] == "file":
                    body = self.read_json()
                    result = workspace.write_text(slug, body.get("path", ""), body.get("content", ""), source="user")
                    return self.send_json(result)
                if len(parts) == 4 and parts[3] == "review":
                    return self.send_json(workspace.mark_reviewed(slug))
                if len(parts) == 6 and parts[3] == "changes" and parts[5] == "revert":
                    return self.send_json(workspace.revert(slug, parts[4]))
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
                        try:
                            return graph_agent.run_turn(
                                slug, chat_id, message, emit, cancelled,
                                mode=mode, selected_context=selected_context,
                            )
                        finally:
                            with CHAT_LOCK:
                                ACTIVE_CHATS.discard(slug)

                    return self.send_json(start_job("Agent turn", slug, run_chat, chat_id=chat_id))
                if len(parts) == 6 and parts[3] == "chats" and parts[5] == "resume":
                    body = self.read_json()
                    chat_id = parts[4]
                    decisions = body.get("decisions")
                    if not decisions:
                        raise ValueError("Approval decisions are required")
                    workspace.get_chat(slug, chat_id)
                    with CHAT_LOCK:
                        if slug in ACTIVE_CHATS:
                            raise ValueError("A chat turn is already running for this problem")
                        ACTIVE_CHATS.add(slug)

                    def run_resume(emit, cancelled):
                        try:
                            return graph_agent.resume_turn(slug, chat_id, decisions, emit, cancelled)
                        finally:
                            with CHAT_LOCK:
                                ACTIVE_CHATS.discard(slug)

                    return self.send_json(start_job("Resume approval", slug, run_resume, chat_id=chat_id))
                if len(parts) == 5 and parts[3] == "chat" and parts[4] == "reset":
                    return self.send_json(workspace.create_chat(slug), 201)
                if len(parts) == 4 and parts[3] == "verify":
                    body = self.read_json()
                    write_answers = bool(body.get("writeAnswers"))

                    def run_verify(emit, cancelled):
                        report = verify.verify(slug, write_answers=write_answers, cancelled=cancelled)
                        emit("report", report)
                        return report

                    return self.send_json(start_job("Package verification", slug, run_verify))
                if len(parts) == 4 and parts[3] == "export":
                    def run_export(emit, cancelled):
                        result = verify.export_package(slug)
                        emit("export", result)
                        return result

                    return self.send_json(start_job("Package export", slug, run_export))
                if len(parts) == 4 and parts[3] == "answers":
                    def run_answers(emit, cancelled):
                        result = verify.build_answers(slug, cancelled=cancelled)
                        emit("answers", result)
                        return result

                    return self.send_json(start_job("Generate answers", slug, run_answers))
                if len(parts) == 4 and parts[3] == "run":
                    body = self.read_json()
                    return self.send_json(verify.run_source(slug, str(body.get("path") or ""), str(body.get("stdin") or "")))
                if len(parts) == 4 and parts[3] == "measure-limits":
                    def run_limits(emit, cancelled):
                        result = verify.measure_limits(slug, cancelled=cancelled)
                        emit("limits", result)
                        return result

                    return self.send_json(start_job("Measure limits", slug, run_limits))
            return self.send_error_json("Unknown route", 404)
        except FileNotFoundError as exc:
            return self.send_error_json(str(exc), 404)
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
