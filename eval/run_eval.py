"""Small real-provider evaluation harness.

Usage:
    python eval/run_eval.py --fixture sum
    python eval/run_eval.py --fixture claim --keep

It creates a workspace, runs one authoring turn with the configured provider,
runs the deterministic verifier, and writes a JSON result to eval/results/.
This uses the provider key from the app configuration and therefore costs real
provider usage. It is intentionally not run automatically in CI.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from author_studio.classic import graph_agent
from author_studio.judging import verify
from author_studio.packages import workspace

KICKOFF = (
    "Author this problem end-to-end from the idea in NOTES.md. State assumptions in "
    "NOTES.md, write the statement, validator, C++20 reference, samples, strong secret "
    "edge cases and negative solutions, build answers, measure limits, and iterate with "
    "verify_package until the package is verified. Do not export."
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--keep", action="store_true", help="Keep the generated workspace")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--max-rounds", type=int, default=24)
    parser.add_argument("--turns", type=int, default=3, help="Maximum repair turns after the first authoring turn")
    args = parser.parse_args()
    os.environ["AUTHOR_AGENT_MAX_TOOL_ROUNDS"] = str(args.max_rounds)

    fixture_path = ROOT / "eval" / "fixtures" / (args.fixture + ".json")
    fixture = json.loads(fixture_path.read_text("utf-8"))
    created = workspace.create(
        fixture.get("name") or args.fixture,
        fixture.get("idea") or "",
        {
            "author": fixture.get("author") or "Eval",
            "shortName": fixture.get("shortName") or "E",
        },
    )
    slug = created["slug"]
    chat_id = workspace.ensure_chats(slug)["activeChat"]
    result_dir = ROOT / "eval" / "results"
    result_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    events = []
    paused_count = 0
    keep = args.keep
    try:
        aggregate_rounds = 0
        aggregate_usage = {}
        turn_errors = []
        turns_used = 0
        blocked = []
        report = {"status": "none"}
        result = {}
        message = KICKOFF
        for turn in range(1, args.turns + 1):
            turns_used = turn
            try:
                result = graph_agent.run_turn(
                    slug, chat_id, message,
                    lambda kind, data: events.append({"kind": kind, "data": data}),
                )
                # Reject any export approval; the eval measures verification, not publishing.
                while result.get("paused") and paused_count < 3:
                    paused_count += 1
                    interrupts = result.get("interrupts") or []
                    batched = any(isinstance(item.get("value"), dict) and "action_requests" in item["value"] for item in interrupts)
                    decisions = (
                        {"decisions": [{"type": "reject"} for _ in sum((item["value"].get("action_requests") or [] for item in interrupts), [])]}
                        if batched else
                        {item["id"]: {"type": "reject"} for item in interrupts}
                    )
                    result = graph_agent.resume_turn(slug, chat_id, decisions, lambda kind, data: events.append({"kind": kind, "data": data}))
                aggregate_rounds += result.get("rounds") or 0
                for key, value in (result.get("usage") or {}).items():
                    if isinstance(value, (int, float)):
                        if key == "costUsd":
                            aggregate_usage[key] = round(aggregate_usage.get(key, 0.0) + float(value), 6)
                        else:
                            aggregate_usage[key] = aggregate_usage.get(key, 0) + int(value)
            except Exception as exc:
                turn_errors.append({"turn": turn, "error": f"{type(exc).__name__}: {exc}"})
                result = {}
            report = verify.verify(slug)
            if report.get("status") == "verified":
                break
            if time.time() - started > args.timeout:
                break
            issues = (report.get("errors") or []) + (report.get("warnings") or [])
            blocked = [str(item)[:500] for item in issues[:8]]
            message = (
                "The verifier is not green. Concrete issues:\n"
                + "\n".join(f"- {item}" for item in blocked)
                + "\nFix these directly. If a negative solution survives because it is actually correct "
                  "for the constraints, remove or replace it; do not weaken tests or constraints. "
                  "Run build_answers/measure_limits if needed, then verify_package."
            )
        wall = time.time() - started
        keep = keep or report.get("status") != "verified"
        payload = {
            "fixture": args.fixture,
            "slug": slug,
            "chatId": chat_id,
            "finishedAt": workspace.now(),
            "wallSeconds": round(wall, 2),
            "turnsUsed": turns_used,
            "turnErrors": turn_errors,
            "rounds": aggregate_rounds,
            "usage": aggregate_usage,
            "pausedCount": paused_count,
            "toolCalls": sum(1 for event in events if event["kind"] == "tool_call"),
            "toolResults": sum(1 for event in events if event["kind"] == "tool_result"),
            "text": result.get("text"),
            "reportStatus": report.get("status"),
            "reportErrors": report.get("errors"),
            "reportWarnings": report.get("warnings"),
            "blocked": blocked,
            "counts": report.get("counts"),
            "limits": report.get("limits"),
        }
        out = result_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{args.fixture}.json"
        out.write_text(json.dumps(payload, indent=2), "utf-8")
        print(json.dumps({k: payload[k] for k in ("fixture", "reportStatus", "turnsUsed", "rounds", "toolCalls", "usage", "wallSeconds", "turnErrors")}, indent=2))
        print("result:", out)
        return 0 if report.get("status") == "verified" else 1
    except Exception as exc:
        keep = True
        debug = result_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{args.fixture}-failed.json"
        debug.write_text(json.dumps({
            "fixture": args.fixture,
            "slug": slug,
            "chatId": chat_id,
            "error": f"{type(exc).__name__}: {exc}",
            "events": events,
        }, indent=2), "utf-8")
        print("failed; workspace kept at", workspace.ws_path(slug), "debug:", debug)
        raise
    finally:
        if not keep:
            shutil.rmtree(workspace.ws_path(slug), ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
