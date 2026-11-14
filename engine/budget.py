"""One budget per admitted action; at most three total model attempts.

The gateway owns retries.  The adapter performs a single request and never
retries internally, so transport retries and schema repairs consume the same
finite attempt ceiling (03 §6, CR05).
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Any, Callable

from .clock import Clock
from .model import PROVIDER_ERRORS
from .store import ApplicationStore
from .request_meter import measure


class BudgetExhausted(RuntimeError):
    def __init__(self, message: str, *, reason: str = "attempts"):
        super().__init__(message)
        self.reason = reason


@dataclass
class ModelOutcome:
    ok: bool
    data: Any = None
    attempts: int = 0
    usage: dict | None = None
    error_kind: str | None = None
    error: str | None = None
    attempt_id: str | None = None


class ModelGateway:
    """Executes a single model action under one reservation."""

    def __init__(
        self,
        store: ApplicationStore,
        adapter,
        clock: Clock | None = None,
        *,
        attempt_timeout_seconds: float = 90.0,
    ):
        self.store = store
        self.adapter = adapter
        self.clock = clock or store.clock
        self.attempt_timeout_seconds = attempt_timeout_seconds

    def _remaining(self, reservation_id: str) -> tuple[int, int]:
        resv = self.store.get_reservation(reservation_id)
        used = len(self.store.attempts_for(reservation_id))
        return max(0, int(resv["attempts_limit"]) - used), used

    def call(
        self,
        *,
        run_id: str,
        reservation_id: str,
        node: str,
        prompt: str,
        context: dict,
        validate: Callable[[Any], Any],
        schema_name: str = "PlanV1",
    ) -> ModelOutcome:
        remaining, used = self._remaining(reservation_id)
        if remaining <= 0:
            self.store.settle_reservation(reservation_id, "exhausted")
            raise BudgetExhausted("action model attempt ceiling exhausted", reason="attempts")
        budget = self.store.get_budget(run_id)
        if int(budget["model_attempts_used"]) >= int(budget["model_attempts_limit"]):
            self.store.settle_reservation(reservation_id, "exhausted")
            raise BudgetExhausted("run model attempt ceiling exhausted", reason="run_attempts")
        if float(budget["active_seconds_used"]) >= float(budget["active_seconds_limit"]):
            raise BudgetExhausted("run active-time ceiling exhausted", reason="active_time")

        attempts = 0
        last_error = "model call failed"
        last_kind = "transport"
        schema_note = ""
        while attempts < remaining:
            attempts += 1
            attempt = self.store.record_attempt(
                reservation_id, kind="model", outcome="in_flight",
                usage={"unknown": True}, attempt_index=used + attempts,
            )
            started = self.clock.monotonic()
            request = {
                "node": node, "run_id": run_id, "schema": schema_name,
                "schema_json": getattr(validate, "schema_json", None),
                "prompt": prompt if not schema_note else prompt + "\n\n" + schema_note,
                "context": context, "attempt": used + attempts,
                "max_attempts": int(self.store.get_reservation(reservation_id)["attempts_limit"]),
            }
            try:
                response = self.adapter.call(
                    request,
                    timeout_seconds=min(
                        self.attempt_timeout_seconds,
                        max(1.0, float(self.store.get_reservation(reservation_id)["wall_ms"] or 90000) / 1000.0),
                    ),
                )
            except Exception as exc:  # noqa: BLE001 - classify, never crash the graph here
                response = {"kind": "transport_error", "error": f"{type(exc).__name__}: {exc}"}
            elapsed = max(0.0, self.clock.monotonic() - started)
            self.store.add_active_seconds(run_id, elapsed)
            usage = dict(response.get("usage") or {"unknown": True})
            try:
                meter = measure(request, self.adapter, usage)
            except (TypeError, ValueError, AttributeError):
                meter = None
            kind = str(response.get("kind") or "malformed")
            if kind == "ok":
                try:
                    data = validate(response.get("data"))
                except Exception as exc:  # schema repair consumes the next attempt
                    last_error = f"schema invalid: {exc}"
                    last_kind = "schema"
                    schema_note = (
                        "Your previous response failed schema validation: "
                        f"{last_error}. Return only a valid JSON object."
                    )
                    self.store.finish_attempt(attempt["attemptId"], outcome="schema_error", usage=usage, meter=meter)
                    self.store.append_event(
                        run_id, "model_attempt", role="model",
                        payload={"node": node, "attempt": used + attempts, "outcome": "schema_error"},
                    )
                    continue
                self.store.finish_attempt(attempt["attemptId"], outcome="ok", usage=usage, meter=meter)
                self.store.append_event(
                    run_id, "model_attempt", role="model",
                    payload={"node": node, "attempt": used + attempts, "outcome": "ok"},
                )
                return ModelOutcome(ok=True, data=data, attempts=attempts, usage=usage,
                                    attempt_id=attempt["attemptId"])
            last_kind = kind
            last_error = str(response.get("error") or kind)
            self.store.finish_attempt(attempt["attemptId"], outcome=kind, usage=usage, meter=meter)
            self.store.append_event(
                run_id, "model_attempt", role="model",
                payload={"node": node, "attempt": used + attempts, "outcome": kind,
                         "error": last_error[:500]},
            )
            if kind == "refusal" or kind in PROVIDER_ERRORS:
                break
        self.store.settle_reservation(reservation_id, "exhausted")
        return ModelOutcome(
            ok=False, attempts=attempts, error_kind=last_kind, error=last_error,
            usage={"unknown": True}, attempt_id=attempt["attemptId"] if attempts else None,
        )


def parse_utc(value: str | None) -> _dt.datetime | None:
    if not value:
        return None
    try:
        parsed = _dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=_dt.timezone.utc)
