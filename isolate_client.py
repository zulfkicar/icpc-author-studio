"""Client for the real Isolate worker (isolate_worker.py)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import workspace


def configured() -> bool:
    return bool(os.environ.get("AUTHOR_AGENT_ISOLATE_URL"))


def _base() -> str:
    url = (os.environ.get("AUTHOR_AGENT_ISOLATE_URL") or "").rstrip("/")
    if not url:
        raise RuntimeError("Isolate is not configured; set AUTHOR_AGENT_ISOLATE_URL")
    return url


def _headers() -> dict:
    token = os.environ.get("AUTHOR_AGENT_ISOLATE_TOKEN") or ""
    return {"X-Isolate-Token": token} if token else {}


def health() -> dict:
    request = urllib.request.Request(_base() + "/health", headers=_headers())
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def run(source: str, language: str = "cpp", stdin: str = "", *,
        time_limit: float = 2.0, wall_time: float | None = None,
        memory_mb: int = 256, fsize_mb: int = 4, request_timeout: float | None = None) -> dict:
    body = json.dumps({
        "source": source,
        "language": language,
        "stdin": stdin,
        "time": float(time_limit),
        "wallTime": float(wall_time if wall_time is not None else max(time_limit * 2 + 2, 5)),
        "memoryMb": int(memory_mb),
        "fsizeMb": int(fsize_mb),
    }).encode("utf-8")
    request = urllib.request.Request(
        _base() + "/isolate/run", data=body,
        headers={"Content-Type": "application/json", **_headers()}, method="POST",
    )
    try:
        timeout = request_timeout if request_timeout is not None else float(wall_time or 20) + 30
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"Isolate HTTP {exc.code}: {detail[:2000]}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Isolate request failed: {exc}") from exc
    payload["verificationAuthority"] = False
    payload["source"] = "isolate"
    return payload


def run_file(slug: str, path: str, stdin: str = "", **kwargs) -> dict:
    content = workspace.read_text(slug, path).get("content") or ""
    language = path.rsplit(".", 1)[-1] if "." in path else "cpp"
    result = run(content, language, stdin, **kwargs)
    result["path"] = path
    return result
