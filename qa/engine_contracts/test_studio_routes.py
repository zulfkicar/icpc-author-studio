"""Author Studio uses the real package API and preserves verification gates."""
import io
import json
import time
import urllib.error
import urllib.request
import zipfile

from author_studio.classic import agent
from author_studio import mcp_server
from author_studio.packages import workspace
from qa.engine_contracts.test_api_boundary import api, create_run


def finish(call, started):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        status, job = call("/api/jobs/" + started["id"])
        assert status == 200
        if job["state"] != "running":
            return job
        time.sleep(0.1)
    raise AssertionError("Package job did not finish")


def test_studio_package_workflow(api, tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "WORKSPACES", tmp_path / "workspaces")
    call = api["call"]
    run_id = create_run(api)
    link = f"/api/engine/runs/{run_id}/studio-package"
    status, data = call(link, "POST", {"name": "Studio Sum", "expectedSlug": None})
    assert status == 201
    slug = data["slug"]
    assert call(link) == (200, {"slug": slug})
    assert call(link, "POST", {"name": "Duplicate", "expectedSlug": None})[0] == 400
    assert len(workspace.list_workspaces()) == 1
    base = f"/api/workspaces/{slug}"

    def save(path, content, expected=None):
        return call(base + "/file", "POST", {"path": path, "content": content, "expectedHash": expected})

    def job(operation, **params):
        status, info = call(base + "/studio")
        assert status == 200
        status, started = call(base + "/" + operation, "POST", {"expectedSnapshot": info["snapshot"], **params})
        assert status == 200
        return finish(call, started)

    files = {
        "problem.yaml": "name: Studio Sum\ntype: pass-fail\nlimits:\n  memory: 256\n",
        "domjudge-problem.ini": "name = Studio Sum\ntimelimit = 1\nshort-name = QS\n",
        "data/sample/01.in": "2 3\n",
        "data/secret/01.in": "4 5\n",
        "submissions/wrong_answer/wrong.py": "a,b=map(int,input().split());print(a-b)\n",
        "input_validators/validate.py": "import sys\na,b=map(int,sys.stdin.read().split());sys.exit(42)\n",
        "problem_statement/problem.en.tex": "\\documentclass{article}\n\\begin{document}\nPrint the sum.\n\\end{document}\n",
    }
    for path, text in files.items():
        workspace.write_text(slug, path, text, source="test")
    reference = "submissions/accepted/sum.py"
    status, saved = save(reference, "a,b=map(int,input().split());print(a+b)\n")
    assert status == 200 and saved["hash"]
    assert save(reference, "print(0)\n")[0] == 409
    assert job("run", path=reference, stdin="5 7", asJob=True)["result"]["stdout"].strip() == "12"
    assert job("answers")["result"]["written"] == 2
    workspace.set_limits(slug, 1.0, 256, {"measuredAt": "test", "slowestTest": "data/sample/01.in"})
    result = job("verify", writeAnswers=False)["result"]
    assert result["status"] == "verified", result["errors"]
    assert call(base + "/studio")[1]["workflow"]["nextAction"] == "review"
    assert job("export")["state"] == "error"
    assert call(base + "/review", "POST", {"expectedSnapshot": result["snapshot"]})[0] == 200
    exported = job("export")["result"]
    assert exported["snapshot"] == result["snapshot"]
    download = api["base"] + base + "/download?snapshot=" + result["snapshot"]
    with urllib.request.urlopen(download, timeout=10) as response:
        assert response.headers["Content-Type"] == "application/zip"
        with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
            assert archive.read("data/secret/01.ans").strip() == b"9"
            assert json.loads(archive.read("problem_statement/manifest.json"))["snapshot"] == result["snapshot"]
    assert call(base + "/studio")[1]["archive"]["status"] == "ready"
    local_statement = workspace.ws_path(slug) / "problem_statement/problem.en.tex"
    with local_statement.open("a", encoding="utf-8") as statement:
        statement.write("\n% Out-of-band author edit\n")
    info = call(base + "/studio")[1]
    assert info["workflow"]["phase"] == "verification_stale"
    assert info["unreviewed"] == 0
    assert call(base + "/download")[0] == 409
    latest = job("verify", writeAnswers=False)["result"]
    assert latest["status"] == "verified"
    info = call(base + "/studio")[1]
    workflow = info["workflow"]
    assert workflow["phase"] == "review_required" and workflow["unreviewedChanges"] == 0
    assert agent._dispatch(slug, "report_summary", {}, lambda *_: None)["workflow"] == workflow
    consent = {"enabled": True, "tools": {"read_report": True}}
    assert mcp_server.call(slug, "read_report", {}, consent)["workflow"] == workflow
    assert call(base + "/review", "POST", {"expectedSnapshot": result["snapshot"]})[0] == 409
    assert call(base + "/review", "POST", {"expectedSnapshot": latest["snapshot"]})[0] == 200
    assert call(base + "/studio")[1]["archive"]["status"] == "stale"
    assert call(base + "/download")[0] == 409
    assert job("export")["result"]["snapshot"] == latest["snapshot"]
    assert call(base + "/studio")[1]["archive"]["status"] == "ready"
    assert save("editorial/change.md", "# Updated\n")[0] == 200
    assert call(base + "/studio")[1]["lastStatus"] == "stale"
    try:
        urllib.request.urlopen(download, timeout=10)
    except urllib.error.HTTPError as error:
        assert error.code == 409
    else:
        raise AssertionError("An outdated package was downloadable")


def test_editor_format_and_check_use_the_submitted_draft(api):
    call = api["call"]
    route = "/api/studio/editor-tool"
    original = '{"x": 1e900, "x": "  keep  ", "y": [true, null]}'
    status, result = call(route, "POST", {"path": "settings.json", "operation": "format", "content": original})
    assert status == 200
    assert '1e900' in result["content"] and result["content"].count('"x"') == 2
    assert '"  keep  "' in result["content"]
    status, result = call(route, "POST", {"path": "settings.json", "operation": "check", "content": '{"x": }'})
    assert status == 200 and result["diagnostics"][0]["severity"] == "error"
