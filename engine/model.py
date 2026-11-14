"""Model adapter seam.

V3 ships a deterministic scripted adapter for contract tests and a single
request OpenAI-compatible adapter that can be qualified later.  Scripted
responses validate mechanics, not autonomous judgment.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from .schemas import canonical_json
from .request_meter import wire_messages

FakeResponse = dict[str, Any]
PROVIDER_QUOTA = "provider_quota"
PROVIDER_QUOTA_MESSAGE = "The saved provider has no available credits. Restore provider access before retrying live chat."
PROVIDER_AUTH = "provider_auth"
PROVIDER_ERRORS = {
    PROVIDER_QUOTA: PROVIDER_QUOTA_MESSAGE,
    PROVIDER_AUTH: "The provider rejected the saved API key. Update it in Provider settings and restart Author Studio.",
}


class ModelScriptExhausted(RuntimeError):
    """A scripted test asked for a model call the script does not define."""


class FakeModelAdapter:
    """Deterministic scripted model.

    ``script`` is either a list of responses consumed in order, or a mapping of
    node name to a list.  A response is ``{"kind": "ok", "data": {...}}`` or one
    of ``transport_error``/``malformed``/``refusal``.  Every consumed response
    is recorded for assertions; no response is invented.
    """

    name = "fake-model-v1"
    version = "1.0"
    configured = False
    demo = True

    def __init__(self, script: list[FakeResponse] | dict[str, list[FakeResponse]] | None = None,
                 default: FakeResponse | None = None):
        self._script = {k: list(v) for k, v in script.items()} if isinstance(script, dict) else None
        self._queue = list(script) if isinstance(script, list) else []
        self._default = default
        self.calls: list[dict] = []

    def describe_capabilities(self) -> dict:
        return {
            "model": self.name,
            "tools": False,
            "structured_output": True,
            "streaming": False,
            "usage": False,
            "cancellation": True,
        }

    def call(self, request: dict, *, timeout_seconds: float = 90.0) -> dict:
        self.calls.append({
            "node": request.get("node"), "attempt": request.get("attempt"),
            "schema": request.get("schema"), "context": request.get("context"),
        })
        node = str(request.get("node") or "")
        if self._script is not None:
            queue = self._script.get(node)
            if not queue:
                if self._default is not None:
                    return dict(self._default)
                raise ModelScriptExhausted(f"no scripted response for node {node!r}")
            response = queue.pop(0)
        elif self._queue:
            response = self._queue.pop(0)
        elif self._default is not None:
            response = self._default
        else:
            raise ModelScriptExhausted("scripted model has no responses left")
        return dict(response)

    def close(self) -> None:
        return None

    def clone(self) -> "FakeModelAdapter":
        """Fresh deterministic script for a new run (queues are per run)."""
        clone = FakeModelAdapter(default=self._default)
        if self._script is not None:
            clone._script = {key: list(value) for key, value in self._script.items()}
        else:
            clone._queue = list(self._queue)
        return clone


class SingleRequestOpenAIAdapter:
    """One outbound request per call; the gateway owns retries.

    Not exercised by the deterministic suite.  A live trial requires explicit
    user authorization, an API key and a selected endpoint (03 §7).
    """

    name = "openai-single-request-v1"
    version = "0.1"
    configured = True
    demo = False

    def __init__(self, *, model: str, api_key: str, base_url: str | None = None,
                 temperature: float = 0.0, max_output_tokens: int | None = None,
                 opencode: bool = False, openrouter_flash: bool = False, context_window: int | None = None):
        from langchain_openai import ChatOpenAI

        self._model_name = model
        self._opencode = opencode
        self._context_window = context_window if type(context_window) is int and context_window > 0 else None
        self._model = ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=base_url or None,
            temperature=temperature,
            max_retries=0,
            timeout=90,
            max_completion_tokens=max_output_tokens,
            default_headers={"User-Agent": "author-studio/0.1"} if opencode else None,
            model_kwargs={"response_format": {"type": "json_object"}} if openrouter_flash else {},
            extra_body={"reasoning": {"enabled": False}} if openrouter_flash else None,
        )

    def describe_capabilities(self) -> dict:
        return {
            "model": self._model_name,
            "tools": False,
            "structured_output": "json_object-prompt",
            "streaming": False,
            "usage": "provider-reported",
            "cancellation": "transport-close",
            "contextWindow": self._context_window,
            "contextWindowSource": "Configured for this model" if self._context_window else None,
        }

    def call(self, request: dict, *, timeout_seconds: float = 90.0) -> dict:
        messages = wire_messages(request)
        from openai import APIConnectionError, APIStatusError

        options = {}
        if self._opencode:
            session = (request.get("context") or {}).get("runId") or request.get("run_id")
            if not isinstance(session, str) or not re.fullmatch(r"run-[a-zA-Z0-9_-]+", session):
                return {"kind": PROVIDER_AUTH, "error": "OpenCode requires a valid Author Studio conversation ID."}
            options["extra_headers"] = {"x-opencode-session": session}
        try:
            response = self._model.invoke(messages, timeout=min(90.0, max(1.0, timeout_seconds)), **options)
        except APIStatusError as exc:
            if exc.status_code == 401:
                return {"kind": PROVIDER_AUTH, "error": PROVIDER_ERRORS[PROVIDER_AUTH]}
            code = str(exc.code or "").lower()
            if exc.status_code in (402, 429) and (
                exc.status_code == 402
                or code in ("insufficient_quota", "insufficient_credits")
                or re.search(r"\binsufficient_(?:quota|credits)\b", str(exc), re.IGNORECASE)
            ):
                return {"kind": PROVIDER_QUOTA, "error": PROVIDER_QUOTA_MESSAGE}
            return {"kind": "transport_error", "error": f"The saved provider returned HTTP {exc.status_code}."}
        except APIConnectionError:
            return {"kind": "transport_error", "error": "The server could not reach the saved provider within the request limit."}
        usage = {}
        meta = getattr(response, "usage_metadata", None)
        if isinstance(meta, dict):
            usage = {
                "input_tokens": meta.get("input_tokens"),
                "output_tokens": meta.get("output_tokens"),
                "total_tokens": meta.get("total_tokens"),
            }
        else:
            usage = {"unknown": True}
        text = response.content if isinstance(response.content, str) else canonical_json(response.content)
        fenced = re.fullmatch(r"\s*```(?:json)?\s*(.*?)\s*```\s*", text, re.IGNORECASE | re.DOTALL)
        if fenced:
            text = fenced.group(1)
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return {"kind": "malformed", "raw": text[:4000], "error": "response was not JSON", "usage": usage}
        return {"kind": "ok", "data": data, "usage": usage}

    def close(self) -> None:
        return None


class UnavailableModelAdapter:
    """Production default when no model is configured.

    Chat must explain this state instead of silently treating arbitrary author
    messages as the scripted demo.
    """

    name = "unconfigured-model"
    version = "0.1"
    configured = False
    demo = False

    def describe_capabilities(self) -> dict:
        return {"model": self.name, "configured": False, "tools": False,
                "structured_output": False, "streaming": False,
                "usage": False, "cancellation": False}

    def call(self, request: dict, *, timeout_seconds: float = 90.0) -> dict:
        return {"kind": "transport_error",
                "error": "No model is configured. Open Settings and configure a "
                         "supported model adapter, or explicitly enable demo mode."}

    def close(self) -> None:
        return None


def validate_with(schema: Any) -> Callable[[Any], Any]:
    """Return a validator that raises on schema violations."""
    if hasattr(schema, "model_validate"):
        def validate(value: Any) -> Any:
            return schema.model_validate(value)

        validate.schema_json = schema.model_json_schema()
        return validate
    if callable(schema):
        return schema
    raise TypeError("A Pydantic model or callable validator is required")
