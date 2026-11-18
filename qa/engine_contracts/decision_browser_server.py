"""Offline decision-layer browser fixture server (test infrastructure only).

Usage: python qa/engine_contracts/decision_browser_server.py --port 8910 --mode hostile
       python ... --mode exhausted
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import tempfile
from http.server import HTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
from engine.decisions import AdapterResult, ScriptedDecisionAdapter  # noqa: E402
from engine.demo import ConversationDemoModel  # noqa: E402
from engine.service import EngineService  # noqa: E402
from engine.worker import FakeWorker  # noqa: E402
from qa.engine_contracts.harness import FIXTURES  # noqa: E402


class SwitchDecision:
    identity = "browser-test-decision"
    version = "1"

    def __init__(self, mode: str):
        self.mode = mode
        self.scripted = ScriptedDecisionAdapter()
        self.failed_once = False

    def call(self, text: str, context: dict, **_kwargs) -> AdapterResult:
        if self.mode == "fail-once" and text.strip() == "Apply your proposed fix." \
                and not self.failed_once:
            self.failed_once = True
            return AdapterResult("unavailable", error="controlled browser interpretation failure",
                                 model_identity=self.identity, model_version=self.version,
                                 usage={"unknown": True})
        if self.mode == "hostile" and text.strip() in (
                "Don't apply your proposed fix.",
                "Explain whether we should apply your proposed fix."):
            return AdapterResult("ok", data={
                "acts": [{"kind": "effect_request", "polarity": "affirmative",
                          "text": "Apply the fix.", "span": [9000, 9014],
                          "target_refs": ["current_solution"], "confidence": 1.0}],
                "explanation": "controlled hostile browser decision",
            }, model_identity=self.identity, model_version=self.version,
                usage={"unknown": True})
        return self.scripted.call(text, context)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8910)
    parser.add_argument("--mode", choices=["hostile", "exhausted", "fail-once"], default="hostile")
    args = parser.parse_args()
    root = pathlib.Path(tempfile.mkdtemp(prefix="decision-browser-"))
    limits = {"model_attempts_limit": 2} if args.mode == "exhausted" else None
    service = EngineService(
        root, model_adapter=ConversationDemoModel(), worker=FakeWorker(),
        fixture_dir=str(FIXTURES), clone_models=False,
        decision_adapter=SwitchDecision(args.mode),
        default_budget_limits=limits,
    )
    server.ENGINE_SERVICE = service
    server.CHAT_SERVICE = None

    class TestHandler(server.Handler):
        def do_POST(self):
            if self.path == "/test/exhaust":
                body = self.read_json()
                run_id = str(body.get("runId") or "")
                store = service.store(run_id)
                used = store.get_budget(run_id)["model_attempts_used"]
                with store.tx() as conn:
                    conn.execute("UPDATE budgets SET model_attempts_limit=? WHERE run_id=?",
                                 (used, run_id))
                self.send_json({"ok": True, "used": used})
                return
            super().do_POST()

    httpd = HTTPServer(("127.0.0.1", args.port), TestHandler)
    print(f"decision browser server on {args.port} mode={args.mode}", flush=True)
    try:
        httpd.serve_forever()
    finally:
        service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())