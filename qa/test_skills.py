"""Skill registry and prompt assembly tests."""
from __future__ import annotations
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import prompt_loader
import skill_registry


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS {name}")
        return
    print(f"  FAIL {name} {detail}")
    raise AssertionError(name)


def main() -> int:
    skills = skill_registry.all_skills()
    names = {item.name for item in skills}
    expected = {
        "constraints", "domain-taxonomy", "difficulty-calibration", "test-coverage",
        "test-design", "negative-solutions", "validator-design", "checker-design",
        "interactive-design", "statement-quality", "performance-limits",
        "verifier-audit", "delivery",
    }
    check("all curated skills present", expected <= names, names)
    check("index contains skill index", "AVAILABLE SKILLS" in skill_registry.index_text())
    active, skill = skill_registry.activate([], "checker-design")
    check("load skill", active == ["checker-design"] and "Checker design" in skill.body)
    check("pinned skill", "ACTIVE SKILL: checker-design" in skill_registry.pinned_text(active))
    active, _ = skill_registry.activate(active, "interactive-design")
    try:
        skill_registry.activate(active, "test-coverage")
    except ValueError:
        check("max two active skills", True)
    else:
        check("max two active skills", False)
    check("unload skill", skill_registry.deactivate(active, "checker-design") == ["interactive-design"])
    system = prompt_loader.compose_system()
    check("system includes index", "AVAILABLE SKILLS" in system, system[:200])
    check("system does not dump skill body", "Self-test: reference accepted" not in system)
    print("SKILL TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
