"""Offline regressions for the production-compatible provider adapter."""
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest
from openai import AuthenticationError, RateLimitError

from author_studio import server
from engine.chat import ChatService
from engine.demo import FRAME_QUESTION
from engine.model import FakeModelAdapter, SingleRequestOpenAIAdapter
from engine.service import EngineService
from engine.worker import FakeWorker


def adapter():
    return SingleRequestOpenAIAdapter(
        model="example-model", api_key="test-placeholder-key",
        base_url="https://example.invalid/v1", max_output_tokens=2048,
    )


def test_live_adapter_honors_deadline_and_accepts_fenced_json():
    live = adapter()
    assert live._model.max_tokens == 2048

    def invoke(messages, *, timeout):
        assert timeout == 12
        assert messages[0][1].startswith("Return JSON\n")
        assert '"answer":{"type":"integer"}' in messages[0][1]
        return SimpleNamespace(content="```json\n{\"answer\": 4}\n```",
                               usage_metadata={"input_tokens": 20, "output_tokens": 9, "total_tokens": 29})

    live._model = SimpleNamespace(invoke=invoke)
    result = live.call({"prompt": "Return JSON", "context": {}, "schema_json": {
        "type": "object", "properties": {"answer": {"type": "integer"}},
    }}, timeout_seconds=12)
    assert result == {"kind": "ok", "data": {"answer": 4},
                      "usage": {"input_tokens": 20, "output_tokens": 9, "total_tokens": 29}}


def test_insufficient_credits_stops_initial_chat_without_a_second_request(tmp_path):
    live = adapter()
    calls = []

    def invoke(messages, *, timeout):
        calls.append(timeout)
        response = httpx.Response(429, request=httpx.Request("POST", "https://example.invalid/v1/chat/completions"))
        raise RateLimitError(
            "insufficient_credits: raw provider message test-placeholder-key",
            response=response, body={"code": "insufficient_credits"},
        )

    live._model = SimpleNamespace(invoke=invoke)
    service = EngineService(tmp_path, model_adapter=live, clone_models=False, worker=FakeWorker())
    try:
        chat = ChatService(service)
        result = chat.start("Develop a weighted booking problem with interval rewards.")
        assert result["view"]["status"] == "blocked"
        assert result["view"]["stopReason"] == "provider_quota"
        assert result["view"]["pendingDecision"] is None
        assert result["view"]["artifacts"] == []
        assert "no available credits" in result["messages"][-1]["text"]
        assert "test-placeholder-key" not in repr(result)
        chat.message(result["runId"], "Try again")
        assert len(calls) == 1
    finally:
        service.close()


@pytest.mark.parametrize(("demo", "override", "configured", "scripted"), [
    (False, None, True, False),
    (True, None, False, True),
    (False, "0", False, False),
])
def test_saved_live_preference_and_explicit_launch_modes(tmp_path, monkeypatch, demo, override, configured, scripted):
    monkeypatch.setattr(server, "ENGINE_SERVICE", None)
    monkeypatch.setattr(server.config, "load", lambda: {
        "engineLiveModel": True, "apiKey": "test-placeholder-key",
        "baseUrl": "https://example.invalid/v1", "model": "example-model",
    })
    monkeypatch.setattr(server.isolate_client, "configured", lambda: False)
    monkeypatch.setenv("AUTHOR_AGENT_ENGINE_ROOT", str(tmp_path))
    monkeypatch.setenv("AUTHOR_AGENT_ENGINE_DEMO", "1" if demo else "0")
    monkeypatch.delenv("AUTHOR_AGENT_ENGINE_LIVE_MODEL", raising=False)
    if override is not None:
        monkeypatch.setenv("AUTHOR_AGENT_ENGINE_LIVE_MODEL", override)
    service = server.engine_service()
    try:
        capabilities = service.capabilities()
        assert capabilities["modelConfigured"] is configured
        assert capabilities["demoMode"] is scripted
        if configured and not scripted:
            assert capabilities["model"]["model"] == "example-model"
    finally:
        service.close()


def test_opencode_provider_is_bound_to_the_conversation_and_uses_a_session(tmp_path):
    model = SingleRequestOpenAIAdapter(
        model="glm-5.3-flash", api_key="test-opencode-key",
        base_url="https://opencode.ai/inference/go/openai/v1",
        max_output_tokens=2048, opencode=True,
    )
    assert model._model.default_headers["User-Agent"] == "author-studio/0.1"
    calls = []

    def invoke(messages, *, timeout, extra_headers):
        calls.append(extra_headers["x-opencode-session"])
        response = httpx.Response(401, request=httpx.Request("POST", "https://example.invalid"))
        raise AuthenticationError("rejected test-opencode-key", response=response, body={})

    model._model = SimpleNamespace(invoke=invoke)
    service = EngineService(tmp_path, model_adapter=adapter(), provider_models={"opencode-go": model})
    try:
        chat = ChatService(service)
        with pytest.raises(ValueError, match="unavailable"):
            chat.start("Weighted bookings", model_provider="unknown-provider")
        result = chat.start("Weighted bookings with integer interval rewards.", model_provider="opencode-go")
        run_id = result["runId"]
        assert calls == [run_id]
        assert result["view"]["capabilities"]["provider"] == "opencode-go"
        assert result["view"]["stopReason"] == "provider_auth"
        assert "test-opencode-key" not in repr(result)
    finally:
        service.close()

    # Removing the profile cannot redirect previously bound chats to another endpoint.
    reopened = EngineService(tmp_path, model_adapter=adapter())
    try:
        assert reopened.capabilities()["modelConfigured"] is True
        caps = reopened.capabilities(run_id)
        assert caps["provider"] == "opencode-go"
        assert caps["modelConfigured"] is False
    finally:
        reopened.close()


def test_openrouter_profile_uses_its_own_key_and_fixed_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ENGINE_SERVICE", None)
    monkeypatch.setattr(server.isolate_client, "configured", lambda: False)
    monkeypatch.setenv("AUTHOR_AGENT_ENGINE_ROOT", str(tmp_path))
    monkeypatch.setenv("AUTHOR_AGENT_ENGINE_LIVE_MODEL", "1")
    cfg = {**server.config.DEFAULTS, "apiKey": "original-placeholder",
           "openrouterApiKey": "router-placeholder"}
    monkeypatch.setattr(server.config, "load", lambda: cfg)
    service = server.engine_service()
    try:
        assert service.capabilities()["providers"] == [
            {"id": "openrouter", "model": server.config.OPENROUTER_DEFAULT_MODEL},
        ]
        router = service.provider_models["openrouter"]._model
        assert router.model_kwargs["response_format"] == {"type": "json_object"}
        assert router.extra_body == {"reasoning": {"enabled": False}}
        assert router.openai_api_base == "https://openrouter.ai/api/v1"
        assert router.openai_api_key.get_secret_value() == cfg["openrouterApiKey"]
        assert service.model_factory._model.openai_api_key.get_secret_value() == cfg["apiKey"]
        public = server.config.public(cfg)
        assert public["hasOpenRouterKey"] and "openrouterApiKey" not in public
    finally:
        service.close()


def test_frame_normalizes_live_half_open_id_without_losing_its_explanation(tmp_path):
    frame = deepcopy(FRAME_QUESTION)
    question = frame["data"]["open_questions"][0]
    option = question["options"][0]
    option["id"] = "half-open"
    option["consequence"] = "Touching bookings can both run."
    question["recommendation"] = "half-open"
    service = EngineService(tmp_path, demo=True, worker=FakeWorker(),
                            model_adapter=FakeModelAdapter(script={"frame_goal": [frame]}))
    try:
        result = ChatService(service).start("Develop weighted bookings with integer rewards.")
        store = service.store(result["runId"])
        pending = store.pending_interaction(result["runId"])
        assert pending["option_ids"] == ["half_open", "closed"]
        assert pending["options"][0]["consequence"] == "Touching bookings can both run."
        assert pending["recommendation"] == "half_open"
    finally:
        service.close()
