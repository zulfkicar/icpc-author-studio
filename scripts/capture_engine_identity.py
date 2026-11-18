"""Capture source/prompt/skill/dependency identities for V0-V3 evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.graph import build_collaboration, build_editing, build_investigation, build_review  # noqa: E402
from engine.prompts import bundle_hash, validate_bundle  # noqa: E402
from engine.procedures import manifest_hash  # noqa: E402
from engine.schemas import SCHEMA_VERSION  # noqa: E402
from engine.service import EngineService  # noqa: E402


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True,
                              timeout=20).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def versions() -> dict:
    try:
        from importlib.metadata import version

        return {name: version(name) for name in (
            "langchain", "langgraph", "langchain-openai", "langgraph-checkpoint-sqlite",
            "pydantic", "pytest", "pytest-asyncio",
        )}
    except Exception:  # noqa: BLE001
        return {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    engine_files = sorted((ROOT / "engine").rglob("*.py"))
    web_files = [ROOT / "web" / "engine.js", ROOT / "web" / "collab.css"]
    fixture_files = sorted((ROOT / "qa" / "engine_contracts" / "fixtures").rglob("*"))
    payload = {
        "capturedAt": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(),
        "schemaVersion": SCHEMA_VERSION,
        "engineSource": {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p)
                         for p in engine_files},
        "uiSource": {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p)
                     for p in web_files if p.is_file()},
        "fixtures": {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p)
                     for p in fixture_files if p.is_file()},
        "promptBundle": validate_bundle(),
        "promptBundleHash": bundle_hash(),
        "skillManifestHash": manifest_hash(),
        "dependencies": versions(),
        "gitHead": git("rev-parse", "HEAD"),
        "historicalBaselineHead": "9074dc3",
        "gitStatusPorcelain": git("status", "--porcelain").splitlines(),
        "note": (
            "Historical research inventories/results are not rewritten; their old hashes are "
            "baselines, not expectations for engine source. This snapshot records the implemented "
            "engine, UI, fixtures and dependency identities for the V0-V3 run."
        ),
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        for key in ("schemaVersion", "promptBundleHash", "skillManifestHash", "gitHead"):
            print(f"{key}: {payload[key]}")
        print(f"engine files: {len(payload['engineSource'])}, fixtures: {len(payload['fixtures'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
