"""Compose the authoring prompt from durable files and the skill index."""
from __future__ import annotations

from pathlib import Path

import skill_registry

ROOT = Path(__file__).resolve().parent / "prompts"
MODES = ("author", "debug", "review")


def _read(relative: str) -> str:
    try:
        return (ROOT / relative).read_text("utf-8").strip()
    except OSError:
        return ""


def compose_system() -> str:
    parts = [
        _read("base.md"),
        _read("workflow.md"),
        _read("tools.md"),
        skill_registry.index_text(),
    ]
    text = "\n\n".join(part for part in parts if part)
    if text:
        return text
    # Emergency fallback for a partially installed tree.
    import agent

    return agent.SYSTEM


def mode_text(mode: str) -> str:
    mode = str(mode or "author").lower()
    if mode not in MODES:
        mode = "author"
    text = _read(f"modes/{mode}.md")
    if text:
        return text
    return f"# Mode: {mode}\nProceed carefully and use the verifier as truth."
