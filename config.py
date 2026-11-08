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
    "reviewWrites": False,
    "summaryTriggerTokens": 30000,
    "summaryKeepMessages": 12,
    "inputPricePerMillion": 0.0,
    "outputPricePerMillion": 0.0,
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
    api_key = os.environ.get("AUTHOR_AGENT_API_KEY")
    base_url = os.environ.get("AUTHOR_AGENT_BASE_URL")
    model = os.environ.get("AUTHOR_AGENT_MODEL")
    if api_key:
        data["apiKey"] = api_key
    if base_url:
        data["baseUrl"] = base_url
    if model:
        data["model"] = model
    max_rounds = os.environ.get("AUTHOR_AGENT_MAX_TOOL_ROUNDS")
    if max_rounds:
        try:
            data["maxToolRounds"] = max(1, min(64, int(max_rounds)))
        except ValueError:
            pass
    summary_trigger = os.environ.get("AUTHOR_AGENT_SUMMARY_TRIGGER_TOKENS")
    if summary_trigger:
        try:
            data["summaryTriggerTokens"] = max(50, int(summary_trigger))
        except ValueError:
            pass
    summary_keep = os.environ.get("AUTHOR_AGENT_SUMMARY_KEEP_MESSAGES")
    if summary_keep:
        try:
            data["summaryKeepMessages"] = max(1, int(summary_keep))
        except ValueError:
            pass
    return data


def save(update: dict) -> dict:
    with _LOCK:
        data = load()
        for key in ("baseUrl", "model", "apiKey", "temperature", "maxToolRounds", "reviewWrites", "summaryTriggerTokens", "summaryKeepMessages", "inputPricePerMillion", "outputPricePerMillion"):
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
        "reviewWrites": bool(data.get("reviewWrites", False)),
        "summaryTriggerTokens": int(data.get("summaryTriggerTokens", 30000)),
        "summaryKeepMessages": int(data.get("summaryKeepMessages", 12)),
        "inputPricePerMillion": float(data.get("inputPricePerMillion", 0.0)),
        "outputPricePerMillion": float(data.get("outputPricePerMillion", 0.0)),
    }
