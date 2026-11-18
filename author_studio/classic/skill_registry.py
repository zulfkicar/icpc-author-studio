"""Progressive-disclosure skill registry.

Only the index is injected by default. Full instructions are loaded on demand by
`load_skill` and pinned into context until unloaded. Skills cannot grant tools or
permissions; they are instructions only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from author_studio.config import ROOT as PROJECT_ROOT

ROOT = PROJECT_ROOT / "skills"
MAX_ACTIVE = 2
MAX_PINNED_CHARS = 16000
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    when_to_use: str
    version: str
    body: str


def _parse(path: Path) -> Skill | None:
    try:
        text = path.read_text("utf-8")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) != 3:
        return None
    meta = {}
    for line in parts[1].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"').strip("'")
    name = meta.get("name", "").strip()
    if not NAME_RE.fullmatch(name):
        return None
    body = parts[2].strip()
    if not body:
        return None
    return Skill(
        name=name,
        description=meta.get("description", ""),
        when_to_use=meta.get("when_to_use", ""),
        version=meta.get("version", "1"),
        body=body,
    )


def all_skills() -> list[Skill]:
    if not ROOT.is_dir():
        return []
    skills = []
    for path in sorted(ROOT.glob("*/SKILL.md")):
        skill = _parse(path)
        if skill is not None:
            skills.append(skill)
    return sorted(skills, key=lambda item: item.name)


def get(name: str) -> Skill | None:
    name = str(name or "").strip()
    if not NAME_RE.fullmatch(name):
        return None
    path = ROOT / name / "SKILL.md"
    return _parse(path) if path.is_file() else None


def index_text() -> str:
    skills = all_skills()
    if not skills:
        return "No skills are available."
    lines = ["AVAILABLE SKILLS (load with load_skill; do not load everything):"]
    for skill in skills:
        lines.append(f"- {skill.name}: {skill.description}")
    return "\n".join(lines)


def activate(active: list[str] | None, name: str) -> tuple[list[str], Skill]:
    skill = get(name)
    if skill is None:
        raise ValueError(f"Unknown skill: {name}")
    current = [item for item in (active or []) if get(item) is not None]
    if skill.name in current:
        return current, skill
    if len(current) >= MAX_ACTIVE:
        raise ValueError(f"At most {MAX_ACTIVE} skills can be active; unload one first")
    return current + [skill.name], skill


def deactivate(active: list[str] | None, name: str) -> list[str]:
    return [item for item in (active or []) if item != name]


def pinned_text(active: list[str] | None) -> str:
    blocks = []
    used = 0
    for name in active or []:
        skill = get(name)
        if skill is None:
            continue
        block = f"\n--- ACTIVE SKILL: {skill.name} (v{skill.version}) ---\n{skill.body}"
        if used + len(block) > MAX_PINNED_CHARS:
            blocks.append("\n[additional active skill instructions truncated]")
            break
        blocks.append(block)
        used += len(block)
    return "\n".join(blocks)
