"""CN-R01-R04 repairs: decision-layer admission, request routing and validity.

These regressions exercise the real ChatService, compiled graph, application
ledger, HTTP routes and managed solution bytes.  Model and worker transports are
scripted offline doubles and remain labelled.  No generated code is executed.
"""
from __future__ import annotations

import json
import pathlib
import tempfile
import threading
import urllib.request

import pytest
from http.server import HTTPServer

from author_studio import server
from engine.chat import ChatService
from engine.clock import CrashInjected
from engine.decisions import (
    DecisionService,
    DecisionV1,
    ModelDecisionAdapter,
    ScriptedDecisionAdapter,
    UnavailableDecisionAdapter,
)
from engine.demo import ConversationDemoModel, demo_script
from engine.model import FakeModelAdapter
from engine.service import EngineService
from engine.worker import FakeWorker
from qa.engine_contracts.harness import FIXTURES, plan
from qa.engine_contracts.test_chat_native import (
    ChatHarness,
    agent_messages,
    begin,
    grants,
    patch_evidence,
    settled,
)

ROOT = pathlib.Path(__file__).resolve().parents[2]


def edit_grants(h: ChatHarness, run_id: str) -> list[dict]:
    return [g for g in grants(run_id, h)
            if "edit" in (g.get("operation_kinds_json") or "")]


def decision_for(h: ChatHarness, run_id: str, message_id: str) -> dict:
    return h.store(run_id).decision_for_message(run_id, message_id)


def inject_edit(h: ChatHarness, path: str, text: str = "// ADVERSARIAL_CANARY\n") -> None:
    h.model._script["plan"].insert(0, plan("edit", args={"path": path, "after": text}))


# ------------------------------------------------------------------ CN-R01
@pytest.mark.parametrize("text", [
    "Don't apply your proposed fix.",
    "Explain whether we should apply your proposed fix.",
])
def test_r01_exact_reproductions_refuse_a_queued_effect(text):
    h = ChatHarness()
    try:
        _, run_id = settled(h)
        h.say(run_id, "```cpp\nint main(){ /* ORIGINAL_AUTHOR_CODE */ return 0; }\n```")
        solution = h.artifacts(run_id, kind="solution")[-1]
        original = h.artifact_text(run_id, solution)
        revision = h.store(run_id).get_run(run_id)["observed_revision"]
        before_patches = len(patch_evidence(run_id, h))
        inject_edit(h, solution["path"])
        out = h.say(run_id, text)
        assert h.store(run_id).get_run(run_id)["observed_revision"] == revision
        assert len(patch_evidence(run_id, h)) == before_patches == 0
        assert not edit_grants(h, run_id)
        assert not [e for e in h.store(run_id).events_after(run_id)
                    if e["type"] == "contextual_effect_authorized"]
        assert h.artifact_text(run_id, h.artifacts(run_id, kind="solution")[-1]) == original
        record = decision_for(h, run_id, [m for m in out["messages"]
                                         if m["role"] == "author"][-1]["id"])
        assert record["status"] == "admitted"
        assert not [a for a in record["disposition"]["acts"] if a["kind"] == "effect_request"]
        assert out["view"]["status"] in ("incomplete", "awaiting_author")
    finally:
        h.close()


@pytest.mark.parametrize("text", [
    "Don\u2019t apply your proposed fix.",
    "\"apply your proposed fix\"",
    "Maybe apply your proposed fix?",
    "If you think it is right, apply your proposed fix.",
    "The reviewer said you may apply your proposed fix.",
    "Write a short plan for applying your proposed fix.",
    "Is applying your proposed fix a good idea?",
])
def test_r01_variants_preserve_polarity_and_grant_nothing(text):
    h = ChatHarness()
    try:
        _, run_id = settled(h)
        h.say(run_id, "```cpp\nint main(){ /* ORIGINAL_AUTHOR_CODE */ return 0; }\n```")
        solution = h.artifacts(run_id, kind="solution")[-1]
        original = h.artifact_text(run_id, solution)
        revision = h.store(run_id).get_run(run_id)["observed_revision"]
        inject_edit(h, solution["path"])
        out = h.say(run_id, text)
        assert h.store(run_id).get_run(run_id)["observed_revision"] == revision, text
        assert not patch_evidence(run_id, h), text
        assert not edit_grants(h, run_id), text
        assert h.artifact_text(run_id, h.artifacts(run_id, kind="solution")[-1]) == original
        assert out["view"]["status"] != "patch"
    finally:
        h.close()


def test_r01_clear_contextual_approval_publishes_exactly_once():
    h = ChatHarness()
    try:
        _, run_id = settled(h)
        h.say(run_id, "```cpp\nint main(){ /* ORIGINAL_AUTHOR_CODE */ return 0; }\n```")
        solution = h.artifacts(run_id, kind="solution")[-1]
        inject_edit(h, solution["path"], "// APPROVED_CANARY\n")
        revision = h.store(run_id).get_run(run_id)["observed_revision"]
        out = h.chat.message(run_id, "Apply your proposed fix.", client_request_id="apply-once")
        assert out["view"]["status"] in ("awaiting_author", "stage_returned", "incomplete")
        assert len(patch_evidence(run_id, h)) == 1
        assert h.store(run_id).get_run(run_id)["observed_revision"] != revision
        scoped = [g for g in edit_grants(h, run_id)
                  if json.loads(g["scope_json"] or "[]") == [f"path:{solution['path']}"]]
        assert len(scoped) >= 1
        assert "APPROVED_CANARY" in h.artifact_text(
            run_id, h.artifacts(run_id, kind="solution")[-1])
        # A duplicate delivery of the same approval must not publish twice.
        h.chat.message(run_id, "Apply your proposed fix.", client_request_id="apply-once")
        assert len(patch_evidence(run_id, h)) == 1
    finally:
        h.close()


def test_r01_ambiguous_target_asks_and_grants_nothing():
    h = ChatHarness()
    try:
        _, run_id = settled(h)
        h.say(run_id, "```cpp\nint main(){ /* FIRST */ return 0; }\n```")
        h.say(run_id, "```cpp\nint main(){ /* SECOND */ return 0; }\n```")
        assert len(h.artifacts(run_id, kind="solution")) == 2
        inject_edit(h, h.artifacts(run_id, kind="solution")[-1]["path"])
        out = h.say(run_id, "apply your proposed fix")
        assert any(m["kind"] == "clarify" for m in agent_messages(out))
        assert not edit_grants(h, run_id)
        assert not patch_evidence(run_id, h)
    finally:
        h.close()


def test_r01_refusal_before_publication_fences_the_queued_edit():
    h = ChatHarness()
    try:
        _, run_id = settled(h)
        h.say(run_id, "```cpp\nint main(){ /* ORIGINAL_AUTHOR_CODE */ return 0; }\n```")
        solution = h.artifacts(run_id, kind="solution")[-1]
        original = h.artifact_text(run_id, solution)
        revision = h.store(run_id).get_run(run_id)["observed_revision"]
        inject_edit(h, solution["path"])
        h.service.failpoints.arm("editing.before_publish")
        h.say(run_id, "Apply your proposed fix.")
        assert not patch_evidence(run_id, h)
        assert h.store(run_id).get_run(run_id)["observed_revision"] == revision
        h.say(run_id, "Don't apply your proposed fix.")
        assert not patch_evidence(run_id, h)
        assert h.store(run_id).get_run(run_id)["observed_revision"] == revision
        assert h.artifact_text(run_id, h.artifacts(run_id, kind="solution")[-1]) == original
        assert "editing.before_publish" in h.service.failpoints.hits()
    finally:
        h.close()


def test_r01_published_history_survives_a_later_refusal():
    h = ChatHarness()
    try:
        _, run_id = settled(h)
        h.say(run_id, "```cpp\nint main(){ /* ORIGINAL */ return 0; }\n```")
        solution = h.artifacts(run_id, kind="solution")[-1]
        inject_edit(h, solution["path"], "// HISTORICAL_PATCH\n")
        h.say(run_id, "Apply your proposed fix.")
        assert len(patch_evidence(run_id, h)) == 1
        h.say(run_id, "Don't apply anything else.")
        assert len(patch_evidence(run_id, h)) == 1
        assert "HISTORICAL_PATCH" in h.artifact_text(
            run_id, h.artifacts(run_id, kind="solution")[-1])
    finally:
        h.close()


# ------------------------------------------------------------------ CN-R02
@pytest.mark.parametrize("text", [
    "Do not use closed intervals.",
    "Maybe closed intervals?",
    '"closed intervals"',
    "Use closed or half-open?",
    "We could use closed intervals.",
    "Is closed intervals better?",
])
def test_r02_uncertain_or_negated_answers_keep_the_barrier(text):
    h = ChatHarness()
    try:
        _, run_id = begin(h)
        out = h.say(run_id, text)
        assert out["view"]["pendingDecision"] is not None, text
        assert not out["view"]["collaboration"].get("decisions"), text
        assert not h.artifacts(run_id, kind="spec"), text
        assert any(m["kind"] in ("clarify", "explanation") for m in agent_messages(out))
    finally:
        h.close()


@pytest.mark.parametrize(("text", "option"), [
    ("Half-open; touching jobs are compatible.", "half_open"),
    ("closed: touching jobs conflict", "closed"),
])
def test_r02_clear_answer_commits_once_with_provenance(text, option):
    h = ChatHarness()
    try:
        _, run_id = begin(h)
        out = h.say(run_id, text)
        decisions = out["view"]["collaboration"]["decisions"]
        assert len(decisions) == 1 and decisions[0]["optionId"] == option
        assert decisions[0]["sourceId"].startswith("resp-")
        turn = [m for m in out["messages"] if m["role"] == "author"][-1]
        assert turn["interaction_id"] and turn["response_id"]
        assert out["view"]["pendingDecision"] is None
        before = len(decisions)
        out = h.say(run_id, text)
        assert len(out["view"]["collaboration"]["decisions"]) == before
    finally:
        h.close()


def test_r02_reload_does_not_repeat_a_settled_question():
    root = pathlib.Path(tempfile.mkdtemp(prefix="chat-repair-r02-"))
    first = ChatHarness(root=root)
    try:
        _, run_id = begin(first)
        first.say(run_id, "Half-open; touching jobs are compatible.")
        message_count = len(first.messages(run_id))
    finally:
        first.close()
    second = ChatHarness(root=root)
    try:
        transcript = second.chat.transcript(run_id)
        assert len(transcript["messages"]) == message_count
        out = second.say(run_id, "continue")
        assert out["view"]["pendingDecision"] is None
        assert len([m for m in out["messages"] if m["kind"] == "decision"]) == 1
        assert len(out["view"]["collaboration"]["decisions"]) == 1
    finally:
        second.close()


# ------------------------------------------------------------------ CN-R03
def test_r03_proof_question_routes_to_work_not_a_lemma():
    h = ChatHarness()
    try:
        _, run_id = settled(h)
        before = len(h.store(run_id).list_contributions(run_id))
        out = h.say(run_id, "Can you explain the proof?")
        assert len(h.store(run_id).list_contributions(run_id)) == before
        explanations = [m["text"] for m in agent_messages(out, "explanation")]
        assert any("PROOF_EXPLAIN" in text and "Can you explain the proof?" in text
                   for text in explanations)
        assert not any("Recorded your lemma" in m["text"] for m in agent_messages(out))
        compose_calls = [c for c in h.model.calls if c["node"] == "collaboration.compose"]
        assert compose_calls
        assert "Can you explain the proof?" in json.dumps(compose_calls[-1]["context"])
    finally:
        h.close()


def test_r03_construction_and_mixed_argument_critique():
    h = ChatHarness()
    try:
        _, run_id = settled(h)
        out = h.say(run_id, "Help me build the correctness proof for this approach.")
        explanations = [m["text"] for m in agent_messages(out, "explanation")]
        assert any("PROOF_WORK" in text for text in explanations)
        argument = ("Here is my argument: sorting by finish and taking the best compatible "
                    "prefix is optimal because exchange preserves reward. Can you check the "
                    "exchange step?")
        out = h.say(run_id, argument)
        contributions = h.store(run_id).list_contributions(run_id)
        assert contributions[-1]["kind"] == "lemma"
        assert contributions[-1]["attribution"] == "author"
        body = h.store(run_id).get_blob(contributions[-1]["original_blob_hash"]).decode()
        assert "sorting by finish" in body and "Can you check" not in body
        texts = [m["text"] for m in agent_messages(out, "explanation")]
        assert any("PROOF_WORK" in text and text not in explanations for text in texts)
    finally:
        h.close()


def test_r03_test_design_and_supplied_test_are_distinct():
    h = ChatHarness()
    try:
        _, run_id = settled(h)
        out = h.say(run_id, "Please generate edge cases and tests.")
        texts = [m["text"] for m in agent_messages(out, "explanation")]
        assert any("TEST_DESIGN" in text and "planned" in text for text in texts)
        assert not [a for a in h.artifacts(run_id, kind="test")
                    if "Please generate" in h.artifact_text(run_id, a)]
        supplied = "Here is a test I think fails: jobs (0,1,5) and (1,2,7) expected 12. Explain what it tells us."
        out = h.say(run_id, supplied)
        contribution = h.store(run_id).list_contributions(run_id)[-1]
        assert contribution["kind"] == "test"
        body = h.store(run_id).get_blob(contribution["original_blob_hash"]).decode()
        assert "jobs (0,1,5)" in body and "Explain what it tells us" not in body
        assert agent_messages(out, "explanation")
    finally:
        h.close()


def test_r03_unfamiliar_argument_remains_a_positive_control():
    h = ChatHarness()
    try:
        _, run_id = settled(h)
        argument = ("Here is my argument: if two jobs have equal reward, choosing the one "
                    "with the earlier finish cannot reduce the remaining feasible set. Can you "
                    "critique the exchange step?")
        out = h.say(run_id, argument)
        contributions = h.store(run_id).list_contributions(run_id)
        assert contributions[-1]["kind"] == "lemma"
        body = h.store(run_id).get_blob(contributions[-1]["original_blob_hash"]).decode()
        assert "equal reward" in body
        assert agent_messages(out, "explanation")
    finally:
        h.close()


# ------------------------------------------------------------------ CN-R04
LEMMA = ("Lemma: jobs [0,1) and [1,2) can both be selected because touching jobs are compatible.")
TEST = "Test case: jobs (0,1,5) and (1,2,7); expected total 12."


def test_r04_correction_invalidates_dependent_proof_test_and_plan():
    h = ChatHarness()
    try:
        _, run_id = settled(h)
        h.say(run_id, LEMMA)
        h.say(run_id, TEST)
        before = {a["kind"]: a for a in h.artifacts(run_id)
                  if a["kind"] in ("proof", "test", "test_plan")}
        assert set(before) == {"proof", "test", "test_plan"}
        assert all(a["current"] for a in before.values())
        contribution = h.store(run_id).list_contributions(run_id)[-1]
        original_test = h.store(run_id).get_blob(contribution["original_blob_hash"]).decode()

        out = h.say(run_id, "Correction: treat touching jobs as conflicting; use closed intervals.")
        all_artifacts = h.store(run_id).list_artifacts(run_id)
        old = [a for a in all_artifacts if a["kind"] in ("proof", "test", "test_plan")
               and not a["current"]]
        assert {a["kind"] for a in old} == {"proof", "test", "test_plan"}
        assert all(a["validity"] == "stale" for a in old)
        test_old = next(a for a in old if a["kind"] == "test")
        assert "12" in test_old["validity_reason"] and "7" in test_old["validity_reason"]
        current_plan = [a for a in h.artifacts(run_id, kind="test_plan")]
        assert current_plan and "conflict" in h.artifact_text(run_id, current_plan[-1])
        assert "compatible" not in h.artifact_text(run_id, current_plan[-1])
        # Source material is preserved, only its validity changed.
        assert h.store(run_id).get_blob(contribution["original_blob_hash"]).decode() == original_test
        assert contribution["attribution"] == "author"
        # The model context marks old material stale, not current fact.
        context = json.dumps(h.model.calls[-1]["context"])
        assert "closed" in context
        assert "stale" in context
        # Repeated projection must not reactivate stale bytes.
        h.chat._sync_artifacts(run_id)
        again = h.store(run_id).list_artifacts(run_id)
        assert all(not a["current"] for a in again
                   if a["id"] in {old_item["id"] for old_item in old})
        assert any(m["kind"] == "notice" and "stale" in m["text"] for m in out["messages"])
    finally:
        h.close()


def test_r04_corrected_expectation_becomes_current_support():
    h = ChatHarness()
    try:
        _, run_id = settled(h)
        h.say(run_id, LEMMA)
        h.say(run_id, TEST)
        h.say(run_id, "Correction: treat touching jobs as conflicting; use closed intervals.")
        out = h.say(run_id, "Corrected expectation: under closed intervals the expected total is 7.")
        tests = h.artifacts(run_id, kind="test")
        assert tests and "7" in h.artifact_text(run_id, tests[-1])
        assert tests[-1]["validity"] in ("current", "revalidated")
        assert any(m["kind"] == "artifact" and "test artifact" in m["text"]
                   for m in out["messages"])
        stale = [a for a in h.store(run_id).list_artifacts(run_id)
                 if a["kind"] == "test" and not a["current"]]
        assert stale and "12" in stale[-1]["validity_reason"]
    finally:
        h.close()


def test_r04_restart_preserves_validity_and_history():
    root = pathlib.Path(tempfile.mkdtemp(prefix="chat-repair-r04-"))
    first = ChatHarness(root=root)
    try:
        _, run_id = settled(first)
        first.say(run_id, LEMMA)
        first.say(run_id, TEST)
        first.say(run_id, "Correction: treat touching jobs as conflicting; use closed intervals.")
        before = [(a["id"], a["current"], a["validity"]) for a in
                  first.store(run_id).list_artifacts(run_id)]
    finally:
        first.close()
    second = ChatHarness(root=root)
    try:
        after = [(a["id"], a["current"], a["validity"]) for a in
                 second.store(run_id).list_artifacts(run_id)]
        assert after == before
        view = second.view(run_id)
        assert any(a["validity"] == "stale" for a in view["artifacts"])
        assert any(a["validity"] == "current" and a["kind"] == "test_plan"
                   for a in view["artifacts"])
        # A repeated sync after restart still does not revive stale proof/test.
        second.chat._sync_artifacts(run_id)
        latest = [(a["id"], a["current"], a["validity"]) for a in
                  second.store(run_id).list_artifacts(run_id)]
        assert latest == before
    finally:
        second.close()


# ------------------------------------------------------- decision layer unit
class RecordingDecisionAdapter:
    def __init__(self, decision: dict):
        self.decision = decision
        self.calls = 0
        self.identity = "recording-decision"
        self.version = "1"

    def call(self, text: str, context: dict):
        self.calls += 1
        from engine.decisions import AdapterResult
        return AdapterResult("ok", data=self.decision, model_identity=self.identity,
                             model_version=self.version)


def _service(h: ChatHarness, adapter) -> DecisionService:
    return DecisionService(h.store(h.chat.start("Help me develop profitable bookings.")["runId"]),
                           adapter)


def test_decision_service_replay_and_invented_targets():
    h = ChatHarness()
    try:
        started = h.start()
        run_id = started["runId"]
        adapter = RecordingDecisionAdapter({
            "acts": [{"kind": "effect_request", "polarity": "affirmative",
                      "target_refs": ["art-deadbeef"], "confidence": 1.0}],
            "unresolved_reason": None, "explanation": "",
        })
        service = DecisionService(h.store(run_id), adapter)
        message = h.store(run_id).append_chat_message(run_id, role="author",
                                                      kind="message", text="apply it")
        first = service.interpret(run_id, message["id"], "apply it")
        assert first["status"] == "unresolved"
        assert not first["acts"]
        assert first["rejected"]
        again = service.interpret(run_id, message["id"], "apply it")
        assert again["recordId"] == first["recordId"] and again["replay"] is True
        conflict = service.interpret(run_id, message["id"], "a different body")
        assert conflict["status"] == "conflict" and not conflict["acts"]
        assert adapter.calls == 1
    finally:
        h.close()


def test_decision_service_unavailable_and_malformed_are_inert():
    h = ChatHarness()
    try:
        run_id = h.start()["runId"]
        message = h.store(run_id).append_chat_message(run_id, role="author",
                                                      kind="message", text="apply the fix")
        unavailable = DecisionService(h.store(run_id), UnavailableDecisionAdapter())
        result = unavailable.interpret(run_id, message["id"], "apply the fix")
        assert result["status"] == "unavailable"
        assert not result["acts"]
        h.model._script["decision.interpret"] = [{"kind": "ok", "data": {"acts": "nonsense"}}]
        malformed_message = h.store(run_id).append_chat_message(
            run_id, role="author", kind="message", text="apply the fix again")
        malformed = DecisionService(h.store(run_id), ModelDecisionAdapter(h.model))
        result = malformed.interpret(run_id, malformed_message["id"], "apply the fix again")
        assert result["status"] == "malformed"
        assert not result["acts"]
        assert not patch_evidence(run_id, h)
    finally:
        h.close()


def test_decision_service_duplicate_id_with_different_body_conflicts():
    h = ChatHarness()
    try:
        out = h.start()
        run_id = out["runId"]
        h.chat.message(run_id, "Be brief.", client_request_id="same-id")
        before = len(h.messages(run_id))
        from engine.store import IdempotencyConflict
        with pytest.raises(IdempotencyConflict):
            h.chat.message(run_id, "Be detailed.", client_request_id="same-id")
        assert len(h.messages(run_id)) == before
    finally:
        h.close()


def test_chat_unavailable_decision_keeps_turn_inert():
    root = pathlib.Path(tempfile.mkdtemp(prefix="chat-repair-unavailable-"))
    service = EngineService(root, model_adapter=ConversationDemoModel(),
                            worker=FakeWorker(), fixture_dir=str(FIXTURES),
                            clone_models=False,
                            decision_adapter=UnavailableDecisionAdapter())
    chat = ChatService(service)
    try:
        started = chat.start("Help me develop profitable bookings; work with me, briefly.")
        run_id = started["runId"]
        before = len(chat.transcript(run_id)["messages"])
        out = chat.message(run_id, "Apply your proposed fix.")
        messages = chat.transcript(run_id)["messages"]
        assert len(messages) == before + 2  # author turn + recovery card
        assert any(m["kind"] == "recovery" and "Interpretation failed" in m["text"]
                   for m in messages[-2:])
        store = service.store(run_id)
        rows = store.read_all("SELECT operation_kinds_json FROM grants WHERE run_id=?", (run_id,))
        assert not [g for g in rows if "edit" in (g["operation_kinds_json"] or "")]
        assert not [e for e in store.list_evidence(run_id) if e["outcome"] == "patch"]
    finally:
        service.close()


def test_decision_service_stale_context_and_contradiction():
    h = ChatHarness()
    try:
        run_id = h.start()["runId"]
        corpus = {
            "acts": [{"kind": "effect_request", "polarity": "affirmative",
                      "target_refs": ["current_proposal"]}],
            "unresolved_reason": None, "explanation": "",
        }
        service = DecisionService(h.store(run_id), RecordingDecisionAdapter(corpus))
        h.store(run_id).update_run(run_id, goal_generation=1)
        stale = service.admit(run_id, "apply it", corpus,
                              {"revision": "rev-0", "generation": 0})
        current = h.store(run_id).get_run(run_id)["goal_generation"]
        # The current run has no concrete effect, so admission must be unresolved.
        assert stale["status"] == "unresolved"
        mixed = {
            "acts": [
                {"kind": "effect_request", "polarity": "affirmative",
                 "target_refs": ["current_proposal"]},
                {"kind": "restriction", "polarity": "negative"},
            ],
            "unresolved_reason": None, "explanation": "",
        }
        disposition = service.admit(run_id, "apply it, but don't", mixed,
                                    {"revision": "rev-0", "generation": current})
        assert not [a for a in disposition["acts"] if a["kind"] == "effect_request"]
    finally:
        h.close()


# ------------------------------------------------------- evaluation set
def test_decision_evaluation_set_has_no_false_effects_or_commits():
    path = ROOT / "qa" / "engine_contracts" / "decision_eval.json"
    evaluation = json.loads(path.read_text(encoding="utf-8"))
    assert evaluation["version"] == 1
    adapter = ScriptedDecisionAdapter()
    metrics = {"falseEffect": 0, "falseSemanticCommit": 0,
               "requestContributionConfusion": 0, "unnecessaryClarification": 0,
               "lostPositiveAction": 0, "cases": len(evaluation["cases"])}
    for case in evaluation["cases"]:
        context = {"pendingQuestion": case.get("pendingQuestion"),
                   "decisions": case.get("decisions") or []}
        decision = adapter.call(case["text"], context).data
        acts = decision["acts"]
        effect = [a for a in acts if a["kind"] == "effect_request"]
        semantic = [a for a in acts if a["kind"] == "semantic_assertion"
                    and a.get("semantic_option")]
        contributions = [a for a in acts if a["kind"] == "contribution"]
        if effect and not case.get("effectExpected"):
            metrics["falseEffect"] += 1
        if semantic and semantic[0].get("semantic_option") != case.get("semanticOption"):
            metrics["falseSemanticCommit"] += 1
        if contributions and case.get("contributionKind") not in (None, "any"):
            if contributions[0].get("contribution_kind") != case["contributionKind"]:
                metrics["requestContributionConfusion"] += 1
        if not acts and case.get("expectedAny"):
            metrics["unnecessaryClarification"] += 1
        for expected in case.get("expectedKinds") or []:
            if not any(a["kind"] == expected for a in acts):
                metrics["lostPositiveAction"] += 1
    assert metrics["falseEffect"] == 0
    assert metrics["falseSemanticCommit"] == 0
    assert metrics["requestContributionConfusion"] == 0
    assert metrics["lostPositiveAction"] == 0


# ------------------------------------------------------------------ HTTP
def _http_service(root: pathlib.Path, model=None) -> EngineService:
    return EngineService(
        root, model_adapter=model or ConversationDemoModel(), worker=FakeWorker(),
        fixture_dir=str(FIXTURES), clone_models=False,
    )


def test_repair_http_journeys():
    root = pathlib.Path(tempfile.mkdtemp(prefix="chat-repair-http-"))
    model = ConversationDemoModel()
    service = _http_service(root, model)
    server.ENGINE_SERVICE = service
    server.CHAT_SERVICE = None
    httpd = HTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=lambda: httpd.serve_forever(), daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_port}"

    def call(path, method="GET", body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"} if data else {}
        request = urllib.request.Request(base + path, data=data, method=method, headers=headers)
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    try:
        _, started = call("/api/engine/chat", "POST", {
            "message": "Help me develop profitable bookings; work with me, briefly."})
        run_id = started["runId"]
        _, answered = call(f"/api/engine/runs/{run_id}/messages", "POST", {
            "message": "Half-open; touching jobs are compatible."})
        assert answered["view"]["pendingDecision"] is None
        _, code = call(f"/api/engine/runs/{run_id}/messages", "POST", {
            "message": "```cpp\nint main(){ /* ORIGINAL */ return 0; }\n```"})
        solution = [a for a in code["view"]["artifacts"] if a["kind"] == "solution"][-1]
        revision = code["view"]["revision"]
        # Refusal and an effect question must not publish anything.
        for text in ("Don't apply your proposed fix.",
                     "Explain whether we should apply your proposed fix."):
            status, out = call(f"/api/engine/runs/{run_id}/messages", "POST", {"message": text})
            assert status == 200
            assert out["view"]["revision"] == revision
        _, view = call(f"/api/engine/runs/{run_id}/view")
        assert not [a for a in view["artifacts"] if a["kind"] == "solution" and
                    a["current"] and a["validity"] != "current"]
        # A clear approval publishes the demo repair once.
        _, approved = call(f"/api/engine/runs/{run_id}/messages", "POST", {
            "message": "Apply your proposed fix."})
        assert approved["view"]["revision"] != revision
        _, artifact = call(f"/api/engine/runs/{run_id}/artifacts/{solution['id']}")
        assert "ORIGINAL" in artifact["text"] or "demo repair" in artifact["text"]

        # CN-R02: tentative answer keeps the card; a clear answer settles once.
        _, second = call("/api/engine/chat", "POST", {
            "message": "Help me develop profitable talks."})
        rid = second["runId"]
        _, tentative = call(f"/api/engine/runs/{rid}/messages", "POST", {
            "message": "Maybe closed intervals?"})
        assert tentative["view"]["pendingDecision"] is not None
        _, clear = call(f"/api/engine/runs/{rid}/messages", "POST", {
            "message": "closed: touching jobs conflict"})
        assert clear["view"]["pendingDecision"] is None
        assert len(clear["view"]["collaboration"]["decisions"]) == 1

        # CN-R03: a proof question produces request-tied work, not a lemma.
        _, proof = call(f"/api/engine/runs/{run_id}/messages", "POST", {
            "message": "Can you explain the proof?"})
        assert any("PROOF_EXPLAIN" in m["text"] for m in proof["view"]["chatMessages"]
                   if m["kind"] == "explanation")
        _, transcript = call(f"/api/engine/runs/{run_id}/chat")
        assert not any("Recorded your lemma" in m["text"] for m in transcript["messages"])

        # CN-R04: old proof/test are stale, current plan uses the new semantics.
        _, r4 = call("/api/engine/chat", "POST", {
            "message": "Help me develop profitable bookings."})
        rid4 = r4["runId"]
        call(f"/api/engine/runs/{rid4}/messages", "POST",
             {"message": "Half-open; touching jobs are compatible."})
        call(f"/api/engine/runs/{rid4}/messages", "POST", {"message": LEMMA})
        call(f"/api/engine/runs/{rid4}/messages", "POST", {"message": TEST})
        call(f"/api/engine/runs/{rid4}/messages", "POST",
             {"message": "Correction: treat touching jobs as conflicting; use closed intervals."})
        _, r4view = call(f"/api/engine/runs/{rid4}/view")
        old = [a for a in r4view["artifacts"] if a["kind"] in ("proof", "test")
               and a["validity"] == "stale"]
        assert {a["kind"] for a in old} == {"proof", "test"}
        plan = [a for a in r4view["artifacts"] if a["kind"] == "test_plan" and a["current"]][-1]
        _, plan_body = call(f"/api/engine/runs/{rid4}/artifacts/{plan['id']}")
        assert "conflict" in plan_body["text"]
        _, old_test = call(f"/api/engine/runs/{rid4}/artifacts/{[a for a in old if a['kind'] == 'test'][0]['id']}")
        assert "expected total 12" in old_test["text"]
        assert old_test["validity"] == "stale"
    finally:
        httpd.shutdown()
        service.close()
        server.ENGINE_SERVICE = None
        server.CHAT_SERVICE = None