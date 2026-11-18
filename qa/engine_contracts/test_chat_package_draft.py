import pytest

from engine.store import LedgerError, PublicationBlocked
from engine.domain import oracle_subset, parse_instance
from engine.worker import IsolateWorker
from qa.engine_contracts.harness import FIXTURES, Harness, plan, script
from qa.engine_contracts.test_chat_native import ChatHarness


IDEA = "Find the maximum reward from compatible half-open booking intervals."
REQUEST = "Generate the C++ reference and concrete test cases for a complete judging package."


def test_live_structured_candidate_reference_and_targeted_inputs(tmp_path):
    h = Harness(root=tmp_path, script=script(plan=[plan("finish")]))
    try:
        rid = h.create(IDEA)
        h.pump(rid)
        store = h.store(rid)
        source = (FIXTURES / "dp_correct.cpp").read_bytes()
        digest = store.put_blob(source)
        rev = store.get_run(rid)["observed_revision"]
        contribution = store.add_contribution(rid, source_input_id=None, actor_kind="author",
                                              actor_id="local", kind="code", blob_hash=digest,
                                              revision=rev)
        ref = {"artifact_id": contribution["id"], "sha256": digest, "revision": rev,
               "role": "author contribution, untrusted data, unvalidated"}
        h.model._script["plan"].extend([plan("investigate", args={
            "candidate_ref": ref, "domain": {"description": "prose only"},
            "targeted_cases": [{"input": "2\n1 2 5\n2 3 7\n", "expected": 7},
                               {"input": "1\n0 1 9\n", "expected": 0}],
        }, requested_budget={"cases": 2}), plan("finish")])
        h.service.submit_input(rid, {"kind": "steer", "text": "Investigate my reference.",
                                     "clientRequestId": "investigate"}, schedule=False)
        h.pump(rid)
        assert len(h.worker.jobs) == 1
        assert h.worker.jobs[0]["candidate"]["source"] == source.decode()
        assert [c["input"] for c in h.worker.jobs[0]["cases"]] == ["2\n1 2 5\n2 3 7\n", "1\n0 1 9\n"]
        evidence = store.list_evidence(rid)[0]
        assert evidence["dependency_hashes"]["candidate"] == "contribution:" + contribution["id"]
        assert evidence["classification"] != "counterexample"
        runtime = h.service.runtime(rid)
        for incorrect in ({**ref, "sha256": "0" * 64}, {**ref, "revision": "wrong-revision"},
                          {"artifact_id": "../code.cpp"}, "fixture:../dp_correct"):
            with pytest.raises(LedgerError):
                runtime.candidate_source(rid, incorrect)
    finally:
        h.close()


def _draft():
    return {"kind": "ok", "data": {
        "title": "Canary Berths", "story": "The canary harbour has one quay.",
        "solution_cpp": "int main() { return 0; } // solution-canary",
        "wrong_answer_cpp": "int main() { return 1; } // baseline-canary",
        "editorial": "Sort by finish and justify both branches of the recurrence.",
        "tests": [{"group": "sample", "input": "1\n0 1 9\n", "purpose": "single"},
                  {"group": "secret", "input": "2\n1 2 5\n2 3 7\n", "purpose": "touching"},
                  {"group": "secret", "input": "2\n0 2 6\n0 4 13\n", "purpose": "reward"}],
    }}


@pytest.mark.parametrize("mode", ["valid", "invalid", "repair"])
def test_chat_draft_publishes_model_bytes_with_independent_answers(tmp_path, mode):
    response = _draft()
    invalid = _draft()
    invalid["data"]["tests"][2]["input"] = invalid["data"]["tests"][1]["input"]
    drafts = {"valid": [response], "invalid": [invalid] * 3, "repair": [invalid, response]}
    h = ChatHarness(root=tmp_path, script_dict={**script(plan=[plan("finish"), plan(
        "collaborate", args={"procedure": "COL-PACKAGE"})]), "collaboration.package_draft": drafts[mode]})
    try:
        rid = h.chat.start(IDEA, title="Author's Berths & Schedules")["runId"]
        result = h.chat.message(rid, REQUEST, client_request_id="draft")
        generated = [a for a in h.artifacts(rid) if a["provenance"].get("packageDraft")]
        if mode == "invalid":
            assert not generated
            assert h.store(rid).get_run(rid)["stop_reason"] == "invalid_package_draft"
            return
        paths = {a["path"]: a for a in generated}
        statement = paths["problem_statement/problem.en.tex"]
        assert r"\newcommand{\problemname}{Author's Berths \& Schedules}" in h.artifact_text(rid, statement)
        reference = paths["submissions/accepted/reference.cpp"]
        assert h.artifact_text(rid, reference).rstrip() == response["data"]["solution_cpp"]
        h.service.rename_run(rid, "New {Berths}")
        updated = next(a for a in h.artifacts(rid) if a["id"] != statement["id"] and a["kind"] == "statement")
        assert r"\newcommand{\problemname}{New \{Berths\}}" in h.artifact_text(rid, updated)
        assert h.messages(rid)[-1]["artifact_ids"] == [updated["id"]]
        h.service.rename_run(rid, "Author's Berths & Schedules")
        restored = next(a for a in h.artifacts(rid) if a["kind"] == "statement")
        assert h.artifact_text(rid, restored) == h.artifact_text(rid, statement)
        touching = paths["data/secret/01.in"]
        assert touching["provenance"]["oracleExpected"] == 12
        assert paths["input_validators/validate.py"]["provenance"]["authorKind"] == "host"
        assert any(reference["id"] in m["artifact_ids"] for m in result["messages"])
        assert not h.h.worker.jobs
        h.chat.message(rid, REQUEST, client_request_id="draft")
        assert len([call for call in h.model.calls if call["node"] == "collaboration.package_draft"]) == (
            2 if mode == "repair" else 1
        )
        store = h.store(rid)
        run = store.get_run(rid)
        with pytest.raises(PublicationBlocked, match="conversation changed"):
            store.publish_package_draft(
                rid, [{"kind": "solution", "path": reference["path"], "text": "late result"}],
                context={"revision": run["observed_revision"], "goal_generation": run["goal_generation"] + 1},
                source_turn=reference["source_turn"], action_id="late", model="test",
                endpoint_decision={"id": "decision"},
            )
        assert h.artifact_text(rid, reference).rstrip() == response["data"]["solution_cpp"]
    finally:
        h.close()


@pytest.mark.parametrize("mode", ["repair", "worker_failure", "unchanged", "declined", "budget"])
def test_automatic_oracle_checks_through_chat(tmp_path, monkeypatch, mode):
    import isolate_client

    calls = []
    def run(source, language, stdin, **limits):
        calls.append((source, stdin))
        if mode == "worker_failure":
            raise OSError("worker offline")
        fixed = "corrected-canary" in source
        expected = oracle_subset(parse_instance(stdin), semantics="half_open" if fixed else "closed")["value"]
        return {"status": "OK", "exit": 0, "stdout": str(expected)}

    monkeypatch.setattr(isolate_client, "configured", lambda: True)
    monkeypatch.setattr(isolate_client, "run", run)
    monkeypatch.setattr(isolate_client, "health", lambda: {"service": "offline test"})
    fixed = "int main() { return 0; } // corrected-canary"
    initial = _draft()
    repair = initial["data"]["solution_cpp"] if mode == "unchanged" else fixed
    h = ChatHarness(root=tmp_path, worker=IsolateWorker(), script_dict={
        **script(plan=[plan("finish"), plan("collaborate", args={"procedure": "COL-PACKAGE"})]),
        "collaboration.package_draft": [initial],
        "collaboration.package_repair": [{"kind": "ok", "data": {"solution_cpp": repair}}],
    })
    try:
        rid = h.start(IDEA)["runId"]
        if mode == "budget":
            with h.store(rid).tx() as conn:
                conn.execute("UPDATE budgets SET cases_limit=6 WHERE run_id=?", (rid,))
        text = REQUEST + (" Do not run the solution." if mode == "declined" else "")
        result = h.chat.message(rid, text, client_request_id="check")
        store = h.store(rid)
        repairs = [call for call in h.model.calls if call["node"] == "collaboration.package_repair"]
        artifacts = [a for a in h.artifacts(rid) if a["provenance"].get("packageDraft")]
        if mode == "repair":
            assert len(repairs) == 1 and len(calls) == 14
            assert [stdin for _, stdin in calls[:7]] == [stdin for _, stdin in calls[7:]]
            failure = repairs[0]["context"]["failedCheck"]
            assert (failure["case_id"], failure["expected"], failure["actual"]) == ("oracle:touching", 12, "7")
            candidate = next(a for a in artifacts if a["kind"] == "solution")
            assert h.artifact_text(rid, candidate).rstrip() == fixed
            assert candidate["provenance"]["packageCheck"]["repairs"] == 1
            evidence = next(e for e in store.list_evidence(rid) if e["domain"] == "package_reference")
            assert evidence["dependency_hashes"]["candidate"] == candidate["blob_hash"]
            assert evidence["usage_observed"]["complete"]
            assert any("independent oracle expected 12" in m["text"] for m in result["messages"])
            assert any("passed 7 isolated oracle checks" in m["text"] for m in result["messages"])
            assert sum(m["role"] == "author" for m in result["messages"]) == 2
            h.chat.message(rid, text, client_request_id="check")
            assert len(calls) == 14
            assert store.get_budget(rid)["cases_used"] == 14
        elif mode == "declined":
            assert artifacts and not calls and not repairs
            assert all("packageCheck" not in a["provenance"] for a in artifacts)
        else:
            assert not artifacts
            stop = {"worker_failure": "package_check_infrastructure_error", "unchanged": "reference_repair_unchanged",
                    "budget": "case_budget_exhausted"}[mode]
            assert store.get_run(rid)["stop_reason"] == stop
            assert len(repairs) == (1 if mode == "unchanged" else 0)
            if mode == "budget":
                assert not calls and store.get_budget(rid)["cases_used"] == 0
    finally:
        h.close()
