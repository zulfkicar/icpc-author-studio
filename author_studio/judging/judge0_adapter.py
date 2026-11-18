"""Optional Judge0 quick-run adapter.

Judge0 is **not** the verification authority. It is a convenient
multi-language quick-run backend for the IDE. The deterministic verifier keeps
using the Isolate-style executor because Judge0's community edition does not
orchestrate testlib interactive problems, ICPC output-validator feedback
directories, or the package's `input_validators/`.

Enable it only by setting ``AUTHOR_AGENT_JUDGE0_URL`` (and optionally
``AUTHOR_AGENT_JUDGE0_TOKEN``). See docs/JUDGE0-EVALUATION.md.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from author_studio.packages import workspace

LANGUAGE_IDS = {
    "c": 50,
    "cpp": 54,
    "c++": 54,
    "py": 71,
    "python": 71,
    "java": 62,
}


def configured() -> bool:
    return bool(os.environ.get("AUTHOR_AGENT_JUDGE0_URL"))


def _request(base_url: str, source: str, language: str, stdin: str, token: str,
             time_limit: float, memory_mb: int) -> dict:
    language_id = LANGUAGE_IDS.get(str(language).lower())
    if language_id is None:
        raise ValueError(f"Judge0 does not map language {language!r}")
    payload = {
        "source_code": source,
        "language_id": language_id,
        "stdin": stdin or "",
        "cpu_time_limit": max(0.1, float(time_limit)),
        "memory_limit": max(16, int(memory_mb)) * 1024,
        "wall_time_limit": max(1.0, float(time_limit) * 2 + 5),
        "max_file_size": 4096,
        # Judge0 CE 1.13.1 targets cgroup v1. These flags make it use Isolate's
        # rlimit path, which works on the cgroup v2 host used here.
        "enable_per_process_and_thread_time_limit": True,
        "enable_per_process_and_thread_memory_limit": True,
    }
    query = urllib.parse.urlencode({"base64_encoded": "false", "wait": "true"})
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/submissions?{query}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **({"X-Auth-Token": token} if token else {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(10.0, float(time_limit) + 20)) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"Judge0 HTTP {exc.code}: {detail[:1000]}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Judge0 request failed: {exc}") from exc


def is_blocked_path(path: str) -> bool:
    """Secret tests and answer files must never leave the workspace."""
    normalized = str(path or "").replace("\\", "/").lstrip("./")
    return normalized.startswith("data/secret/") or normalized.lower().endswith(".ans")


def run_file(slug: str, path: str, stdin: str = "", *, base_url: str | None = None,
             token: str | None = None, time_limit: float = 2.0, memory_mb: int = 256) -> dict:
    """Read a workspace source file and run it through Judge0."""
    if is_blocked_path(path):
        raise ValueError("Judge0 quick run is blocked for secret tests and .ans answer files")
    content = workspace.read_text(slug, path).get("content") or ""
    language = path.rsplit(".", 1)[-1] if "." in path else "cpp"
    result = quick_run(
        content, language, stdin,
        base_url=base_url, token=token, time_limit=time_limit, memory_mb=memory_mb,
    )
    result["path"] = path
    return result


def quick_run(source: str, language: str = "cpp", stdin: str = "", *,
              base_url: str | None = None, token: str | None = None,
              time_limit: float = 2.0, memory_mb: int = 256) -> dict:
    base_url = base_url or os.environ.get("AUTHOR_AGENT_JUDGE0_URL", "")
    if not base_url:
        raise RuntimeError("Judge0 is not configured; set AUTHOR_AGENT_JUDGE0_URL")
    token = token if token is not None else os.environ.get("AUTHOR_AGENT_JUDGE0_TOKEN", "")
    payload = _request(base_url, source, language, stdin, token, time_limit, memory_mb)
    status = payload.get("status") or {}
    status_id = status.get("id")
    description = str(status.get("description") or "")
    # Judge0: 3 = accepted, 4 = wrong answer (when expected_output is set).
    ok = status_id in (1, 2, 3) and not payload.get("stderr") and not payload.get("compile_output")
    return {
        "ok": ok,
        "status": description or str(status_id),
        "statusId": status_id,
        "stdout": payload.get("stdout") or "",
        "stderr": payload.get("stderr") or "",
        "compileOutput": payload.get("compile_output") or "",
        "message": payload.get("message") or "",
        "time": payload.get("time"),
        "memory": payload.get("memory"),
        "token": payload.get("token"),
        "source": "judge0",
        "verificationAuthority": False,
    }
