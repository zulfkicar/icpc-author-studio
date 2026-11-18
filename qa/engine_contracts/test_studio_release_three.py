"""Saved evidence, replay and human-approved export over the actual HTTP routes."""
import io
import json
import sqlite3
import threading
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest

from author_studio.packages import workspace
from engine.domain import render_instance, witness_weighted_greedy
from qa.engine_contracts.test_api_boundary import api, wait_for
from qa.engine_contracts.test_studio_release_one import start
from qa.engine_contracts.test_studio_routes import finish


CASE = render_instance(witness_weighted_greedy())
SOURCE = "submissions/accepted/reference.py"
SAMPLE = "data/sample/01.in"
SECRET = "data/secret/weighted.in"
GREEDY = '''import sys
_, *rows = sys.stdin.read().splitlines()
total, finish = 0, -1
for a, b, w in sorted((tuple(map(int, line.split())) for line in rows), key=lambda j: (j[1], j[0])):
    if a >= finish:
        total, finish = total + w, b
print(total)
'''
REFERENCE = '''from bisect import bisect_right
import sys
_, *rows = sys.stdin.read().splitlines()
jobs = sorted((tuple(map(int, line.split())) for line in rows), key=lambda j: j[1])
ends = [job[1] for job in jobs]
dp = [0]
for i, (a, _, w) in enumerate(jobs):
    dp.append(max(dp[-1], w + dp[bisect_right(ends, a, 0, i)]))
print(dp[-1])
'''


def test_counterexample_to_reviewed_zip_with_outside_edit(api, monkeypatch, tmp_path):
    monkeypatch.setattr(workspace, "WORKSPACES", tmp_path / "packages")
    call = api["call"]
    run_id = start(call, "r3-idea", "Interval Evidence")
    run = f"/api/engine/runs/{run_id}"
    card = wait_for(call, run_id, lambda v: v.get("pendingDecision"))["pendingDecision"]
    assert call(run + "/messages", "POST", {
        "message": "Half-open: touching jobs are compatible", "clientRequestId": "r3-semantics",
        "expectedInteractionId": card["id"],
    })[0] == 200
    view = wait_for(call, run_id, lambda v: v.get("evidenceCards"))
    witness = next(item for item in view["evidenceCards"].values() if item["input"] == CASE)
    assert witness["legal"] and witness["expected"] == 13 and witness["actual"] == 12
    assert "simulation" in witness["worker"] and witness["claim"] == "H1"
    assert view["collaboration"]["decisions"][-1]["optionId"] == "half_open"

    status, linked = call(run + "/studio-package", "POST", {"name": "Interval Evidence", "expectedSlug": None})
    assert status == 201, linked
    slug = linked["slug"]
    base = f"/api/workspaces/{slug}"
    for path, text in {
        "problem.yaml": "name: Interval Evidence\ntype: pass-fail\nlimits:\n  memory: 256\n",
        "domjudge-problem.ini": "name = Interval Evidence\ntimelimit = 1\nshort-name = IE\n",
        "problem_statement/problem.en.tex": "\\documentclass{article}\n\\begin{document}\nMaximize reward.\n\\end{document}\n",
        "input_validators/validate.py": "import sys\nn,*values=map(int,sys.stdin.read().split());sys.exit(42 if len(values)==3*n else 1)\n",
        SOURCE: GREEDY, "submissions/wrong_answer/greedy.py": GREEDY,
        SAMPLE: "1\n0 2 6\n", SECRET: CASE,
    }.items():
        workspace.write_text(slug, path, text, source="test")

    def info():
        return call(base + "/studio")[1]

    def job(op, **body):
        status, started = call(base + "/" + op, "POST", {"expectedSnapshot": info()["snapshot"], **body})
        assert status == 200, started
        return finish(call, started)

    def save(path, content, origin=None):
        _, old = call(base + f"/file?path={path}")
        return call(base + "/file", "POST", {"path": path, "content": content,
                                              "expectedHash": old.get("hash"), "artifactOrigin": origin})

    first = job("run", asJob=True, path=SOURCE, stdin=CASE, expected="13")["result"]
    assert first["stdout"].strip() == "12" and not first["comparison"]["matches"]
    assert first["evidenceSource"] == "local process" and first["comparison"]["source"] == "attached expectation"
    assert save(SOURCE, "def :\n")[0] == 200
    assert job("run", asJob=True, path=SOURCE, stdin=CASE, expectedHash=first["sourceHash"])["state"] == "error"
    error = job("run", asJob=True, path=SOURCE, stdin=CASE)["result"]
    assert error["diagnostics"] == [{"path": SOURCE, "line": 1, "column": 1}]
    assert error["sourceHash"] != first["sourceHash"]
    status, saved = save(SOURCE, REFERENCE)
    assert status == 200
    repaired = job("run", asJob=True, path=SOURCE, stdin=CASE, expected="13", expectedHash=saved["hash"])["result"]
    assert repaired["comparison"]["matches"] and repaired["stdout"].strip() == "13"

    plan = call(base + "/answer-plan")[1]
    assert plan["counts"] == {"sample": 1, "secret": 1} and plan["references"] == [SOURCE]
    assert [row["answer"] for row in plan["outputs"]] == ["data/sample/01.ans", "data/secret/weighted.ans"]
    assert job("answers")["result"]["written"] == 2
    assert job("run", asJob=True, path=SOURCE, casePath=SECRET, stdin="different")["state"] == "error"
    assert job("run", asJob=True, path=SOURCE, casePath=SECRET, stdin=CASE)["result"]["comparison"]["source"] == "stored answer"
    workspace.set_limits(slug, 1.0, 256, {"measuredAt": "test", "slowestTest": SECRET})
    answer = "data/secret/weighted.ans"
    assert save(answer, "12\n")[0] == 200
    failed = job("verify", writeAnswers=False)["result"]
    assert failed["status"] == "failed"
    mismatch = next(row for row in failed["tests"] if row["path"] == SECRET)
    assert mismatch["expectedAnswer"]["references"] == []
    assert mismatch["solutions"][0]["verdict"] == "WA"
    assert mismatch["solutions"][0]["actualPreview"].strip() == "13"
    assert mismatch["solutions"][0]["expectedPreview"].strip() == "12"
    assert job("answers")["result"]["written"] == 2

    verified = job("verify", writeAnswers=False)["result"]
    assert verified["status"] == "verified", verified["errors"]
    assert verified["negative"][0]["secretKill"]
    row = next(row for row in verified["tests"] if row["path"] == SECRET)
    assert row["validatorPassed"] and row["solutions"][0]["verdict"] == "AC"
    assert row["expectedAnswer"]["references"] == [SOURCE] and row["expectedAnswer"]["inputMatchesBuild"]
    snapshot = verified["snapshot"]
    assert job("export")["state"] == "error"
    assert call(base + "/studio-review")[1]["baseline"] is None
    assert call(base + "/review", "POST", {"expectedSnapshot": snapshot})[0] == 200
    assert job("export")["result"]["snapshot"] == snapshot
    with urllib.request.urlopen(api["base"] + base + "/download?snapshot=" + snapshot, timeout=8) as response:
        with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
            assert archive.testzip() is None
            assert archive.read("data/secret/weighted.ans").strip() == b"13"
            manifest = json.loads(archive.read("problem_statement/manifest.json"))
            assert manifest["snapshot"] == snapshot and manifest["createdAt"]

    note = workspace.ws_path(slug) / "problem_statement/problem.en.tex"
    with note.open("a", encoding="utf-8") as handle:
        handle.write("\n% A meaningful edit outside Author Studio\n")
    changed = info()
    assert changed["archive"]["status"] == "stale" and changed["archive"]["snapshot"] == snapshot
    assert call(base + "/download")[0] == call(base + "/download?snapshot=" + snapshot)[0] == 409
    assert call(base + "/review", "POST", {"expectedSnapshot": snapshot})[0] == 409
    report = call(base + "/studio-review")[1]
    assert report["baseline"] == snapshot
    assert {"path": "problem_statement/problem.en.tex", "source": "outside change or unrecorded source",
            "kind": "modified"} in report["files"]
    comparison = call(base + "/studio-review?path=problem_statement/problem.en.tex")[1]
    assert comparison["hasDiff"] and "+% A meaningful edit outside Author Studio" in comparison["diff"]

    for key, message, option in (
        ("correct-closed", "Correction: treat touching jobs as conflicting; use closed intervals.", "closed"),
        ("return-half-open", "Correction: use half-open intervals; touching jobs are compatible.", "half_open"),
    ):
        assert call(run + "/messages", "POST", {"message": message, "clientRequestId": key})[0] == 200
        updated = wait_for(call, run_id, lambda value: value["collaboration"]["decisions"][-1]["optionId"] == option)
        assert updated["collaboration"]["decisions"][-1]["sourceId"]


def test_artifact_source_revision_and_destination_hash_both_gate_save(api, monkeypatch, tmp_path):
    monkeypatch.setattr(workspace, "WORKSPACES", tmp_path / "packages")
    call = api["call"]
    run_id = start(call, "artifact-r3", "Draft origin")
    store = api["service"].store(run_id)
    run = f"/api/engine/runs/{run_id}"
    card = wait_for(call, run_id, lambda v: v.get("pendingDecision"))["pendingDecision"]
    assert call(run + "/messages", "POST", {"message": "Half-open: touching jobs are compatible",
        "clientRequestId": "artifact-r3-answer", "expectedInteractionId": card["id"]})[0] == 200
    view = wait_for(call, run_id, lambda v: any(a["current"] for a in v["artifacts"]))
    artifact = next(a for a in view["artifacts"] if a["current"])
    slug = workspace.create("Artifact copy destination")["slug"]
    route = f"/api/workspaces/{slug}/file"
    origin = {"runId": run_id, "artifactId": artifact["id"], "revision": artifact["revision"]}
    request = {"path": "editorial/copied.md", "content": "An edited draft\n", "expectedHash": None, "artifactOrigin": origin}
    assert call(route, "POST", {**request, "artifactOrigin": {**origin, "revision": "wrong"}})[0] == 409
    status, copied = call(route, "POST", request)
    assert status == 200 and copied["change"]["artifactOrigin"] == origin
    assert call(route, "POST", request)[0] == 409
    store.set_artifact_validity(artifact["id"], "stale", reason="new semantics")
    assert call(route, "POST", {**request, "path": "editorial/stale.md"})[0] == 409
    assert call(route + "?path=editorial/stale.md")[0] == 404


def test_owner_defers_checkpoint_close_until_active_graph_returns(api, monkeypatch):
    run_id = start(api["call"], "owner-shutdown", "Continue safely")
    service = api["service"]
    owner = service._owners.owner(service.runtime(run_id), run_id)
    entered = threading.Event()
    resume = threading.Event()
    read_checkpoint = owner.graph.get_state

    def paused_read(config):
        entered.set()
        assert resume.wait(10)
        return read_checkpoint(config)

    monkeypatch.setattr(owner.graph, "get_state", paused_read)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pumped = executor.submit(service.pump_sync, run_id)
        try:
            assert entered.wait(10)
            owner.close()
            assert owner._lock.held
            assert owner.pump(run_id)["status"] == "closed"
        finally:
            resume.set()
        assert pumped.result(timeout=10)["status"] in {"waiting", "idle", "done"}
    assert not owner._lock.held
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        owner._conn.execute("select 1")
