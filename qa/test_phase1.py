"""Phase 1 regression tests: context budget, model settings, schemas."""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from langchain.agents.middleware import ModelRequest, ModelRetryMiddleware
from langchain_core.messages import HumanMessage

import agent
import config
import graph_agent
from agent_middleware import ContextBudgetMiddleware
import schemas


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS {name}")
        return True
    print(f"  FAIL {name} {detail}")
    raise AssertionError(name)


def main() -> int:
    cfg = config.load()
    check("500k context", cfg["contextBudgetTokens"] == 500000, cfg)
    check("500k summary", cfg["summaryTriggerTokens"] == 500000, cfg)
    check("24 keep", cfg["summaryKeepMessages"] == 24, cfg)
    check("393k output", cfg["maxOutputTokens"] == 393216, cfg)
    check("pricing", cfg["inputPricePerMillion"] == 0.375 and cfg["outputPricePerMillion"] == 1.5, cfg)
    check("key not public", "apiKey" not in config.public(cfg), config.public(cfg))

    model = graph_agent._model(cfg)
    check("model max tokens", model.max_tokens == 393216, model.max_tokens)
    check("model streaming usage", model.stream_usage is True, model.stream_usage)
    check("model timeout", model.request_timeout == 300.0, model.request_timeout)

    small = ModelRequest(model=object(), messages=[HumanMessage(content="hello")])
    middleware = ContextBudgetMiddleware(model_window_tokens=1_048_576, max_output_tokens=393_216)
    _, output = middleware._budget(small)
    check("small request gets full output", output == 393216, output)

    huge = ModelRequest(model=object(), messages=[HumanMessage(content="x" * 4_200_000)])
    _, output = middleware._budget(huge)
    check("huge request clamps output", 1024 <= output < 393216, output)

    event = schemas.Event("run", 1, "now", "verify", "verify_package", status="passed", summary="ok")
    check("event schema", schemas.validate_event_dict(event.to_dict()), event.to_dict())
    question = schemas.ClarificationQuestion("q1", "Which output format?", why="checker", options=["tokens", "lines"], recommended="tokens")
    request = schemas.ClarificationRequest("c1", "chat", [question])
    check("clarification schema", request.to_dict()["questions"][0]["id"] == "q1", request.to_dict())
    try:
        schemas.ClarificationRequest("c2", "chat", [question, question])
    except ValueError:
        check("duplicate clarification rejected", True)
    else:
        check("duplicate clarification rejected", False)

    fallback_cfg = {**cfg, "fallbackModel": "fallback-model", "fallbackApiKey": "test", "fallbackBaseUrl": "https://example.invalid/v1"}
    fallbacks = graph_agent._fallback_models(fallback_cfg)
    check("fallback model constructed", len(fallbacks) == 1 and fallbacks[0].model_name == "fallback-model", fallbacks)
    check("no fallback by default", graph_agent._fallback_models({**cfg, "fallbackModel": ""}) == [])
    check("system treats output as untrusted", "untrusted data" in agent.SYSTEM, agent.SYSTEM[:200])
    key = cfg.get("apiKey") or "xpl_1234567890abcdef"
    redacted = config.redact(f"prefix {key} suffix xpl_abcdef1234567890")
    check("secret redaction", key not in redacted and "xpl_abcdef" not in redacted, redacted)
    try:
        graph_agent._model({**cfg, "apiKey": ""})
    except RuntimeError:
        check("missing key fails clearly", True)
    else:
        check("missing key fails clearly", False)

    attempts = {"n": 0}
    def flaky(_request):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("rate limited")
        return "ok"
    retry = ModelRetryMiddleware(max_retries=1, initial_delay=0.0, retry_on=(RuntimeError,))
    check("model retry", retry.wrap_model_call(object(), flaky) == "ok" and attempts["n"] == 2, attempts)

    print("PHASE 1 TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
