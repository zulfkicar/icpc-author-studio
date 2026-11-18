"""Conversation-first facade over the collaborative engine.

The author types ordinary language.  This service creates the internal run
automatically, translates the message into the existing typed ingress/response
contracts, pumps the single owner, and projects durable transcript messages and
internal artifacts back into the conversation.
"""
from __future__ import annotations

import json
import re
import threading
import uuid

from .model import PROVIDER_ERRORS
from .policy import LOCAL_ACTOR, PolicyDenied, validate_text
from problem_titles import validate_title
from .schemas import canonical_json, sha256_text
from .service import EngineService
from .store import IdempotencyConflict, LedgerError
from .studio_evidence import project_cards

_FAMILY = re.compile(
    r"\b(?:interval|intervals|booking|bookings|meeting|meetings|talk|talks|job|jobs|"
    r"activity|activities|schedule|scheduling|timeline|slot|slots|reservation|"
    r"reservations|reward|rewards|profit|weighted|weight|earliest finish|"
    r"compatible|half[- ]open|closed intervals|sequence dp|selecting|profitabl\w*)\b",
    re.I)
_CODE = re.compile(r"```(?:[A-Za-z0-9_+-]*)\n(.*?)```", re.S)
_CODE_HINT = re.compile(
    r"(?:#include\s*<|int\s+main\s*\(|using\s+namespace\s+std|std::|"
    r"def\s+\w+\s*\(|class\s+\w+|function\s+\w+\s*\(|vector\s*<)", re.I)
_LEMMA = re.compile(r"\b(?:lemma|proof|theorem|claim|corollary|proposition)\b", re.I)
_TEST = re.compile(r"\b(?:test|example|case|sample|try this)\b", re.I)
_APPLY = re.compile(
    r"\b(?:apply|implement|make)\b.{0,80}\b(?:fix|patch|change|proposal|repair)\b|"
    r"\b(?:apply|implement)\s+(?:it|that|this|the fix|your fix|your proposal)\b|"
    r"\b(?:go ahead|do it|make the change)\b", re.I)
_EXPLAIN = re.compile(r"\b(?:explain|why|what did|how did|clarify|understand)\b", re.I)
_REJECT = re.compile(r"^(?:no|reject|keep|leave|don't|do not|not that)\b", re.I)
_DEFER = re.compile(r"\b(?:defer|later|not now|wait|pause)\b", re.I)
_APPROVE = re.compile(r"^(?:yes|approve|authorize|authorise|go ahead|apply|do it|ok|okay)\b", re.I)
_HALF = re.compile(r"\b(?:half[- ]open|open|touch|touching|free|compatible)\b", re.I)
_CLOSED = re.compile(r"\b(?:closed|strict|inclusive|overlap)\b", re.I)
_BRIEF = re.compile(r"\b(?:brief|briefly|short|concise)\b", re.I)
_DETAILED = re.compile(r"\b(?:detailed|in depth|full detail|thorough)\b", re.I)
_DELEGATED = re.compile(r"\b(?:delegate|on your own|for you to|take it)\b", re.I)
_TOGETHER = re.compile(r"\b(?:together|work with me)\b", re.I)
_IDEA = re.compile(
    r"\b(?:i\s+(?:propose|suggest|think)|my\s+approach|approach\s+is|"
    r"i(?:'d|\s+would)\s+(?:use|try)|idea\s*:|alternative\s+approach)\b", re.I
)
_PATCH_PATH = re.compile(
    r"(?:\+\+\+\s*|\bpath\b\s*[:=]\s*|\bfile\b\s*[:=]\s*)"
    r"([A-Za-z0-9_./-]+\.(?:cpp|h|hpp|md|txt|py))"
)
_PATH_TAIL = re.compile(r"([A-Za-z0-9_./-]+\.(?:cpp|h|hpp|md|txt|py))")


def _max_compatible_reward(jobs: list[tuple[int, int, int]], *, half_open: bool) -> int:
    """Independent subset oracle for small parsed test tuples (no candidate code)."""
    ordered = sorted(jobs, key=lambda job: (job[1], job[0]))
    best = [0] * (len(ordered) + 1)
    for index, (start, finish, reward) in enumerate(ordered, start=1):
        predecessor = 0
        for previous in range(index - 1):
            other = ordered[previous]
            compatible = (other[1] <= start) if half_open else (other[1] < start)
            if compatible:
                predecessor = previous + 1
        best[index] = max(best[index - 1], best[predecessor] + reward)
    return best[-1]


class ChatService:
    def __init__(self, service: EngineService):
        self.service = service
        self._start_locks = [threading.Lock() for _ in range(32)]

    def _start_path(self, key: str):
        if not isinstance(key, str) or not key.strip() or len(key) > 200:
            raise ValueError("A request ID must contain between 1 and 200 characters.")
        return self.service.base_root / "chat-starts" / (sha256_text(key) + ".json")

    def receipt(self, key: str, run_id: str | None = None) -> dict:
        path = self._start_path(key)
        prefix = "message:"
        if not run_id:
            prefix = "start:"
            try:
                run_id = json.loads(path.read_text("utf-8"))["runId"]
            except FileNotFoundError:
                return {"accepted": False}
        if not re.fullmatch(r"run-[a-f0-9]{12}", run_id):
            raise ValueError("Invalid conversation identifier.")
        try:
            store = self.service.store(run_id)
        except LedgerError:
            return {"accepted": False}
        message = store.read_one(
            "SELECT id, seq, input_id, response_id FROM chat_messages WHERE run_id=? AND dedupe_key=?",
            (run_id, prefix + key),
        )
        if not message:
            return {"accepted": False}
        input_status = store.get_input(message["input_id"])["status"] if message["input_id"] else None
        response = store.get_response(message["response_id"]) if message["response_id"] else None
        return {"accepted": True, "runId": run_id, "messageId": message["id"],
                "seq": message["seq"], "inputId": message["input_id"], "status": input_status,
                "choiceApplied": bool(response and response["applied"])}

    # ---------------------------------------------------------------- session
    def start(self, message: str, *, client_request_id: str | None = None,
              model_provider: str = "custom", title: str | None = None) -> dict:
        text = str(message or "").strip()
        if not text:
            raise ValueError("Write an idea first")
        if client_request_id is None:
            return self._start(text, None, model_provider, title)
        validate_text(text, field="idea")
        if title is not None:
            title = validate_title(title)
        path = self._start_path(client_request_id)
        body_hash = sha256_text({"idea": text, "provider": model_provider, "title": title})
        with self._start_locks[int(path.stem[:2], 16) % len(self._start_locks)]:
            try:
                reservation = json.loads(path.read_text("utf-8"))
            except FileNotFoundError:
                reservation = {"runId": "run-" + uuid.uuid4().hex[:12], "bodyHash": body_hash}
                path.parent.mkdir(parents=True, exist_ok=True)
                pending = path.with_suffix(".tmp")
                pending.write_text(canonical_json(reservation), encoding="utf-8")
                pending.replace(path)
            if reservation["bodyHash"] != body_hash:
                raise IdempotencyConflict("clientRequestId was reused with a different idea, title or provider")
            run_id = reservation["runId"]
            if self.receipt(client_request_id)["accepted"]:
                return {**self._result(run_id), "unsupported": not bool(_FAMILY.search(text))}
            return self._start(text, client_request_id, model_provider, title, run_id)

    def _start(self, text, client_request_id, model_provider, title, reserved_run_id=None) -> dict:
        unsupported = not bool(_FAMILY.search(text))
        try:
            store = self.service.store(reserved_run_id) if reserved_run_id else None
            if store:
                store.get_run(reserved_run_id)
        except LedgerError:
            store = None
        if store:
            run_id = reserved_run_id
            existing = store.read_one("SELECT id FROM inputs WHERE run_id=? AND kind='new_goal' ORDER BY seq LIMIT 1",
                                      (run_id,))
            if not existing:
                receipt = store.append_input(run_id, kind="new_goal", text=text, expected_generation=0,
                                             client_request_id="initial-" + run_id)
                input_id = receipt["inputId"]
            else:
                input_id = existing["id"]
            if not store.read_one("SELECT id FROM grants WHERE run_id=? LIMIT 1", (run_id,)):
                store.create_grant(run_id, actor_id=LOCAL_ACTOR, source_input_id=input_id,
                                   operation_kinds=["read_artifact", "differential_search", "replay_diagnostic"],
                                   scope=["author-visible"], goal_generation=0)
        else:
            created = self.service.create_run(workspace_id="conversation", idea=text, model_provider=model_provider,
                                              title=title, reserved_run_id=reserved_run_id)
            run_id = created["runId"]
            input_id = (created.get("input") or {}).get("inputId")
        caps = self.service.capabilities(run_id)
        store = self.service.store(run_id)
        user = store.append_chat_message(
            run_id, role="author", kind="idea", text=text, input_id=input_id,
            dedupe_key="start" if client_request_id is None else f"start:{client_request_id}",
        )
        if unsupported:
            store.update_run(run_id, status="blocked", stop_reason="unsupported_profile")
            self._assistant(
                run_id, "boundary",
                "This profile currently supports weighted interval scheduling with exact integer "
                "output (bookings, talks, jobs or activities with start/finish times and rewards). "
                "I did not reinterpret your idea as that problem. If it fits this family, describe "
                "the intervals and reward rule; otherwise this task is outside the supported profile.",
                dedupe="unsupported",
            )
        elif not (caps.get("modelConfigured") or caps.get("demoMode")):
            store.update_run(run_id, status="blocked", stop_reason="model_unavailable")
            self._assistant(
                run_id, "boundary",
                "No model adapter is configured. I created a local conversation but cannot run the "
                "authoring graph. Configure a supported model in Settings, or explicitly enable the "
                "labelled demo model. No fake response was substituted.",
                dedupe="model-unavailable",
            )
        else:
            record = self.service.decisions(run_id).interpret(run_id, user["id"], text)
            if input_id:
                store.bind_decision_input(record["recordId"], input_id)
            if record["status"] in PROVIDER_ERRORS:
                reason = record["status"]
                store.update_run(run_id, status="blocked", stop_reason=reason)
                self._assistant(run_id, "boundary", PROVIDER_ERRORS[reason] + " Start a new problem after access is restored.",
                                dedupe=f"provider:{reason}")
            else:
                self._pump(run_id)
                self._sync(run_id)
        return {"runId": run_id, "messages": self.transcript(run_id)["messages"],
                "view": self.view(run_id), "unsupported": unsupported}

    def message(self, run_id: str, message: str, *,
                client_request_id: str | None = None,
                recover_input_id: str | None = None, expected_interaction_id: str | None = None) -> dict:
        text = str(message or "").strip()
        if not text:
            raise ValueError("Write a message first")
        store = self.service.store(run_id)
        run = store.get_run(run_id)
        if client_request_id:
            existing = store.read_one(
                "SELECT id, text FROM chat_messages WHERE run_id=? AND dedupe_key=?",
                (run_id, f"message:{client_request_id}"),
            )
            if existing is not None:
                if existing["text"] != text:
                    raise IdempotencyConflict(
                        "clientRequestId was reused with a different chat message body")
                return self._resume_turn(run_id, existing["id"], existing["text"])
        interaction = store.pending_interaction(run_id)
        if expected_interaction_id and (not interaction or interaction["id"] != expected_interaction_id):
            raise IdempotencyConflict("This choice has changed. Review the current question before answering.")
        recovery_id = self._recovery_target(run_id, text, recover_input_id)
        if recover_input_id and recovery_id is None:
            self._assistant(
                run_id, "clarify",
                "That recovery target is not an unresolved failed turn for this request. "
                "No barrier was cleared; use the Retry control on the failed turn or cancel.",
                dedupe=None,
            )
            return self._result(run_id)
        payload = {"messageId": "pending", "awaitingDecision": True}
        if expected_interaction_id:
            payload["expectedInteractionId"] = expected_interaction_id
        if recovery_id:
            payload["recoversInputId"] = recovery_id
        receipt_key = (f"chat-turn-{client_request_id}" if client_request_id
                       else f"chat-turn-{uuid.uuid4().hex}")
        created = store.append_chat_turn(
            run_id, role="author", text=text, payload=payload,
            client_request_id=receipt_key,
            dedupe_key=None if client_request_id is None else f"message:{client_request_id}",
        )
        user = created["message"]
        turn = created["input"]
        if user is None or turn is None:
            return self._result(run_id)
        if client_request_id and user["text"] != text:
            raise IdempotencyConflict(
                "clientRequestId was reused with a different chat message body")
        payload["messageId"] = user["id"]
        store.update_chat_links(user["id"], input_id=turn["inputId"] if "inputId" in turn else turn["id"])
        turn_id = turn["inputId"] if "inputId" in turn else turn["id"]
        if recovery_id:
            store.append_event(run_id, "failed_turn_recovery_started", role="author",
                               payload={"failedInputId": recovery_id,
                                        "recoveryInputId": turn_id})
        if run["status"] == "blocked" and run["stop_reason"] in PROVIDER_ERRORS:
            self._settle_turn(store, turn_id, "The initial provider request was rejected")
            return self._result(run_id)
        if run["status"] == "blocked" and run["stop_reason"] in (
                "unsupported_profile", "model_unavailable"):
            self._assistant(
                run_id, "boundary",
                "This conversation is outside the supported profile or has no configured model. "
                "Start a supported weighted-interval idea or configure a model adapter.",
                dedupe=f"blocked:{run['stop_reason']}",
            )
            return self._result(run_id)

        if not expected_interaction_id:
            interaction = store.pending_interaction(run_id)
        if self._decision_budget_exhausted(run_id):
            safe_acts = self._safe_control_acts(text)
        else:
            safe_acts = [a for a in self._safe_control_acts(text)
                         if a["kind"] == "cancel"]
        if safe_acts:
            interpretation = {"acts": safe_acts, "unresolved_reason": None,
                              "explanation": "Host-safe explicit control; no model call."}
            disposition = {"status": "admitted", "acts": safe_acts, "rejected": [],
                           "reason": None,
                           "contextRevision": run["observed_revision"],
                           "contextGeneration": run["goal_generation"]}
            record = store.add_decision_record(
                run_id, message_id=user["id"], text_hash=sha256_text(text),
                interpretation=interpretation, disposition=disposition,
                status="admitted", schema_version=1,
                prompt_version="host-safe-control",
                model_identity="host-safe-control", model_version="1",
                context_revision=run["observed_revision"],
                context_generation=run["goal_generation"],
                attempts=0, usage={"unknown": True},
            )
            record["recordId"] = record["id"]
            pump = self._apply_unprompted(run_id, record, safe_acts, user)
            self._settle_turn(store, turn_id, "host-safe control")
            if pump:
                self._pump(run_id)
            self._sync(run_id)
            return self._result(run_id)
        record = self.service.decisions(run_id).interpret(run_id, user["id"], text)
        acts = record["acts"]
        if record["status"] in self._FAILED_DECISION and not acts:
            self._recovery_card(run_id, turn_id, record["status"],
                                record.get("unresolvedReason"))
            self._sync(run_id)
            return self._result(run_id)
        if not acts:
            self._assistant(run_id, "clarify", self._clarify_text(record, interaction),
                            dedupe=None)
            if record["status"] in ("admitted", "unresolved"):
                self._settle_turn(store, turn_id, "safe no-effect disposition")
            self._sync(run_id)
            return self._result(run_id)
        if interaction is not None:
            pump = self._apply_pending(run_id, interaction, record, acts, user,
                                       client_request_id)
        else:
            pump = self._apply_unprompted(run_id, record, acts, user)
        if recovery_id and record["status"] == "admitted":
            self._settle_recovery(run_id, recovery_id, turn_id)
        if record["status"] in ("admitted", "unresolved"):
            self._settle_turn(store, turn_id, "decision applied or safely clarified")
        if pump:
            self._pump(run_id)
        self._sync(run_id)
        return self._result(run_id)

    @staticmethod
    def _settle_turn(store, turn_id: str, reason: str) -> None:
        try:
            item = store.get_input(turn_id)
        except LedgerError:
            return
        if item["status"] in ("received", "interpreting", "needs_disambiguation"):
            store.disposition_input(turn_id, "superseded", reason=reason)

    _FAILED_DECISION = ("unavailable", "malformed", "budget_exhausted", "unknown", "refusal", *PROVIDER_ERRORS)

    def _failed_turns(self, run_id: str, text: str) -> list[str]:
        store = self.service.store(run_id)
        found: list[str] = []
        for item in store.list_inputs(run_id):
            if item["kind"] != "chat_turn" or item["status"] not in (
                    "received", "interpreting", "needs_disambiguation"):
                continue
            message = store.read_one(
                "SELECT * FROM chat_messages WHERE run_id=? AND input_id=? ORDER BY seq DESC LIMIT 1",
                (run_id, item["id"]),
            )
            if message is None or str(message["text"]).strip() != text.strip():
                continue
            record = store.decision_for_message(run_id, message["id"])
            if record is not None and record["status"] in self._FAILED_DECISION:
                found.append(item["id"])
        return found

    def _recovery_target(self, run_id: str, text: str,
                         explicit: str | None) -> str | None:
        store = self.service.store(run_id)
        if explicit:
            try:
                item = store.get_input(explicit)
            except LedgerError:
                return None
            if item["kind"] != "chat_turn" or item["status"] not in (
                    "received", "interpreting", "needs_disambiguation"):
                return None
            message = store.read_one(
                "SELECT * FROM chat_messages WHERE run_id=? AND input_id=? "
                "ORDER BY seq DESC LIMIT 1", (run_id, explicit))
            record = (store.decision_for_message(run_id, message["id"])
                      if message is not None else None)
            if record is None or record["status"] not in self._FAILED_DECISION:
                return None
            return explicit
        candidates = self._failed_turns(run_id, text)
        return candidates[0] if len(candidates) == 1 else None

    def _settle_recovery(self, run_id: str, recovery_id: str | None,
                         turn_id: str) -> None:
        if not recovery_id:
            return
        store = self.service.store(run_id)
        try:
            old = store.get_input(recovery_id)
        except LedgerError:
            return
        if old["status"] in ("received", "interpreting", "needs_disambiguation"):
            store.disposition_input(recovery_id, "superseded",
                                    reason=f"resolved by {turn_id}")
            store.append_event(run_id, "failed_turn_resolved", role="host",
                               payload={"failedInputId": recovery_id,
                                        "recoveryInputId": turn_id})

    def _recovery_card(self, run_id: str, turn_id: str, status: str,
                       reason: str | None) -> None:
        self._assistant(
            run_id, "recovery",
            f"Interpretation failed for this turn ({status}). The original request is still "
            f"durable and fenced; no effect was applied. {reason or ''} "
            "Use Retry to interpret it again as an explicit recovery action, or cancel.",
            dedupe=f"recovery:{turn_id}", artifact_ids=[turn_id],
        )

    def _resume_turn(self, run_id: str, message_id: str, text: str) -> dict:
        """Resume an unfinished turn without spending a second model call."""
        store = self.service.store(run_id)
        user = store.get_chat_message(message_id)
        record = store.decision_for_message(run_id, message_id)
        turn_id = user.get("input_id")
        if not turn_id:
            receipt = self.service.runtime(run_id).inputs.submit_input(run_id, {
                "kind": "chat_turn", "text": text,
                "clientRequestId": f"chat-turn-{message_id}",
                "payload": {"messageId": message_id, "awaitingDecision": True},
            })
            turn_id = receipt["inputId"]
            store.update_chat_links(message_id, input_id=turn_id)
        if record is None:
            reservation = store.reservation_for_action(run_id, f"decision:{message_id}")
            if reservation is not None and store.attempts_for(reservation["id"]):
                self._assistant(
                    run_id, "notice",
                    "A previous interpretation attempt for this turn has no durable result; "
                    "I will not repeat a potentially paid call. Resubmit as a new turn.",
                    dedupe=f"unknown-turn:{message_id}",
                )
                self._sync(run_id)
                return self._result(run_id)
            record = self.service.decisions(run_id).interpret(run_id, message_id, text)
        if turn_id:
            item = store.get_input(turn_id)
            if item["status"] in ("applied", "superseded", "cancelled"):
                return self._result(run_id)
        acts = record["acts"]
        if not acts:
            if record["status"] in ("admitted", "unresolved") and turn_id:
                self._settle_turn(store, turn_id, "resumed no-effect disposition")
            self._sync(run_id)
            return self._result(run_id)
        interaction = store.pending_interaction(run_id)
        expected = ((store.get_input(turn_id).get("payload") or {}).get("expectedInteractionId")
                    if turn_id else None)
        if expected and (not interaction or interaction["id"] != expected):
            self._settle_turn(store, turn_id, "The card changed before its choice could be applied")
            return self._result(run_id)
        if interaction is not None:
            pump = self._apply_pending(run_id, interaction, record, acts, user, None)
        else:
            pump = self._apply_unprompted(run_id, record, acts, user)
        if record["status"] in ("admitted", "unresolved") and turn_id:
            self._settle_turn(store, turn_id, "resumed decision application")
        if pump:
            self._pump(run_id)
        self._sync(run_id)
        return self._result(run_id)

    # ------------------------------------------------------ decision routing
    def _apply_unprompted(self, run_id: str, record: dict, acts: list[dict],
                          user: dict) -> bool:
        store = self.service.store(run_id)
        kinds = [a["kind"] for a in acts]
        if "cancel" in kinds:
            self._linked_input(run_id, record, user, {"kind": "cancel", "text": user["text"]})
            return True
        restrictions = [a for a in acts if a["kind"] == "restriction"]
        effects = [a for a in acts if a["kind"] == "effect_request"]
        if restrictions and not effects:
            self._assistant(
                run_id, "notice",
                "I have not applied the proposed change. The restriction is recorded and "
                "any queued edit is fenced before publication.",
                dedupe=f"restricted:{record['recordId']}",
            )
            self._linked_input(run_id, record, user, {"kind": "steer", "text": user["text"]})
            return True
        contributed = 0
        for act in acts:
            if act["kind"] != "contribution":
                continue
            self._linked_contribution(run_id, record, user, act)
            contributed += 1
        for act in acts:
            if act["kind"] == "preference":
                try:
                    payload = json.loads(act.get("requested_work") or "{}")
                except json.JSONDecodeError:
                    payload = {}
                if payload:
                    self._linked_input(run_id, record, user, {
                        "kind": "set_engagement", "text": "",
                        "payload": {**payload, "preference_source": "author"},
                    })
            elif act["kind"] == "effect_request":
                target = act.get("resolvedTarget")
                if target is None:
                    self._assistant(run_id, "clarify", self._clarify_text(record, None),
                                    dedupe=None)
                    continue
                self._contextual_apply(run_id, record, user, target)
            elif act["kind"] == "semantic_assertion" and act.get("admission") == "commit":
                self._linked_input(run_id, record, user, {
                    "kind": "steer", "text": user["text"],
                })
            elif act["kind"] in ("information_request", "request_work"):
                if act["kind"] == "information_request":
                    self._explain_now(run_id, user["text"], user)
                self._linked_input(run_id, record, user, {
                    "kind": "steer", "text": user["text"],
                })
            elif act["kind"] in ("proof_explanation", "proof_development",
                                 "proof_critique", "approach_comparison", "test_design"):
                self._linked_input(run_id, record, user, {
                    "kind": "steer", "text": user["text"],
                })
                self._assistant(
                    run_id, "notice",
                    f"Requested bounded {act['kind'].replace('_', ' ')} work on the current "
                    "conversation and artifacts.",
                    dedupe=f"request:{record['recordId']}:{act['kind']}",
                )
        # A contribution-only turn still needs the owner to apply the barrier.
        return True

    def _apply_pending(self, run_id: str, interaction: dict, record: dict,
                       acts: list[dict], user: dict,
                       client_request_id: str | None) -> bool:
        store = self.service.store(run_id)
        kinds = [a["kind"] for a in acts]
        if "cancel" in kinds:
            self._linked_input(run_id, record, user, {"kind": "cancel", "text": user["text"]})
            return True
        for act in acts:
            if act["kind"] == "contribution":
                self._linked_contribution(run_id, record, user, act)
                self._assistant(
                    run_id, "notice",
                    f"Recorded your {act['contribution_kind']} contribution while the "
                    "decision is open; it does not answer the question.",
                    dedupe=f"received:{user['id']}",
                )
        semantic = next((a for a in acts if a["kind"] == "semantic_assertion"
                         and a.get("admission") == "commit"), None)
        if semantic is not None:
            option = semantic.get("pendingOptionId") or semantic.get("semantic_option")
            try:
                response = self.service.submit_response(run_id, interaction["id"], {
                    "clientRequestId": client_request_id or f"chat-{user['seq']}",
                    "kind": "semantic_choice",
                    "payload": {"requirement_id": "endpoint_semantics", "option_id": option},
                    "expectedRevision": interaction["revision"],
                    "expectedGoalGeneration": interaction["goal_generation"],
                    "expectedProposalHash": interaction["proposal_hash"],
                }, schedule=False)
                store.update_chat_links(user["id"], interaction_id=interaction["id"],
                                        response_id=response.get("responseId"))
            except (PolicyDenied, LedgerError, IdempotencyConflict) as exc:
                self._assistant(run_id, "notice",
                                f"I could not record that answer: {exc}", dedupe=None)
                return False
            request = next((a for a in acts if a["kind"] in (
                "information_request", "proof_explanation", "proof_development",
                "proof_critique", "test_design", "approach_comparison")), None)
            if request is not None:
                self._linked_input(run_id, record, user, {
                    "kind": "steer", "text": user["text"],
                })
            return True
        effect = next((a for a in acts if a["kind"] == "effect_request"), None)
        if effect is not None:
            path = self._interaction_path(interaction)
            if path is None:
                self._assistant(run_id, "clarify",
                                "I cannot bind this approval to a concrete current effect. "
                                "The card stays open.", dedupe=None)
                return False
            try:
                response = self.service.submit_response(run_id, interaction["id"], {
                    "clientRequestId": client_request_id or f"chat-{user['seq']}",
                    "kind": "authorize_effect",
                    "payload": {"effect_manifest_hash": interaction["proposal_hash"],
                                "grant_scope_ref": f"path:{path}", "decision": "approve"},
                    "expectedRevision": interaction["revision"],
                    "expectedGoalGeneration": interaction["goal_generation"],
                    "expectedProposalHash": interaction["proposal_hash"],
                }, schedule=False)
                store.update_chat_links(user["id"], interaction_id=interaction["id"],
                                        response_id=response.get("responseId"))
            except (PolicyDenied, LedgerError, IdempotencyConflict) as exc:
                self._assistant(run_id, "notice",
                                f"I could not record that approval: {exc}", dedupe=None)
                return False
            return True
        if any(a["kind"] in ("information_request", "proof_explanation",
                             "proof_development", "proof_critique", "test_design",
                             "approach_comparison", "request_work") for a in acts):
            self._assistant(run_id, "explanation",
                            self._pending_explanation(interaction, user["text"]),
                            dedupe=None)
            return False
        if any(a["kind"] == "restriction" for a in acts) or any(
                a["kind"] == "semantic_assertion" and a.get("admission") != "commit"
                for a in acts):
            self._assistant(run_id, "clarify", self._clarify_text(record, interaction),
                            dedupe=None)
            return False
        self._assistant(run_id, "clarify", self._clarify_text(record, interaction),
                        dedupe=None)
        return False

    def _linked_input(self, run_id: str, record: dict, user: dict, body: dict) -> dict:
        store = self.service.store(run_id)
        receipt = self.service.submit_input(run_id, {
            **body, "clientRequestId": f"chat-{user['seq']}-{body['kind']}",
        }, schedule=False)
        receipt = receipt if "inputId" in receipt else {"inputId": receipt.get("id")}
        if receipt.get("inputId"):
            store.bind_decision_input(record["recordId"], receipt["inputId"])
            store.update_chat_links(user["id"], input_id=receipt["inputId"])
        return receipt

    def _linked_contribution(self, run_id: str, record: dict, user: dict,
                             act: dict) -> dict:
        store = self.service.store(run_id)
        receipt = self.service.runtime(run_id).inputs.submit_input(run_id, {
            "kind": "contribute",
            "clientRequestId": f"chat-{user['seq']}-{act['kind']}-{act['contribution_kind']}",
            "payload": {"contributionKind": act["contribution_kind"],
                        "content": act["contribution_text"],
                        "attribution": "author"},
        })
        store.bind_decision_input(record["recordId"], receipt["inputId"])
        store.update_chat_links(user["id"], input_id=receipt["inputId"])
        return receipt

    def _pending_explanation(self, interaction: dict, request: str = "") -> str:
        options = " / ".join(str(o.get("label") or o.get("id"))
                             for o in interaction.get("options") or [])
        lines = [f"The open question is: {interaction['prompt_ref']}"]
        if interaction.get("why"):
            lines.append("Why it matters: " + interaction["why"])
        if options:
            lines.append("Available options: " + options)
        if request:
            lines.append(f"Your request: {request[:500]}")
            lines.append("I can answer the open question or answer this request; the question "
                         "stays open until you choose. No proof or test result is claimed while "
                         "the endpoint semantics are unresolved.")
        lines.append("I have not committed an answer. Reply with the option you mean, "
                     "or ask for a specific explanation.")
        return "\n\n".join(lines)

    def _clarify_text(self, record: dict, interaction: dict | None) -> str:
        reason = record.get("unresolvedReason") or "the message is not a clear instruction"
        lines = [f"I did not apply an effect: {reason}."]
        if record.get("status") in ("unavailable", "malformed"):
            lines.append("The decision service did not return a valid interpretation. "
                         "The turn remains received and inert; configure the decision model "
                         "or enable demo mode explicitly.")
        if interaction is not None:
            lines.append(self._pending_explanation(interaction))
        else:
            lines.append("Rephrase the requested change, or ask a question without "
                         "requesting an effect.")
        rejected = record.get("rejected") or []
        if rejected:
            lines.append("Rejected refs: " + "; ".join(
                f"{item.get('ref') or item.get('act')}: {item.get('reason')}"
                for item in rejected[:4]))
        return "\n\n".join(lines)

    def _result(self, run_id: str) -> dict:
        return {"runId": run_id, "messages": self.transcript(run_id)["messages"],
                "view": self.view(run_id)}

    def _decision_budget_exhausted(self, run_id: str) -> bool:
        try:
            budget = self.service.store(run_id).get_budget(run_id)
        except LedgerError:
            return True
        return (int(budget["model_attempts_used"]) >= int(budget["model_attempts_limit"])
                or float(budget["active_seconds_used"]) >= float(budget["active_seconds_limit"]))

    @staticmethod
    def _safe_control_acts(text: str) -> list[dict]:
        """Narrow unbudgeted negative controls: cancel and explicit refusal."""
        visible = " ".join(text.strip().split())
        if re.fullmatch(r"(?:cancel|stop|abort|stop\s+this\s+stage)[.!]?", visible, re.I):
            return [{"kind": "cancel", "polarity": "negative", "text": text,
                     "reason": "explicit host-safe cancellation"}]
        if re.match(r"^(?:please\s+)?(?:don'?t|do\s+not|never|stop|reject|avoid)\b",
                    visible, re.I) and re.search(
                        r"\b(?:apply|edit|patch|change|repair|proposal|effect)\b",
                        visible, re.I):
            return [{"kind": "restriction", "polarity": "negative", "text": text,
                     "reason": "explicit host-safe effect denial"}]
        return []

    # ---------------------------------------------------------------- ingress
    def _steer(self, run_id: str, text: str, user: dict) -> dict:
        kind = "cancel" if re.fullmatch(r"(?:cancel|stop|stop this stage|abort)", text.strip(), re.I) else "steer"
        runtime = self.service.runtime(run_id)
        return runtime.inputs.submit_input(run_id, {
            "kind": kind, "text": text, "clientRequestId": f"chat-{user['seq']}",
        })

    def _contribute(self, run_id: str, text: str, user: dict) -> dict:
        kind = self._contribution_kind(text) or "idea"
        content = self._code_content(text) if kind == "code" else text
        runtime = self.service.runtime(run_id)
        receipt = runtime.inputs.submit_input(run_id, {
            "kind": "contribute", "clientRequestId": f"chat-{user['seq']}",
            "payload": {"contributionKind": kind, "content": content,
                        "attribution": "author"},
        })
        return receipt

    @staticmethod
    def _explanation_request(text: str) -> bool:
        return bool(_EXPLAIN.search(text)) and not ChatService._apply_request(text)

    def _explain_now(self, run_id: str, text: str, user: dict) -> bool:
        """Answer an explanation request from committed material, not a guess.

        Returns True when the graph should be pumped (no committed explanation
        exists yet); the author's question is then a steering request.
        """
        store = self.service.store(run_id)
        if re.search(r"\b(?:apply|fix|patch|proposal)\b", text, re.I):
            current = [a for a in store.list_artifacts(run_id, current_only=True)
                       if a["kind"] in ("solution", "proposal")]
            if current:
                paths = ", ".join(f"`{a['path']}`" for a in current[-3:])
                self._assistant(
                    run_id, "explanation",
                    f"I have not applied the proposed change. The current candidate is {paths}. "
                    "A repair would be bound to that exact current artifact and its revision; "
                    "say `apply your proposed fix` to authorize that effect, or leave it unchanged.",
                    dedupe=None,
                )
                return False
        explanation = store.current_explanation(run_id)
        decisions = (self.service.runtime(run_id).inputs.collaboration(run_id).get("decisions") or [])
        if explanation is None:
            if decisions:
                lines = ["The conversation has recorded these choices:"]
                lines.append("; ".join(
                    f"{d.get('requirementId')} = {d.get('optionId') or d.get('definitionText')}"
                    f" (from {d.get('sourceId')})" for d in decisions[-6:]
                ))
                lines.append("No current explanation or evidence is committed; earlier results are "
                             "stale, so I will not present them as proof.")
                self._assistant(run_id, "explanation", "\n\n".join(lines), dedupe=None)
                return False
            self._assistant(
                run_id, "notice",
                "No explanation has been committed yet, so I will not invent one. "
                "I am passing the question to the current stage.",
                dedupe=None,
            )
            return True
        lines = [explanation["short_answer"]]
        if decisions:
            lines.append("Recorded choices: " + "; ".join(
                f"{d.get('requirementId')} = {d.get('optionId') or d.get('definitionText')}"
                f" (from {d.get('sourceId')})" for d in decisions[-6:]
            ))
        if explanation.get("uncertainty"):
            lines.append("Remaining uncertainty: " + "; ".join(explanation["uncertainty"]))
        if explanation.get("alternatives"):
            lines.append("Alternatives considered: " + "; ".join(explanation["alternatives"]))
        refs = explanation.get("evidence_refs") or []
        if refs:
            lines.append(f"Basis: {len(refs)} committed evidence reference(s); "
                         f"explanation {explanation['id']}.")
        findings = [f for f in store.list_findings(run_id) if f.get("severity") in ("high", "critical")]
        for finding in findings[-3:]:
            lines.append(f"Open {finding['severity']} finding: {finding['allegation']}")
        if explanation.get("next_author_actions"):
            lines.append("Next: " + "; ".join(explanation["next_author_actions"]))
        self._assistant(run_id, "explanation", "\n\n".join(lines), dedupe=None)
        return False

    def _set_preference(self, run_id: str, text: str, user: dict) -> dict:
        payload = self._preference(text)
        runtime = self.service.runtime(run_id)
        runtime.inputs.submit_input(run_id, {
            "kind": "set_engagement", "clientRequestId": f"chat-{user['seq']}",
            "payload": payload,
        })
        return {"inputId": None}

    def _contextual_apply(self, run_id: str, record: dict, user: dict,
                          target: dict) -> dict:
        runtime = self.service.runtime(run_id)
        runtime.inputs.authorize_contextual_edit(
            run_id, source_id=user["id"], path=target["path"],
            proposal_hash=target.get("proposalHash"),
            generation=int(target.get("generation") or 0),
            artifact_id=target.get("id"),
            revision=target.get("revision"),
            blob_hash=target.get("blobHash"),
        )
        # The original author turn is preserved in the transcript and submitted
        # unchanged.  Admission, not the text, carries the resolved effect.
        return self._linked_input(run_id, record, user, {
            "kind": "steer", "text": user["text"],
        })

    def _effect_target(self, run_id: str) -> dict | None:
        store = self.service.store(run_id)
        try:
            if store.list_artifacts(run_id, current_only=True):
                solutions = [a for a in store.list_artifacts(run_id, current_only=True)
                             if a["kind"] == "solution"]
                if solutions:
                    return {"path": solutions[-1]["path"]}
        except Exception:  # noqa: BLE001
            pass
        for contribution in store.list_contributions(run_id):
            if contribution["kind"] == "code" and contribution["revision"] == store.get_run(run_id)["observed_revision"]:
                return {"path": f"solutions/author-{contribution['id'].split('-')[-1]}.cpp"}
        pending = store.read_all(
            "SELECT * FROM interactions WHERE run_id=? AND kind='repair_review' AND status='pending'"
            " ORDER BY created_at DESC LIMIT 1", (run_id,))
        if pending:
            interaction = store.get_interaction(pending[0]["id"])
            for ref in interaction.get("evidence_refs") or []:
                try:
                    body = store.get_blob(ref).decode("utf-8", "replace")
                except LedgerError:
                    continue
                match = _PATCH_PATH.search(body)
                if match:
                    return {"path": match.group(1), "proposalHash": interaction["proposal_hash"]}
        return None

    # ---------------------------------------------------------------- answers
    def _answer_for(self, interaction: dict, text: str) -> tuple[str, dict] | None:
        kind = interaction["kind"]
        lowered = text.lower()
        if _LEMMA.search(lowered) or _CODE.search(text) or _CODE_HINT.search(text):
            # A lemma or pasted solution is a contribution, even when it also
            # contains words like "compatible" that could answer the open card.
            return None
        if _EXPLAIN.search(lowered):
            return "request_explanation", {"target_ref": interaction["id"], "question": text}
        if _DEFER.search(lowered):
            return "defer", {"target_ref": interaction["id"], "requested_next_step": text}
        if kind == "semantics":
            if _CLOSED.search(lowered) and _HALF.search(lowered):
                return None
            if _CLOSED.search(lowered):
                return "semantic_choice", {"requirement_id": "endpoint_semantics",
                                           "option_id": "closed"}
            if _HALF.search(lowered):
                return "semantic_choice", {"requirement_id": "endpoint_semantics",
                                           "option_id": "half_open"}
            return None
        if kind in ("repair_review", "delegation"):
            if _REJECT.search(lowered):
                return "reject", {"target_ref": interaction["id"], "reason": text}
            if _APPROVE.search(lowered):
                target = self._interaction_path(interaction)
                if target is None:
                    return None
                return "authorize_effect", {
                    "effect_manifest_hash": interaction["proposal_hash"],
                    "grant_scope_ref": f"path:{target}",
                    "decision": "approve",
                }
            code = self._code_content(text)
            if code:
                return "edit_proposal", {"replacement_text": code}
            return None
        if _REJECT.search(lowered):
            return "reject", {"target_ref": interaction["id"], "reason": text}
        if _APPROVE.search(lowered) and interaction.get("option_ids"):
            return "semantic_choice", {"requirement_id": "endpoint_semantics",
                                       "option_id": interaction["option_ids"][0]}
        return None

    def _interaction_path(self, interaction: dict) -> str | None:
        option_paths = []
        for option in interaction.get("options") or []:
            for path in option.get("scopePaths") or []:
                if isinstance(path, str) and path:
                    option_paths.append(path)
        if option_paths:
            return option_paths[0].removeprefix("path:")
        store = self.service.store(interaction["run_id"])
        for ref in interaction.get("evidence_refs") or []:
            try:
                body = store.get_blob(ref).decode("utf-8", "replace")
            except LedgerError:
                continue
            match = _PATCH_PATH.search(body)
            if match:
                return match.group(1)
        solutions = [a for a in store.list_artifacts(interaction["run_id"], current_only=True)
                     if a["kind"] == "solution"]
        return solutions[-1]["path"] if solutions else None

    # ---------------------------------------------------------------- sync
    def _pump(self, run_id: str) -> None:
        try:
            self.service.pump_sync(run_id, max_steps=140)
        except Exception as exc:  # noqa: BLE001
            self._assistant(run_id, "notice", f"The controller could not continue: {exc}",
                            dedupe=f"pump-error:{str(exc)[:80]}")

    def _sync(self, run_id: str) -> None:
        store = self.service.store(run_id)
        self._sync_artifacts(run_id)
        run = store.get_run(run_id)
        collab = self.service.runtime(run_id).inputs.collaboration(run_id)
        interaction = store.pending_interaction(run_id)
        if interaction is not None:
            options = " / ".join(str(o.get("label") or o.get("id")) for o in interaction["options"])
            text = interaction["prompt_ref"]
            if interaction.get("why"):
                text += "\n\nWhy: " + interaction["why"]
            if options:
                text += "\n\nOptions: " + options
            self._assistant(run_id, "decision", text,
                            interaction_id=interaction["id"],
                            dedupe=f"interaction:{interaction['id']}")
        for finding in store.list_findings(run_id):
            self._assistant(
                run_id, "finding",
                f"{finding['severity']}: {finding['allegation']}",
                dedupe=f"finding:{finding['id']}",
            )
        for evidence in store.list_evidence(run_id):
            if evidence["domain"] != "weighted_campaign" or evidence["freshness"] != "current":
                continue
            report = json.loads(store.get_blob(evidence["artifact_refs"][0]))
            outcome = report["classification"].replace("_", " ")
            scope = "registered domain" if report["mode"] == "exhaustive" else "seeded sample"
            worker = evidence["environment_ref"] or "worker unavailable"
            self._assistant(run_id, "campaign",
                            f"Weighted scheduling campaign, seed {report['seed']}: {outcome}. "
                            f"Compared {report['completed']} of {report['declared']} inputs in the {scope}. "
                            f"Worker: {worker}.", dedupe=f"campaign:{evidence['id']}")
        explanation = store.current_explanation(run_id)
        if explanation is not None:
            text = explanation["short_answer"]
            if explanation.get("uncertainty"):
                text += "\n\nRemaining uncertainty: " + "; ".join(explanation["uncertainty"])
            if explanation.get("next_author_actions"):
                text += "\n\nNext: " + "; ".join(explanation["next_author_actions"])
            self._assistant(run_id, "explanation", text,
                            dedupe=f"explanation:{explanation['id']}")
        handoff = store.latest_handoff(run_id)
        if handoff is not None:
            lines = [f"Stage outcome: {handoff['outcome']}."]
            if handoff.get("stage_return"):
                stage = handoff["stage_return"]
                lines.append(
                    f"Typed return {stage.get('contract', {}).get('kind')} satisfied: "
                    f"{stage.get('satisfied')}."
                )
            if handoff.get("open_questions"):
                lines.append("Open questions: " + "; ".join(handoff["open_questions"]))
            if handoff.get("next_actions"):
                lines.append("Next: " + "; ".join(handoff["next_actions"]))
            if handoff["outcome"] in ("incomplete", "cancelled", "blocked"):
                lines.append("This is not a completed package or delivery approval.")
            self._assistant(run_id, "handoff", "\n".join(lines),
                            dedupe=f"handoff:{handoff['id']}")
        for artifact in store.list_artifacts(run_id):
            if artifact["validity"] in ("stale", "unresolved"):
                self._assistant(
                    run_id, "notice",
                    f"{artifact['kind']} artifact `{artifact['path']}` is "
                    f"{artifact['validity']}: {artifact['validity_reason'] or 'dependency changed'}",
                    dedupe=f"invalid:{artifact['id']}",
                    artifact_ids=[artifact["id"]],
                )
        for row in store.read_all("SELECT receipt_json FROM package_checks WHERE run_id=? AND receipt_json IS NOT NULL",
                                  (run_id,)):
            receipt = json.loads(row["receipt_json"])
            if receipt["status"] != "candidate_failed":
                continue
            failure = receipt["failure"]
            if failure["status"] == "wrong_answer":
                text = (f"The reference returned {failure['actual'] or '(empty output)'} on {failure['case_id']}. "
                        f"The independent oracle expected {failure['expected']}.")
            else:
                text = f"The reference failed the isolated check on {failure['case_id']} ({failure['status']})."
            self._assistant(run_id, "notice", text, dedupe=f"package-check:{receipt['id']}")
        draft = [artifact for artifact in store.list_artifacts(run_id, current_only=True)
                 if artifact["provenance"].get("packageDraft")]
        if draft:
            tests = [item for item in draft if item["kind"] == "test"]
            checked = draft[0]["provenance"].get("packageCheck")
            status = (f" The reference passed {checked['cases']} isolated oracle checks after "
                      f"{checked['repairs']} repair round(s)." if checked else
                      " This draft has no execution receipt.")
            self._assistant(
                run_id, "artifact",
                f"Drafted a reference solution, a wrong-answer baseline, and {len(tests)} test inputs. "
                "The independent oracle computed the expected totals." + status +
                " Review the files and copy them to the package for verification and export review.",
                dedupe=f"package-draft:{draft[0]['provenance']['actionId']}",
                artifact_ids=[item["id"] for item in draft],
            )
        if run["status"] == "blocked" and run["stop_reason"] not in (None, "unsupported_profile",
                                                                   "model_unavailable"):
            self._assistant(run_id, "notice",
                            f"The stage is blocked: {run['stop_reason']}.",
                            dedupe=f"blocked:{run['stop_reason']}")
        if run["stop_reason"] in PROVIDER_ERRORS:
            reason = run["stop_reason"]
            self._assistant(run_id, "notice", PROVIDER_ERRORS[reason],
                            dedupe=f"stop:{reason}:{run['goal_generation']}")
        if run["stop_reason"] in ("infrastructure_error", "worker_unavailable", "unknown_outcome",
                                  "model_contract", "budget_exhausted", "deadline",
                                  "admission_denied"):
            self._assistant(
                run_id, "notice",
                f"The stage stopped with `{run['stop_reason']}`. No result was fabricated; "
                "current evidence is preserved and the run can continue when the cause is resolved.",
                dedupe=f"stop:{run['stop_reason']}:{run['goal_generation']}",
            )

    def _sync_artifacts(self, run_id: str) -> None:
        store = self.service.store(run_id)
        runtime = self.service.runtime(run_id)
        run = store.get_run(run_id)
        collab = runtime.inputs.collaboration(run_id)
        generation = int(run["goal_generation"])
        semantics = self._semantics_state(collab)
        dependency = [{"requirementId": "endpoint_semantics",
                       "generation": semantics["generation"],
                       "decisionId": semantics.get("decisionId")}]
        if collab.get("artifact_generation") != generation:
            invalidated: list[str] = []
            if collab.get("artifact_generation") is not None:
                reason = (f"semantic correction at generation {generation}"
                          + (f" ({semantics.get('option')})" if semantics.get("option") else ""))
                invalidated = store.invalidate_artifacts(
                    run_id,
                    kinds=["spec", "editorial", "validator", "test_plan", "proof", "test",
                           "solution", "statement", "negative"],
                    reason=reason, generation=generation,
                    depends_requirement="endpoint_semantics",
                    decision_id=semantics.get("decisionId"),
                )
                for artifact_id in invalidated:
                    artifact = store.get_artifact(artifact_id)
                    if artifact["kind"] != "test":
                        continue
                    body = store.artifact_body(artifact_id).decode("utf-8", "replace")
                    check = self._expectation_check(body, semantics.get("option"))
                    if check["status"] == "mismatch":
                        store.set_artifact_validity(
                            artifact_id, "stale", reason=check["reason"], current=False)
            collab["artifact_generation"] = generation
            store.update_run(run_id, collaboration_json=canonical_json(collab))
        contributions = store.list_contributions(run_id)
        ideas = [store.get_blob(c["original_blob_hash"]).decode("utf-8", "replace")
                 for c in contributions if c["kind"] == "idea" and not c.get("supersedes")]
        decisions = collab.get("decisions") or []
        if decisions or ideas:
            spec = self._spec_text(run, collab)
            self._artifact(run_id, "spec", "spec/problem.md", spec,
                           source_turn=(decisions[-1] or {}).get("sourceId"),
                           generation=generation, depends=dependency)
            validator = self._validator_text()
            self._artifact(run_id, "validator", "validators/validate.py", validator,
                           source_turn=(decisions[-1] or {}).get("sourceId"),
                           generation=generation, depends=dependency)
            editorial = self._editorial_text(run, collab, ideas)
            self._artifact(run_id, "editorial", "editorial/approach.md", editorial,
                           source_turn=(decisions[-1] or {}).get("sourceId"),
                           generation=generation, depends=dependency)
            self._artifact(run_id, "test_plan", "tests/plan.md",
                           self._test_plan_text(semantics.get("option")),
                           source_turn=(decisions[-1] or {}).get("sourceId"),
                           generation=generation, depends=dependency)
        for item in store.list_inputs(run_id):
            if item["kind"] != "contribute" or item["status"] not in ("received", "applied"):
                continue
            payload = item.get("payload") or {}
            contribution_kind = str(payload.get("contributionKind") or payload.get("kind") or "")
            if contribution_kind not in ("code", "lemma", "test"):
                continue
            content = payload.get("content")
            if not isinstance(content, str) or not content:
                ref = payload.get("originalBlobRef")
                if ref:
                    try:
                        content = store.get_blob(ref).decode("utf-8", "replace")
                    except LedgerError:
                        continue
            if not content:
                continue
            input_generation = int(item.get("generation_at_receipt") or 0)
            depends = [{"requirementId": "endpoint_semantics",
                        "generation": input_generation,
                        "inputId": item["id"]}]
            validity = "current"
            reason = ""
            if contribution_kind != "code" and input_generation != generation:
                validity = "stale"
                reason = (f"depends on semantics generation {input_generation}; "
                          f"the current generation is {generation}")
            provenance = {"chat_native": True, "inputId": item["id"],
                          "semanticGeneration": input_generation,
                          "semantics": semantics.get("option")}
            if contribution_kind == "test":
                check = self._expectation_check(content, semantics.get("option"))
                provenance["expectationCheck"] = check
                if check["status"] == "mismatch":
                    validity = "unresolved"
                    reason = check["reason"]
                elif check["status"] == "unresolved" and semantics.get("option") is None:
                    validity = "unresolved"
                    reason = "endpoint semantics are unresolved; expectation cannot be validated"
            suffix = item["id"].split("-")[-1]
            revision = next((c["revision"] for c in contributions
                             if c["source_input_id"] == item["id"]), run["observed_revision"])
            source_turn = self._turn_for_input(run_id, item["id"])
            if contribution_kind == "code":
                self._artifact(run_id, "solution", f"solutions/author-{suffix}.cpp",
                               content, revision=revision, source_turn=source_turn,
                               generation=input_generation, depends=depends,
                               provenance=provenance)
            elif contribution_kind == "test":
                self._artifact(run_id, "test", f"tests/test-{suffix}.txt",
                               content, revision=revision, source_turn=source_turn,
                               generation=input_generation, validity=validity,
                               reason=reason, depends=depends, provenance=provenance)
            else:
                self._artifact(run_id, "proof", f"proof/lemma-{suffix}.md",
                               content, revision=revision, source_turn=source_turn,
                               generation=input_generation, validity=validity,
                               reason=reason, depends=depends, provenance=provenance)
        for contribution in contributions:
            if contribution.get("supersedes"):
                continue
            if contribution.get("source_input_id") and contribution["kind"] in ("code", "lemma", "test"):
                continue
            body = store.get_blob(contribution["original_blob_hash"]).decode("utf-8", "replace")
            if contribution["kind"] == "code":
                path = f"solutions/author-{contribution['id'].split('-')[-1]}.cpp"
                self._artifact(run_id, "solution", path, body,
                               revision=contribution["revision"],
                               source_turn=self._turn_for_input(run_id, contribution["source_input_id"]),
                               generation=generation)
            elif contribution["kind"] == "test":
                path = f"tests/test-{contribution['id'].split('-')[-1]}.txt"
                self._artifact(run_id, "test", path, body,
                               revision=contribution["revision"],
                               source_turn=self._turn_for_input(run_id, contribution["source_input_id"]),
                               generation=generation, depends=dependency)
            elif contribution["kind"] == "lemma":
                path = f"proof/lemma-{contribution['id'].split('-')[-1]}.md"
                self._artifact(run_id, "proof", path, body,
                               revision=contribution["revision"],
                               source_turn=self._turn_for_input(run_id, contribution["source_input_id"]),
                               generation=generation, depends=dependency)
        for evidence in store.list_evidence(run_id):
            if evidence["freshness"] != "current" or evidence["outcome"] != "patch":
                continue
            for ref in evidence.get("artifact_refs") or []:
                try:
                    patch = json.loads(store.get_blob(ref).decode("utf-8"))
                except Exception:  # noqa: BLE001
                    continue
                path = patch.get("path")
                revision = patch.get("newRevision")
                if not path or not revision:
                    continue
                try:
                    rev = store.get_revision(revision)
                    file = next(f for f in rev["files"] if f["canonical_path"] == path)
                    body = store.get_blob(file["hash"]).decode("utf-8", "replace")
                except Exception:  # noqa: BLE001
                    continue
                self._artifact(run_id, "solution", path, body, revision=revision,
                               source_turn=self._turn_for_input(
                                   run_id, (evidence.get("input_refs") or [None])[0]),
                               generation=generation)

    @staticmethod
    def _semantics_state(collab: dict) -> dict:
        decisions = collab.get("decisions") or []
        for decision in reversed(decisions):
            if decision.get("requirementId") == "endpoint_semantics":
                return {"option": decision.get("optionId"),
                        "decisionId": decision.get("id"),
                        "sourceId": decision.get("sourceId"),
                        "generation": int(decision.get("generation") or 0)}
        return {"option": None, "decisionId": None, "sourceId": None, "generation": 0}

    @staticmethod
    def _expectation_check(text: str, semantics: str | None) -> dict:
        import re as _re

        tuples = [(int(a), int(b), int(w)) for a, b, w in
                  _re.findall(r"\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", text)]
        expected_match = _re.search(r"expected(?:\s+total)?\s*(?:is|=|:)?\s*(\d+)", text, _re.I)
        if not tuples or expected_match is None:
            return {"status": "unparsed", "reason": "no interval tuple and expected total"}
        if semantics not in ("half_open", "closed"):
            return {"status": "unresolved", "reason": "endpoint semantics unresolved"}
        expected = int(expected_match.group(1))
        computed = _max_compatible_reward(tuples, half_open=semantics == "half_open")
        if computed != expected:
            return {"status": "mismatch", "expected": expected, "computed": computed,
                    "semantics": semantics,
                    "reason": (f"stated expectation {expected} is not valid under {semantics}; "
                               f"the independent subset computation gives {computed}")}
        return {"status": "ok", "expected": expected, "computed": computed,
                "semantics": semantics}

    def _artifact(self, run_id: str, kind: str, path: str, text: str, *,
                  revision: str | None = None, source_turn: str | None = None,
                  generation: int | None = None, validity: str = "current",
                  reason: str = "", depends: list[dict] | None = None,
                  provenance: dict | None = None) -> dict:
        store = self.service.store(run_id)
        artifact = store.create_artifact(
            run_id, kind=kind, path=path, body=text.encode("utf-8"),
            revision=revision or store.get_run(run_id)["observed_revision"],
            source_turn=source_turn,
            provenance={**(provenance or {}), "chat_native": True},
            generation=generation, validity=validity, validity_reason=reason,
            depends=depends,
        )
        if artifact["validity"] in ("current", "revalidated"):
            self._assistant(run_id, "artifact",
                            f"Updated {kind} artifact `{path}`.",
                            dedupe=f"artifact:{artifact['id']}",
                            artifact_ids=[artifact["id"]])
        else:
            self._assistant(run_id, "notice",
                            f"{kind} artifact `{path}` is {artifact['validity']}: "
                            f"{artifact['validity_reason'] or reason}",
                            dedupe=f"invalid:{artifact['id']}",
                            artifact_ids=[artifact["id"]])
        return artifact

    def _turn_for_input(self, run_id: str, input_id: str | None) -> str | None:
        if not input_id:
            return None
        row = self.service.store(run_id).read_one(
            "SELECT id FROM chat_messages WHERE run_id=? AND input_id=? ORDER BY seq DESC LIMIT 1",
            (run_id, input_id),
        )
        return row["id"] if row else input_id

    def _spec_text(self, run: dict, collab: dict) -> str:
        decisions = collab.get("decisions") or []
        requirements = collab.get("requirements") or []
        lines = [f"# {run['goal_text'].splitlines()[0][:120]}", "",
                 "Status: proposed from author conversation; not delivery-approved.", ""]
        if requirements:
            lines.append("## Requirements")
            for item in requirements:
                lines.append(f"- {item.get('id')}: {item.get('text')}")
            lines.append("")
        lines.append("## Decisions (latest per requirement)")
        latest: dict[str, dict] = {}
        for decision in decisions:
            latest[str(decision.get("requirementId"))] = decision
        for decision in latest.values():
            lines.append(f"- {decision.get('requirementId')}: "
                         f"{decision.get('optionId') or decision.get('definitionText')} "
                         f"(source {decision.get('sourceId')})")
        if len(decisions) > len(latest):
            lines.append(f"- Superseded earlier choices remain in conversation history "
                         f"({len(decisions) - len(latest)} revision(s)).")
        lines.extend(["", "## Open obligations",
                      "- Proof and bounded executable evidence remain to be reviewed."])
        return "\n".join(lines) + "\n"

    @staticmethod
    def _validator_text() -> str:
        return (
            "# Generated validator contract for the weighted interval profile.\n"
            "# Input: n >= 1; then n lines start finish reward; 0 <= start < finish <= 1e9;\n"
            "# 1 <= reward <= 1e9; total reward <= 2e14. Reject extra tokens and invalid UTF-8.\n"
            "def validate(text):\n"
            "    tokens = text.split()\n"
            "    n = int(tokens[0])\n"
            "    assert n >= 1 and len(tokens) == 1 + 3 * n\n"
            "    for i in range(n):\n"
            "        s, f, w = map(int, tokens[1 + 3*i:4 + 3*i])\n"
            "        assert 0 <= s < f and w >= 1\n"
            "    return True\n"
        )

    @staticmethod
    def _test_plan_text(semantics: str | None = None) -> str:
        if semantics == "half_open":
            boundary = ("- Hand boundary: touching intervals are compatible "
                        "(half-open, finish <= start).")
        elif semantics == "closed":
            boundary = ("- Hand boundary: touching intervals conflict "
                        "(closed, finish < start).")
        else:
            boundary = ("- Hand boundary: endpoint semantics are unresolved; no coverage claim "
                        "is made for touching intervals.")
        return (
            "# Test plan\n\n"
            + boundary + "\n"
            "- Nested intervals challenge reward choice under the current rule.\n"
            "- Duplicate labelled jobs remain distinct.\n"
            "- Large rewards exercise 64-bit accumulation.\n"
            "- Finite ordered domain of the six declared job types, lengths 1..4 (1,554 cases).\n"
            "- Independent subset oracle checks selected pairs directly; it never reuses the DP.\n"
            "- Expected totals are validated against the current endpoint semantics; stale "
            "expectations are reported rather than silently reused.\n"
        )

    def _editorial_text(self, run: dict, collab: dict, ideas: list[str]) -> str:
        decisions = collab.get("decisions") or []
        lines = ["# Approach and editorial notes", "",
                 "The current conversation has recorded these decisions:"]
        for decision in decisions:
            lines.append(f"- {decision.get('requirementId')}: "
                         f"{decision.get('optionId') or decision.get('definitionText')}")
        if ideas:
            lines.extend(["", "## Author-proposed approaches (verbatim)"])
            for index, idea in enumerate(ideas[-6:], start=1):
                lines.append(f"{index}. {idea[:1500]}")
        lines.extend([
            "",
            "A proposed solution must still be supported by an independent finite oracle,",
            "bounded evidence and a reviewed argument. A fluent model explanation is not proof.",
        ])
        return "\n".join(lines) + "\n"

    # ---------------------------------------------------------------- helpers
    def _assistant(self, run_id: str, kind: str, text: str, *,
                   dedupe: str | None = None, interaction_id: str | None = None,
                   artifact_ids: list[str] | None = None) -> dict:
        return self.service.store(run_id).append_chat_message(
            run_id, role="agent", kind=kind, text=text,
            interaction_id=interaction_id, artifact_ids=artifact_ids, dedupe_key=dedupe,
        )

    def transcript(self, run_id: str, after: int = 0, *, before: int | None = None) -> dict:
        store = self.service.store(run_id)
        if before is not None:
            messages = store.recent_chat_messages(run_id, before=before, limit=100)
            return {"runId": run_id, "messages": messages, "older": bool(messages and messages[0]["seq"] > 1),
                    "evidenceCards": project_cards(store, run_id, messages)}
        messages = store.list_chat_messages(run_id, after=after, limit=500)
        return {"runId": run_id, "messages": messages,
                "nextSeq": (messages[-1]["seq"] + 1) if messages else after + 1}

    def view(self, run_id: str, *, studio: bool = False) -> dict:
        view = self.service.view(run_id)
        store = self.service.store(run_id)
        view["chatMessages"] = store.recent_chat_messages(run_id, limit=100 if studio else 200)
        view["hasEarlierChat"] = bool(view["chatMessages"] and view["chatMessages"][0]["seq"] > 1)
        if studio:
            view["requestContext"] = store.request_context(run_id)
        view["evidenceCards"] = project_cards(store, run_id, view["chatMessages"])
        view["artifacts"] = [
            {"id": artifact["id"], "kind": artifact["kind"], "path": artifact["path"],
             "blobHash": artifact["blob_hash"], "revision": artifact["revision"],
             "sourceTurn": artifact["source_turn"], "current": artifact["current"],
             "generation": artifact["generation"], "validity": artifact["validity"],
             "validityReason": artifact["validity_reason"],
             "depends": artifact["depends"]}
            for artifact in store.list_artifacts(run_id)
        ]
        last_decision = None
        for message in reversed(store.recent_chat_messages(run_id, limit=50)):
            if message["role"] != "author":
                continue
            record = store.decision_for_message(run_id, message["id"])
            if record is not None:
                last_decision = {
                    "recordId": record["id"], "messageId": message["id"],
                    "status": record["status"], "model": record["model_identity"],
                    "modelVersion": record["model_version"],
                    "schemaVersion": record["schema_version"],
                    "promptVersion": record["prompt_version"],
                    "contextRevision": record["context_revision"],
                    "contextGeneration": record["context_generation"],
                    "interpretation": record["interpretation"],
                    "disposition": record["disposition"],
                }
                break
        view["lastDecision"] = last_decision
        return view

    @staticmethod
    def _is_contribution(text: str) -> bool:
        return ChatService._contribution_kind(text) is not None

    @staticmethod
    def _contribution_kind(text: str) -> str | None:
        if _CODE.search(text) or _CODE_HINT.search(text):
            return "code"
        if _LEMMA.search(text):
            return "lemma"
        if _TEST.search(text) and not _APPLY.search(text):
            return "test"
        if _IDEA.search(text):
            return "idea"
        return None

    @staticmethod
    def _code_content(text: str) -> str:
        match = _CODE.search(text)
        return match.group(1) if match else text

    @staticmethod
    def _apply_request(text: str) -> bool:
        return bool(_APPLY.search(text) and re.search(
            r"\b(?:fix|patch|repair|proposal|change|solution|it|that|this)\b", text, re.I))

    @staticmethod
    def _preference(text: str) -> dict | None:
        payload = {}
        if _BRIEF.search(text):
            payload["explanation_depth"] = "brief"
        elif _DETAILED.search(text):
            payload["explanation_depth"] = "detailed"
        if _DELEGATED.search(text):
            payload["engagement"] = "delegated"
        elif _TOGETHER.search(text):
            payload["engagement"] = "together"
        if not payload:
            return None
        # Preference-only messages have no edit verbs or decisions.
        if re.search(r"\b(?:apply|edit|patch|fix|repair|closed|half[- ]open)\b", text, re.I):
            return None
        return payload
