"""Local configuration for the author agent.

The API key is stored only in .author-agent/config.json on this machine. The
key is never returned to the browser; the UI only sees a masked hint.
"""
from __future__ import annotations

import json
import os
import pathlib
import threading

ROOT = pathlib.Path(__file__).resolve().parent
STATE_DIR = ROOT / ".author-agent"
CONFIG_PATH = STATE_DIR / "config.json"
WORKSPACES = ROOT / "workspaces"
TEMPLATES = ROOT / "templates"

DEFAULTS = {
    "baseUrl": "https://api.deepseek.com/v1",
    "model": "deepseek-chat",
    "apiKey": "",
    "temperature": 0.2,
    "maxToolRounds": 24,
}

_LOCK = threading.Lock()


def _ensure() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    WORKSPACES.mkdir(parents=True, exist_ok=True)


def load() -> dict:
    _ensure()
    data = dict(DEFAULTS)
    try:
        raw = json.loads(CONFIG_PATH.read_text("utf-8"))
        if isinstance(raw, dict):
            data.update(raw)
    except FileNotFoundError:
        pass
    except (ValueError, OSError):
        pass
    data["apiKey"] = os.environ.get("AUTHOR_AGENT_API_KEY", data.get("apiKey", ""))
    data["baseUrl"] = os.environ.get("AUTHOR_AGENT_BASE_URL", data.get("baseUrl", DEFAULTS["baseUrl"]))
    data["model"] = os.environ.get("AUTHOR_AGENT_MODEL", data.get("model", DEFAULTS["model"]))
    return data


def save(update: dict) -> dict:
    with _LOCK:
        data = load()
        for key in ("baseUrl", "model", "apiKey", "temperature", "maxToolRounds"):
            if key in update and update[key] is not None:
                data[key] = update[key]
        data["temperature"] = max(0.0, min(2.0, float(data.get("temperature", 0.2))))
        data["maxToolRounds"] = max(1, min(64, int(data.get("maxToolRounds", 24))))
        _ensure()
        CONFIG_PATH.write_text(json.dumps(data, indent=2), "utf-8")
        return data


def public(data: dict | None = None) -> dict:
    data = data or load()
    key = str(data.get("apiKey") or "")
    return {
        "baseUrl": data.get("baseUrl", ""),
        "model": data.get("model", ""),
        "hasKey": bool(key),
        "keyHint": ("..." + key[-4:]) if len(key) >= 8 else ("" if not key else "set"),
        "temperature": data.get("temperature", 0.2),
        "maxToolRounds": data.get("maxToolRounds", 24),
    }
