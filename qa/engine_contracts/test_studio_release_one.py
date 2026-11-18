"""Release 1 compatibility and recovery through the real local HTTP routes."""
from author_studio.packages import workspace
from engine.chat import ChatService
from engine.service import EngineService
from qa.engine_contracts.test_api_boundary import api


def start(call, key, title):
    status, result = call("/api/engine/chat", "POST", {
        "message": "Set a weighted interval scheduling problem with room bookings.",
        "clientRequestId": key, "title": title,
    })
    assert status == 201, result
    return result["runId"]


def preview(call, route, body):
    status, result = call(route, "POST", body)
    assert status == 200, result
    return result


def test_first_chat_has_durable_lookup_and_idempotent_retry(api):
    call = api["call"]
    lookup = "/api/engine/chat/receipt?requestId=first-release"
    assert call(lookup) == (200, {"accepted": False})
    run_id = start(call, "first-release", "Canal Relays")
    status, receipt = call(lookup)
    assert status == 200 and receipt["accepted"] and receipt["runId"] == run_id
    assert start(call, "first-release", "Canal Relays") == run_id
    assert call(lookup)[1]["messageId"] == receipt["messageId"]
    assert len(call("/api/engine/runs")[1]["runs"]) == 1
    reopened = EngineService(api["root"], demo=True)
    try:
        assert ChatService(reopened).receipt("first-release") == receipt
    finally:
        reopened.close()
    assert call("/api/engine/chat", "POST", {
        "message": "Another problem", "clientRequestId": "first-release", "title": "Different",
    })[0] == 409


def test_choice_receipt_belongs_to_the_selected_card(api):
    call = api["call"]
    run_id = start(call, "question-start", "Intervals")
    root = f"/api/engine/runs/{run_id}"
    card = call(root + "/view")[1]["pendingDecision"]
    assert card
    choice = {"message": "Half-open: touching jobs are compatible", "clientRequestId": "choose-first",
              "expectedInteractionId": card["id"]}
    assert call(root + "/messages", "POST", choice)[0] == 200
    lookup = f"/api/engine/chat/receipt?requestId=choose-first&runId={run_id}"
    receipt = call(lookup)[1]
    assert receipt["accepted"] and receipt["choiceApplied"]
    assert call(root + "/messages", "POST", choice)[0] == 200
    assert call(lookup)[1] == receipt
    assert call(root + "/messages", "POST", {**choice, "clientRequestId": "already-closed"})[0] == 409
    assert call(f"/api/engine/chat/receipt?requestId=already-closed&runId={run_id}") == (200, {"accepted": False})


def test_link_keeps_import_bytes_until_explicit_title_match(api, monkeypatch, tmp_path):
    monkeypatch.setattr(workspace, "WORKSPACES", tmp_path / "packages")
    call = api["call"]
    run_id = start(call, "name-scope", "Canal & Relays")
    root = f"/api/engine/runs/{run_id}"
    slug = workspace.create("Imported Title")["slug"]
    workspace.write_text(slug, "problem_statement/problem.en.tex", "\\documentclass{article}\n")
    snapshot = workspace.snapshot_hash(slug)
    link = preview(call, root + "/studio-package-preview", {"slug": slug})
    assert link["packageTitle"] == "Imported Title" and link["filename"] == "canal-relays-domjudge.zip"
    assert not link["statementSupported"]
    body = {"slug": slug, "syncTitle": False, **link["basis"]}
    assert call(root + "/studio-package", "POST", body) == (201, {"slug": slug, "syncTitle": False})
    assert workspace.snapshot_hash(slug) == snapshot
    separate = preview(call, root + "/title-preview", {"title": "New “Canal”"})
    assert separate["separate"]
    assert call(root + "/title", "POST", {"title": "New “Canal”", **separate["basis"]})[0] == 200
    assert workspace.snapshot_hash(slug) == snapshot
    assert call(root + "/studio-package", "POST", body)[0] == 409
    newer = preview(call, root + "/studio-package-preview", {"slug": slug})
    assert call(root + "/studio-package", "POST", {"slug": slug, "syncTitle": True, **newer["basis"]})[0] == 201
    assert workspace.state(slug)["meta"]["name"] == "New “Canal”"
    assert workspace.export_filename(slug) == newer["filename"]
    assert workspace.snapshot_hash(slug) != snapshot


def test_preview_conflict_and_same_title_noop(api, monkeypatch, tmp_path):
    monkeypatch.setattr(workspace, "WORKSPACES", tmp_path / "packages")
    call = api["call"]
    run_id = start(call, "create-with-title", None)
    root = f"/api/engine/runs/{run_id}"
    draft = preview(call, root + "/studio-package-preview", {"slug": None})
    status, result = call(root + "/studio-package", "POST", {
        "name": "Initial Name", "syncTitle": True, **draft["basis"],
    })
    assert status == 201
    slug = result["slug"]
    assert call(root + "/view")[1]["title"] == "Initial Name"
    first = preview(call, root + "/title-preview", {"title": "First change"})
    second = preview(call, root + "/title-preview", {"title": "Second change"})
    assert first["basis"] == second["basis"]
    assert call(root + "/title", "POST", {"title": "First change", **first["basis"]})[0] == 200
    status, conflict = call(root + "/title", "POST", {"title": "Second change", **second["basis"]})
    assert status == 409 and "First change" in conflict["error"]
    snapshot, changes = workspace.snapshot_hash(slug), workspace.changes(slug)
    same = preview(call, root + "/title-preview", {"title": "First change"})
    assert call(root + "/title", "POST", {"title": "First change", **same["basis"]})[0] == 200
    assert workspace.snapshot_hash(slug) == snapshot and workspace.changes(slug) == changes
