"""Performance soak: repeated executor runs and agent turns with latency budgets."""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "qa"))

from author_studio.classic import graph_agent
from author_studio import winutil
from author_studio.packages import workspace
from stress_agent import FakeChat, use_model

RUNS = int(os.environ.get("SOAK_RUNS", "20"))
TURNS = int(os.environ.get("SOAK_TURNS", "8"))
RUN_P95_BUDGET_MS = float(os.environ.get("SOAK_RUN_P95_MS", "10000"))
TURN_P95_BUDGET_MS = float(os.environ.get("SOAK_TURN_P95_MS", "5000"))


def p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
    return ordered[index]


def main() -> int:
    created = workspace.create("QA Soak", "performance soak")
    slug = created["slug"]
    chat = workspace.ensure_chats(slug)["activeChat"]
    run_ms: list[float] = []
    turn_ms: list[float] = []
    try:
        workspace.write_text(slug, "hello.py", "print('soak-ok')\n", source="test")
        source = workspace.ws_path(slug) / "hello.py"
        for _ in range(RUNS):
            started = time.perf_counter()
            result = winutil.run_captured([sys.executable, str(source)], cwd=workspace.ws_path(slug), timeout=30)
            elapsed = (time.perf_counter() - started) * 1000
            assert result["ok"] and b"soak-ok" in result["stdout"], result
            run_ms.append(elapsed)
        use_model(FakeChat(auto_text="soak"))
        for index in range(TURNS):
            started = time.perf_counter()
            result = graph_agent.run_turn(slug, chat, f"soak {index}", lambda *_: None)
            elapsed = (time.perf_counter() - started) * 1000
            assert result.get("text") == "soak", result
            turn_ms.append(elapsed)
    finally:
        shutil.rmtree(workspace.ws_path(slug), ignore_errors=True)
    summary = {
        "runs": {
            "count": len(run_ms),
            "medianMs": round(statistics.median(run_ms), 1),
            "p95Ms": round(p95(run_ms), 1),
            "maxMs": round(max(run_ms), 1),
            "budgetMs": RUN_P95_BUDGET_MS,
        },
        "turns": {
            "count": len(turn_ms),
            "medianMs": round(statistics.median(turn_ms), 1),
            "p95Ms": round(p95(turn_ms), 1),
            "maxMs": round(max(turn_ms), 1),
            "budgetMs": TURN_P95_BUDGET_MS,
        },
    }
    print(json.dumps(summary, indent=2))
    assert summary["runs"]["p95Ms"] <= RUN_P95_BUDGET_MS, summary
    assert summary["turns"]["p95Ms"] <= TURN_P95_BUDGET_MS, summary
    out = ROOT / "qa" / "soak-results.json"
    out.write_text(json.dumps(summary, indent=2) + "\n", "utf-8")
    print("SOAK TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
