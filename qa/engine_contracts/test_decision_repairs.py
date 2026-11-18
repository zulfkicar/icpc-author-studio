"""DR01-DR03: decision admission provenance, receipt ordering and budgets."""
from __future__ import annotations

import json
import pathlib
import tempfile
import threading
import time
import urllib.request

import pytest
from http.server import HTTPServer

from author_studio import server
from engine.decisions import DecisionService, ModelDecisionAdapter, UnavailableDecisionAdapter
from engine.demo import ConversationDemoModel
from engine.model import FakeModelAdapter
from engine.service import EngineService
from engine.store import IdempotencyConflict
from engine.worker import FakeWorker
from qa.engine_contracts.harness import FIXTURES, plan
from qa.engine_contracts.test_chat_native import ChatHarness, begin, settled
from qa.engine_contracts.test_chat_repairs import edit_grants, inject_edit, patch_evidence

SOLUTION_TEXT = "```cpp\nint main(){ /* AUTHOR_ORIGINAL */ return 0; }\n```"


def hostile(h: ChatHarness, run_id: str, data: dict, calls: list | None = None):
    model = FakeModelAdapter(script={"decision.interpret": [{"kind": "ok", "data": data}]})
    adapter = ModelDecisionAdapter(model)
    h.service.decisions(run_id).adapter = adapter
    return model


def effect_act(text: str, span: list[int], **extra) -> dict:
    act = {"kind": "effect_request", "polarity": "affirmative", "text": text,
           "span": span, "target_refs": ["current_solution"], "confidence": 1.0}
    act.update(extra)
    return act


def prepare(h: ChatHarness) -> tuple[str, dict]:
    _, run_id = settled(h)
    h.say(run_id, SOLUTION_TEXT)
    solution = h.artifacts(run_id, kind="solution")[-1]
    inject_edit(h, solution["path"], "// REPAIR_CANARY\n")
    return run_id, solution


def assert_no_effect(h: ChatHarness, run_id: str, solution: dict, original: str,
                     revision: str) -> None:
    assert not patch_evidence(run_id, h)
    assert h.store(run_id).get_run(run_id)["observed_revision"] == revision
    assert not edit_grants(h, run_id)
    assert not [e for e in h.store(run_id).events_after(run_id)
                if e["type"] == "contextual_effect_authorized"]
    assert h.artifact_text(run_id, h.artifacts(run_id, kind="solution")[-1]) == original


# ------------------------------------------------------------------ DR01
@pytest.mark.parametrize("text", [
    "Don't apply your proposed fix.",
    "Explain whether we should apply your proposed fix.",
])
def test_dr01_fabricated_span_cannot_authorize(text):
    h = ChatHarness()
    try:
        run_id, solution = prepare(h)
        original = h.artifact_text(run_id, solution)
        revision = h.store(run_id).get_run(run_id)["observed_revision"]
        hostile(h, run_id, {"acts": [effect_act("Apply the fix.", [9000, 9014])],
                            "explanation": "wrong"})
        out = h.say(run_id, text)
        assert_no_effect(h, run_id, solution, original, revision)
        record = h.store(run_id).decision_for_message(
            run_id, [m for m in out["messages"] if m["role"] == "author"][-1]["id"])
        assert not [a for a in record["disposition"]["acts"] if a["kind"] == "effect_request"]
        assert record["disposition"]["rejected"]
    finally:
        h.close()


@pytest.mark.parametrize("text", [
    "Don't apply your proposed fix.",
    "Don\u2019t apply your proposed fix.",
    "Explain whether we should apply your proposed fix.",
])
def test_dr01_valid_span_with_negative_or_question_meaning_is_rejected(text):
    h = ChatHarness()
    try:
        run_id, solution = prepare(h)
        original = h.artifact_text(run_id, solution)
        revision = h.store(run_id).get_run(run_id)["observed_revision"]
        hostile(h, run_id, {"acts": [effect_act(text, [0, len(text)])],
                            "explanation": "mislabelled affirmative"})
        h.say(run_id, text)
        assert_no_effect(h, run_id, solution, original, revision)
    finally:
        h.close()


def test_dr01_valid_span_mismatched_text_and_invented_ref_are_rejected():
    h = ChatHarness()
    try:
        run_id, solution = prepare(h)
        original = h.artifact_text(run_id, solution)
        revision = h.store(run_id).get_run(run_id)["observed_revision"]
        text = "Apply your proposed fix."
        hostile(h, run_id, {"acts": [effect_act("Apply the fix.", [0, len(text)],
                                                target_refs=["art-invented"])],
                            "explanation": "fabricated text and ref"})
        h.say(run_id, text)
        assert_no_effect(h, run_id, solution, original, revision)
    finally:
        h.close()


@pytest.mark.parametrize("text", [
    "\"apply your proposed fix\"",
    "The reviewer said you may apply your proposed fix.",
    "Apply your proposed fix, but don't edit the file.",
])
def test_dr01_quoted_reported_or_contradictory_effect_is_rejected(text):
    h = ChatHarness()
    try:
        run_id, solution = prepare(h)
        original = h.artifact_text(run_id, solution)
        revision = h.store(run_id).get_run(run_id)["observed_revision"]
        hostile(h, run_id, {"acts": [effect_act(text, [0, len(text)])],
                            "explanation": "reported/quoted"})
        h.say(run_id, text)
        assert_no_effect(h, run_id, solution, original, revision)
    finally:
        h.close()


def test_dr01_positive_exact_provenance_publishes_once():
    h = ChatHarness()
    try:
        run_id, solution = prepare(h)
        revision = h.store(run_id).get_run(run_id)["observed_revision"]
        text = "Apply your proposed fix."
        hostile(h, run_id, {"acts": [effect_act(text, [0, len(text)],
                                                target_refs=[solution["id"]])],
                            "explanation": "clear approval"})
        out = h.chat.message(run_id, text, client_request_id="dr01-positive")
        assert out["view"]["status"] in ("awaiting_author", "incomplete", "stage_returned")
        assert len(patch_evidence(run_id, h)) == 1
        assert h.store(run_id).get_run(run_id)["observed_revision"] != revision
        grants = [g for g in edit_grants(h, run_id)
                  if solution["path"] in (g.get("scope_json") or "")]
        assert grants
        record = h.store(run_id).decision_for_message(
            run_id, [m for m in out["messages"] if m["role"] == "author"][-1]["id"])
        effect = [a for a in record["disposition"]["acts"] if a["kind"] == "effect_request"]
        assert effect and effect[0]["resolvedTarget"]["id"] == solution["id"]
        assert effect[0]["resolvedTarget"]["revision"] == revision
        assert effect[0]["resolvedTarget"]["blobHash"]
        h.chat.message(run_id, text, client_request_id="dr01-positive")
        assert len(patch_evidence(run_id, h)) == 1
    finally:
        h.close()


def test_dr01_stale_binding_cannot_authorize_a_replacement():
    h = ChatHarness()
    try:
        run_id, solution = prepare(h)
        text = "Apply your proposed fix."
        hostile(h, run_id, {"acts": [effect_act(text, [0, len(text)],
                                                target_refs=[solution["id"]])],
                            "explanation": "clear approval"})
        message = h.store(run_id).append_chat_message(run_id, role="author",
                                                      kind="message", text=text)
        record = h.service.decisions(run_id).interpret(run_id, message["id"], text)
        target = [a for a in record["acts"] if a["kind"] == "effect_request"][0]["resolvedTarget"]
        # Replace the artifact at the same path before application.
        h.store(run_id).create_artifact(
            run_id, kind="solution", path=solution["path"],
            body=b"// REPLACEMENT\n", generation=target["generation"])
        runtime = h.service.runtime(run_id)
        runtime.inputs.authorize_contextual_edit(
            run_id, source_id=message["id"], path=target["path"],
            generation=target["generation"], artifact_id=target["id"],
            revision=target["revision"], blob_hash=target["blobHash"])
        grant = runtime.inputs.submit_input(run_id, {
            "kind": "steer", "text": text, "clientRequestId": "dr01-stale",
        })
        h.store(run_id).bind_decision_input(record["recordId"], grant["inputId"])
        h.service.pump_sync(run_id, max_steps=120)
        assert not patch_evidence(run_id, h)
        assert all(g.get("revoked_at") for g in edit_grants(h, run_id))
    finally:
        h.close()


# ------------------------------------------------------------------ DR02
class BlockingDecision:
    identity = "blocking-decision"
    version = "1"

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def call(self, text, context, **_kwargs):
        self.calls += 1
        self.entered.set()
        if not self.release.wait(30):
            raise RuntimeError("decision block timed out")
        from engine.decisions import ScriptedDecisionAdapter
        return ScriptedDecisionAdapter().call(text, context)


def test_dr02_receipt_before_interpretation_fences_publication():
    h = ChatHarness()
    try:
        run_id, solution = prepare(h)
        h.service.failpoints.arm("editing.before_publish")
        h.say(run_id, "Apply your proposed fix.")
        assert not patch_evidence(run_id, h)
        original = h.artifact_text(run_id, solution)
        revision = h.store(run_id).get_run(run_id)["observed_revision"]
        block = BlockingDecision()
        h.service.decisions(run_id).adapter = block
        errors = []

        def refuse():
            try:
                h.chat.message(run_id, "Don't apply your proposed fix.",
                               client_request_id="dr02-race")
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

        thread = threading.Thread(target=refuse)
        thread.start()
        assert block.entered.wait(10)
        received = [i for i in h.store(run_id).list_inputs(run_id)
                    if i["status"] in ("received", "interpreting")
                    and i["kind"] == "chat_turn"]
        assert received
        pump_thread = threading.Thread(target=lambda: h.service.pump_sync(run_id, max_steps=140))
        pump_thread.start()
        # Observe while the interpreter is still blocked; no publication may occur.
        observed = []
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            observed.append(len(patch_evidence(run_id, h)))
            time.sleep(0.01)
        assert not any(observed)
        block.release.set()
        pump_thread.join(20)
        thread.join(20)
        assert not errors
        assert not patch_evidence(run_id, h)
        assert h.store(run_id).get_run(run_id)["observed_revision"] == revision
        assert h.artifact_text(run_id, h.artifacts(run_id, kind="solution")[-1]) == original
        assert any(e["type"] == "edit_authority_denied"
                   for e in h.store(run_id).events_after(run_id))
    finally:
        h.close()


def test_dr02_publication_first_is_preserved_and_later_refusal_blocks_future_effects():
    h = ChatHarness()
    try:
        run_id, solution = prepare(h)
        h.say(run_id, "Apply your proposed fix.")
        assert len(patch_evidence(run_id, h)) == 1
        revision = h.store(run_id).get_run(run_id)["observed_revision"]
        inject_edit(h, solution["path"], "// LATER_CANARY\n")
        h.say(run_id, "Don't apply your proposed fix.")
        assert len(patch_evidence(run_id, h)) == 1
        assert h.store(run_id).get_run(run_id)["observed_revision"] == revision
        assert "LATER_CANARY" not in h.artifact_text(
            run_id, h.artifacts(run_id, kind="solution")[-1])
    finally:
        h.close()


def test_dr02_resume_after_receipt_without_interpretation():
    root = pathlib.Path(tempfile.mkdtemp(prefix="dr02-resume-"))
    first = ChatHarness(root=root)
    try:
        run_id, _ = prepare(first)
        text = "Don't apply your proposed fix."
        message = first.store(run_id).append_chat_message(
            run_id, role="author", kind="message", text=text,
            dedupe_key="message:resume-receipt")
        receipt = first.service.runtime(run_id).inputs.submit_input(run_id, {
            "kind": "chat_turn", "text": text,
            "clientRequestId": "chat-turn-resume-receipt",
            "payload": {"awaitingDecision": True},
        })
        first.store(run_id).update_chat_links(message["id"], input_id=receipt["inputId"])
    finally:
        first.close()
    second = ChatHarness(root=root)
    try:
        out = second.chat.message(run_id, text, client_request_id="resume-receipt")
        assert out["view"]["revision"] == "rev-1"
        assert not patch_evidence(run_id, second)
        turns = [i for i in second.store(run_id).list_inputs(run_id)
                 if i["kind"] == "chat_turn"]
        assert turns and turns[-1]["status"] in ("superseded", "applied", "interpreting")
        assert second.store(run_id).decision_for_message(
            run_id, [m for m in out["messages"] if m["role"] == "author"][-1]["id"])
    finally:
        second.close()


# ------------------------------------------------------------------ DR02-A atomic
def active_barriers(store, run_id: str) -> list[dict]:
    return [i for i in store.list_inputs(run_id)
            if i["barrier"] and i["status"] in ("received", "interpreting",
                                                "needs_disambiguation")]


def test_dr02_atomic_turn_receipt_has_barrier_link_and_idempotency():
    h = ChatHarness()
    try:
        run_id = h.start()["runId"]
        store = h.store(run_id)
        first = store.append_chat_turn(
            run_id, role="author", text="Don't apply your proposed fix.",
            payload={"messageId": "pending", "awaitingDecision": True},
            client_request_id="atomic-turn-1", dedupe_key="message:atomic-turn-1")
        assert first["message"]["input_id"] == first["input"]["id"]
        assert first["input"]["kind"] == "chat_turn"
        assert first["input"]["barrier"] == 1
        assert first["input"]["status"] == "received"
        second = store.append_chat_turn(
            run_id, role="author", text="Don't apply your proposed fix.",
            payload={"messageId": "pending", "awaitingDecision": True},
            client_request_id="atomic-turn-1", dedupe_key="message:atomic-turn-1")
        assert second["message"]["id"] == first["message"]["id"]
        assert second["input"]["id"] == first["input"]["id"]
        assert len([m for m in store.list_chat_messages(run_id)
                    if m["dedupe_key"] == "message:atomic-turn-1"]) == 1
    finally:
        h.close()


def test_dr02_concurrent_duplicate_receipt_is_one_turn():
    h = ChatHarness()
    try:
        run_id = h.start()["runId"]
        store = h.store(run_id)
        results = []
        errors = []

        def send():
            try:
                results.append(store.append_chat_turn(
                    run_id, role="author", text="Don't apply your proposed fix.",
                    payload={"messageId": "pending", "awaitingDecision": True},
                    client_request_id="atomic-turn-concurrent",
                    dedupe_key="message:atomic-turn-concurrent"))
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

        threads = [threading.Thread(target=send) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(20)
        assert not errors
        assert len({r["input"]["id"] for r in results}) == 1
        assert len([m for m in store.list_chat_messages(run_id)
                    if m["dedupe_key"] == "message:atomic-turn-concurrent"]) == 1
    finally:
        h.close()


def test_dr02_guarded_publication_blocks_a_late_receipt():
    h = ChatHarness()
    try:
        run_id, solution = prepare(h)
        store = h.store(run_id)
        before = store.get_run(run_id)["observed_revision"]
        entered = threading.Event()
        release = threading.Event()
        original = store.publish_revision

        def gated_publish(*args, **kwargs):
            entered.set()
            if not release.wait(30):
                raise RuntimeError("publication gate timeout")
            return original(*args, **kwargs)

        store.publish_revision = gated_publish
        block = BlockingDecision()
        errors = []
        apply_thread = threading.Thread(
            target=lambda: h.say(run_id, "Apply your proposed fix."))
        apply_thread.start()
        assert entered.wait(15), "edit did not reach guarded publication"
        h.service.decisions(run_id).adapter = block

        def refuse():
            try:
                h.chat.message(run_id, "Don't apply your proposed fix.",
                               client_request_id="late-receipt-refusal")
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

        refusal_thread = threading.Thread(target=refuse)
        refusal_thread.start()
        assert block.entered.wait(10)
        barriers = active_barriers(store, run_id)
        assert barriers, "refusal barrier must be durable before the guarded write"
        release.set()
        apply_thread.join(30)
        assert not errors
        assert not patch_evidence(run_id, h)
        assert store.get_run(run_id)["observed_revision"] == before
        block.release.set()
        refusal_thread.join(30)
        assert not patch_evidence(run_id, h)
        assert store.get_run(run_id)["observed_revision"] == before
    finally:
        h.close()


def test_dr02_failed_turn_recovery_publishes_once_and_preserves_failure():
    h = ChatHarness()
    try:
        run_id, solution = prepare(h)
        store = h.store(run_id)
        service = h.service.decisions(run_id)
        good = service.adapter
        service.adapter = UnavailableDecisionAdapter()
        failed = h.chat.message(run_id, "Apply your proposed fix.",
                                client_request_id="failed-once")
        recovery = [m for m in failed["messages"] if m["kind"] == "recovery"]
        assert recovery and recovery[-1]["artifact_ids"]
        old_id = recovery[-1]["artifact_ids"][0]
        old_decision = store.decision_for_message(
            run_id, [m for m in failed["messages"] if m["role"] == "author"][-1]["id"])
        assert old_decision["status"] == "unavailable"
        service.adapter = good
        out = h.chat.message(run_id, "Apply your proposed fix.",
                             client_request_id="recovery-once",
                             recover_input_id=old_id)
        assert out["view"]["status"] in ("awaiting_author", "incomplete", "stage_returned")
        assert len(patch_evidence(run_id, h)) == 1
        assert store.get_input(old_id)["status"] == "superseded"
        assert store.decision_for_message(
            run_id, [m for m in failed["messages"] if m["role"] == "author"][-1]["id"]
        )["status"] == "unavailable", "historical failure must remain"
        assert out["view"].get("stopReason") != "controller_error"
        assert any(e["type"] == "failed_turn_resolved"
                   for e in store.events_after(run_id))
    finally:
        h.close()


def test_dr02_failed_turn_recovery_after_restart():
    root = pathlib.Path(tempfile.mkdtemp(prefix="dr02-recovery-restart-"))
    first = ChatHarness(root=root)
    try:
        run_id, solution = prepare(first)
        first.service.decisions(run_id).adapter = UnavailableDecisionAdapter()
        failed = first.chat.message(run_id, "Apply your proposed fix.",
                                    client_request_id="failed-restart")
        old_id = [m for m in failed["messages"] if m["kind"] == "recovery"][-1]["artifact_ids"][0]
    finally:
        first.close()
    second = ChatHarness(root=root)
    try:
        out = second.chat.message(run_id, "Apply your proposed fix.",
                                  client_request_id="recovery-restart",
                                  recover_input_id=old_id)
        assert len(patch_evidence(run_id, second)) == 1
        assert second.store(run_id).get_input(old_id)["status"] == "superseded"
        assert not [i for i in second.store(run_id).list_inputs(run_id)
                    if i["barrier"] and i["status"] in ("received", "interpreting")]
        assert any(m["kind"] == "recovery" for m in second.messages(run_id))
    finally:
        second.close()


def test_dr02_failed_turn_cancel_settles_without_model_call():
    h = ChatHarness()
    try:
        run_id, solution = prepare(h)
        service = h.service.decisions(run_id)
        service.adapter = UnavailableDecisionAdapter()
        out = h.chat.message(run_id, "Apply your proposed fix.",
                             client_request_id="failed-cancel")
        old_id = [m for m in out["messages"] if m["kind"] == "recovery"][-1]["artifact_ids"][0]
        calls = []
        service.adapter = type("Never", (), {
            "identity": "never", "version": "1",
            "call": lambda self, text, context, **kw: calls.append(text)})()
        cancelled = h.chat.message(run_id, "cancel", client_request_id="cancel-failed")
        assert cancelled["view"]["status"] == "cancelled"
        assert calls == []
        assert h.store(run_id).get_input(old_id)["status"] in ("superseded", "cancelled")
        assert not patch_evidence(run_id, h)
    finally:
        h.close()


def test_dr02_recovery_targets_one_failed_turn_and_leaves_another():
    h = ChatHarness()
    try:
        run_id, solution = prepare(h)
        store = h.store(run_id)
        service = h.service.decisions(run_id)
        good = service.adapter
        service.adapter = UnavailableDecisionAdapter()
        first = h.chat.message(run_id, "Apply your proposed fix.",
                               client_request_id="failed-a")
        second = h.chat.message(run_id, "Explain whether we should apply it.",
                                client_request_id="failed-b")
        a_id = [m for m in first["messages"] if m["kind"] == "recovery"][-1]["artifact_ids"][0]
        b_id = [m for m in second["messages"] if m["kind"] == "recovery"][-1]["artifact_ids"][0]
        service.adapter = good
        h.chat.message(run_id, "Apply your proposed fix.",
                       client_request_id="recovery-a", recover_input_id=a_id)
        assert store.get_input(a_id)["status"] == "superseded"
        assert store.get_input(b_id)["status"] in ("received", "interpreting")
        # The unrelated unresolved barrier still fences the recovered effect.
        assert len(patch_evidence(run_id, h)) == 0
    finally:
        h.close()


# ------------------------------------------------------------------ HTTP
def _http_start(root: pathlib.Path, model=None):
    service = EngineService(root, model_adapter=model or ConversationDemoModel(),
                            worker=FakeWorker(), fixture_dir=str(FIXTURES),
                            clone_models=False)
    server.ENGINE_SERVICE = service
    server.CHAT_SERVICE = None
    httpd = HTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=lambda: httpd.serve_forever(), daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_port}"

    def call(path, method="GET", body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"} if data else {}
        request = urllib.request.Request(base + path, data=data, method=method, headers=headers)
        with urllib.request.urlopen(request, timeout=90) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    return service, httpd, call


def _http_stop(service, httpd):
    httpd.shutdown()
    service.close()
    server.ENGINE_SERVICE = None
    server.CHAT_SERVICE = None


def test_dr01_http_hostile_provenance_and_positive_control():
    service, httpd, call = _http_start(pathlib.Path(tempfile.mkdtemp(prefix="dr01-http-")))
    try:
        _, started = call("/api/engine/chat", "POST", {
            "message": "Help me develop profitable bookings; work with me, briefly."})
        run_id = started["runId"]
        call(f"/api/engine/runs/{run_id}/messages", "POST",
             {"message": "Half-open; touching jobs are compatible."})
        _, code = call(f"/api/engine/runs/{run_id}/messages", "POST",
                       {"message": SOLUTION_TEXT})
        solution = [a for a in code["view"]["artifacts"] if a["kind"] == "solution"][-1]
        revision = code["view"]["revision"]
        original = call(f"/api/engine/runs/{run_id}/artifacts/{solution['id']}")[1]["text"]
        # Inject through the demo model used by the service.
        model = service._model_for(run_id)
        model._script["plan"].insert(0, plan("edit", args={
            "path": solution["path"], "after": "// HTTP_CANARY\n"}))
        for text in ("Don't apply your proposed fix.",
                     "Explain whether we should apply your proposed fix."):
            service.decisions(run_id).adapter = ModelDecisionAdapter(
                FakeModelAdapter(script={"decision.interpret": [{"kind": "ok", "data": {
                    "acts": [effect_act("Apply the fix.", [9000, 9014])],
                    "explanation": "hostile HTTP response"}}]}))
            status, out = call(f"/api/engine/runs/{run_id}/messages", "POST", {"message": text})
            assert status == 200
            assert out["view"]["revision"] == revision
            current = call(f"/api/engine/runs/{run_id}/artifacts/{solution['id']}")[1]["text"]
            assert current == original
        # The same service still has the queued adversarial edit; a valid
        # approval through a hostile transport with exact provenance publishes once.
        model._script["plan"].insert(0, plan("edit", args={
            "path": solution["path"], "after": "// HTTP_APPROVED\n"}))
        text = "Apply your proposed fix."
        service.decisions(run_id).adapter = ModelDecisionAdapter(
            FakeModelAdapter(script={"decision.interpret": [{"kind": "ok", "data": {
                "acts": [effect_act(text, [0, len(text)], target_refs=[solution["id"]])],
                "explanation": "exact positive"}}]}))
        status, approved = call(f"/api/engine/runs/{run_id}/messages", "POST", {"message": text})
        assert status == 200
        assert approved["view"]["revision"] != revision
        assert any(a["kind"] == "solution" for a in approved["view"]["artifacts"])
    finally:
        _http_stop(service, httpd)


def test_dr02_http_receipt_is_visible_before_interpretation_and_fences():
    service, httpd, call = _http_start(pathlib.Path(tempfile.mkdtemp(prefix="dr02-http-")))
    try:
        _, started = call("/api/engine/chat", "POST", {
            "message": "Help me develop profitable bookings; work with me, briefly."})
        run_id = started["runId"]
        call(f"/api/engine/runs/{run_id}/messages", "POST",
             {"message": "Half-open; touching jobs are compatible."})
        _, code = call(f"/api/engine/runs/{run_id}/messages", "POST",
                       {"message": SOLUTION_TEXT})
        solution = [a for a in code["view"]["artifacts"] if a["kind"] == "solution"][-1]
        revision = code["view"]["revision"]
        model = service._model_for(run_id)
        model._script["plan"].insert(0, plan("edit", args={
            "path": solution["path"], "after": "// HTTP_RACE_CANARY\n"}))
        service.failpoints.arm("editing.before_publish")
        call(f"/api/engine/runs/{run_id}/messages", "POST",
             {"message": "Apply your proposed fix."})
        block = BlockingDecision()
        service.decisions(run_id).adapter = block
        result = {}

        def refuse():
            try:
                result["response"] = call(f"/api/engine/runs/{run_id}/messages", "POST",
                                          {"message": "Don't apply your proposed fix."})
            except Exception as exc:  # noqa: BLE001
                result["error"] = repr(exc)

        thread = threading.Thread(target=refuse)
        thread.start()
        assert block.entered.wait(10)
        _, view = call(f"/api/engine/runs/{run_id}/view")
        turns = [i for i in view["inputs"]
                 if i["kind"] == "chat_turn" and i["status"] in ("received", "interpreting")]
        assert turns
        pump_thread = threading.Thread(
            target=lambda: service.pump_sync(run_id, max_steps=140))
        pump_thread.start()
        time.sleep(1.0)
        assert not [e for e in service.store(run_id).list_evidence(run_id)
                    if e["outcome"] == "patch"], "published while interpretation blocked"
        block.release.set()
        pump_thread.join(30)
        thread.join(30)
        assert "error" not in result
        _, final = call(f"/api/engine/runs/{run_id}/view")
        assert final["revision"] == revision
        assert not [e for e in service.store(run_id).list_evidence(run_id)
                    if e["outcome"] == "patch"]
    finally:
        _http_stop(service, httpd)


def test_dr03_http_exhaustion_is_recoverable_and_cancellable():
    service, httpd, call = _http_start(pathlib.Path(tempfile.mkdtemp(prefix="dr03-http-")))
    try:
        _, started = call("/api/engine/chat", "POST", {
            "message": "Help me develop profitable bookings; work with me, briefly."})
        run_id = started["runId"]
        store = service.store(run_id)
        used = store.get_budget(run_id)["model_attempts_used"]
        with store.tx() as conn:
            conn.execute("UPDATE budgets SET model_attempts_limit=? WHERE run_id=?",
                         (used, run_id))
        transport = UsageTransport()
        service.decisions(run_id).adapter = ModelDecisionAdapter(transport)
        status, out = call(f"/api/engine/runs/{run_id}/messages", "POST",
                           {"message": "Maybe closed intervals?"})
        assert status == 200
        assert transport.calls == []
        assert any(m["kind"] in ("clarify", "notice", "recovery")
                   for m in out["view"]["chatMessages"][-2:])
        turns = [i for i in out["view"]["inputs"]
                 if i["kind"] == "chat_turn" and i["status"] in ("received", "interpreting")]
        assert turns
        status, cancelled = call(f"/api/engine/runs/{run_id}/messages", "POST",
                                 {"message": "cancel"})
        assert status == 200
        assert cancelled["view"]["status"] == "cancelled"
        assert transport.calls == []
    finally:
        _http_stop(service, httpd)
class UsageTransport:
    name = "usage-transport"
    version = "1"

    def __init__(self, *, kind="ok", usage=None):
        self.kind = kind
        self.usage = usage
        self.calls = []

    def call(self, request):
        self.calls.append(request)
        if self.kind != "ok":
            return {"kind": self.kind, "error": "controlled failure",
                    "usage": self.usage or {"unknown": True}}
        return {"kind": "ok", "data": {"acts": [{"kind": "semantic_assertion",
                "polarity": "tentative", "text": request["context"]["authorText"]}]},
                "usage": self.usage}


def set_budget(h: ChatHarness, run_id: str, **updates) -> None:
    with h.store(run_id).tx() as conn:
        for key, value in updates.items():
            conn.execute(f"UPDATE budgets SET {key}=? WHERE run_id=?", (value, run_id))


def attempts_count(h: ChatHarness, run_id: str) -> int:
    return h.store(run_id).read_one(
        "SELECT COUNT(*) AS n FROM attempts a JOIN reservations r ON a.reservation_id=r.id "
        "WHERE r.run_id=?", (run_id,))["n"]


def test_dr03_exhausted_budget_makes_no_transport_call_and_keeps_barrier():
    h = ChatHarness()
    try:
        _, run_id = begin(h)
        store = h.store(run_id)
        used = store.get_budget(run_id)["model_attempts_used"]
        set_budget(h, run_id, model_attempts_limit=used)
        calls_before = attempts_count(h, run_id)
        transport = UsageTransport()
        h.service.decisions(run_id).adapter = ModelDecisionAdapter(transport)
        for index in range(3):
            out = h.chat.message(run_id, "Maybe closed intervals?",
                                 client_request_id=f"dr03-exhausted-{index}")
            assert any(m["kind"] in ("clarify", "notice", "recovery") for m in out["messages"][-2:])
        assert len(transport.calls) == 0
        assert attempts_count(h, run_id) == calls_before
        records = store.list_decision_records(run_id)[-3:]
        assert all(r["status"] == "budget_exhausted" for r in records)
        turns = [i for i in store.list_inputs(run_id)
                 if i["kind"] == "chat_turn" and i["status"] in ("received", "interpreting")]
        assert len(turns) == 3
    finally:
        h.close()


def test_dr03_one_slot_consumes_attempt_and_preserves_usage():
    h = ChatHarness()
    try:
        _, run_id = begin(h)
        store = h.store(run_id)
        used = store.get_budget(run_id)["model_attempts_used"]
        set_budget(h, run_id, model_attempts_limit=used + 1)
        before = attempts_count(h, run_id)
        transport = UsageTransport(usage={"input_tokens": 100, "output_tokens": 20,
                                          "total_tokens": 120})
        h.service.decisions(run_id).adapter = ModelDecisionAdapter(transport)
        out = h.chat.message(run_id, "Maybe closed intervals?",
                             client_request_id="dr03-one")
        assert len(transport.calls) == 1
        assert attempts_count(h, run_id) == before + 1
        record = store.decision_for_message(
            run_id, [m for m in out["messages"] if m["role"] == "author"][-1]["id"])
        assert record["usage"]["total_tokens"] == 120
        attempts = store.attempts_for(record["reservation_id"])
        assert attempts and attempts[-1]["usage"]["total_tokens"] == 120
        assert store.get_budget(run_id)["model_attempts_used"] == used + 1
        # The next call has no slot.
        out = h.chat.message(run_id, "Maybe closed intervals?",
                             client_request_id="dr03-one-next")
        assert len(transport.calls) == 1
        assert store.get_budget(run_id)["model_attempts_used"] == used + 1
    finally:
        h.close()


def test_dr03_concurrent_final_slot_has_one_transport_call():
    h = ChatHarness()
    try:
        _, run_id = begin(h)
        store = h.store(run_id)
        used = store.get_budget(run_id)["model_attempts_used"]
        set_budget(h, run_id, model_attempts_limit=used + 1)
        transport = UsageTransport()
        h.service.decisions(run_id).adapter = ModelDecisionAdapter(transport)
        errors = []

        def send(index):
            try:
                h.chat.message(run_id, "Maybe closed intervals?",
                               client_request_id=f"dr03-concurrent-{index}")
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

        threads = [threading.Thread(target=send, args=(i,)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        assert not errors
        assert len(transport.calls) == 1
        assert store.get_budget(run_id)["model_attempts_used"] == used + 1
    finally:
        h.close()


@pytest.mark.parametrize("kind", ["malformed", "refusal", "transport_error"])
def test_dr03_failure_kinds_consume_attempt_and_settle(kind):
    h = ChatHarness()
    try:
        _, run_id = begin(h)
        store = h.store(run_id)
        before = attempts_count(h, run_id)
        transport = UsageTransport(kind=kind, usage={"unknown": True})
        h.service.decisions(run_id).adapter = ModelDecisionAdapter(transport)
        out = h.chat.message(run_id, "Maybe closed intervals?",
                             client_request_id=f"dr03-{kind}")
        assert len(transport.calls) == 1
        assert attempts_count(h, run_id) == before + 1
        record = store.decision_for_message(
            run_id, [m for m in out["messages"] if m["role"] == "author"][-1]["id"])
        assert record["status"] in ("malformed", "refusal", "unavailable")
        assert record["usage"].get("unknown") is True
        assert not patch_evidence(run_id, h)
    finally:
        h.close()


def test_dr03_schema_invalid_output_consumes_attempt():
    h = ChatHarness()
    try:
        _, run_id = begin(h)
        store = h.store(run_id)
        before = attempts_count(h, run_id)
        h.service.decisions(run_id).adapter = ModelDecisionAdapter(
            FakeModelAdapter(script={"decision.interpret": [
                {"kind": "ok", "data": {"acts": "not-a-list"}}]}))
        out = h.chat.message(run_id, "Maybe closed intervals?",
                             client_request_id="dr03-schema")
        assert attempts_count(h, run_id) == before + 1
        record = store.decision_for_message(
            run_id, [m for m in out["messages"] if m["role"] == "author"][-1]["id"])
        assert record["status"] == "malformed"
        assert record["usage"].get("unknown") is True
    finally:
        h.close()


def test_dr03_active_time_exhaustion_prevents_calls():
    h = ChatHarness()
    try:
        _, run_id = begin(h)
        store = h.store(run_id)
        budget = store.get_budget(run_id)
        set_budget(h, run_id, active_seconds_used=budget["active_seconds_limit"])
        transport = UsageTransport()
        h.service.decisions(run_id).adapter = ModelDecisionAdapter(transport)
        h.chat.message(run_id, "Maybe closed intervals?",
                       client_request_id="dr03-active")
        assert transport.calls == []
        record = store.list_decision_records(run_id)[-1]
        assert record["status"] == "budget_exhausted"
        out = h.chat.message(run_id, "cancel", client_request_id="dr03-active-cancel")
        assert out["view"]["status"] == "cancelled"
        assert transport.calls == []
    finally:
        h.close()


def test_dr03_replay_spends_nothing_and_stale_body_conflicts():
    h = ChatHarness()
    try:
        _, run_id = begin(h)
        store = h.store(run_id)
        transport = UsageTransport()
        h.service.decisions(run_id).adapter = ModelDecisionAdapter(transport)
        h.chat.message(run_id, "Maybe closed intervals?", client_request_id="dr03-replay")
        assert len(transport.calls) == 1
        before = attempts_count(h, run_id)
        h.chat.message(run_id, "Maybe closed intervals?", client_request_id="dr03-replay")
        assert len(transport.calls) == 1
        assert attempts_count(h, run_id) == before
        with pytest.raises(IdempotencyConflict):
            h.chat.message(run_id, "Maybe half-open instead?",
                           client_request_id="dr03-replay")
    finally:
        h.close()


def test_dr03_safe_cancellation_and_refusal_work_at_exhaustion():
    h = ChatHarness()
    try:
        run_id, solution = prepare(h)
        h.service.failpoints.arm("editing.before_publish")
        h.say(run_id, "Apply your proposed fix.")
        assert not patch_evidence(run_id, h)
        store = h.store(run_id)
        used = store.get_budget(run_id)["model_attempts_used"]
        set_budget(h, run_id, model_attempts_limit=used)
        out = h.say(run_id, "Don't apply your proposed fix.")
        assert not patch_evidence(run_id, h)
        assert any(e["type"] == "edit_authority_denied"
                   for e in store.events_after(run_id))
        out = h.say(run_id, "cancel")
        assert out["view"]["status"] == "cancelled"
        assert not patch_evidence(run_id, h)
        assert store.get_budget(run_id)["model_attempts_used"] == used
        assert h.artifact_text(run_id, h.artifacts(run_id, kind="solution")[-1]) != ""
    finally:
        h.close()