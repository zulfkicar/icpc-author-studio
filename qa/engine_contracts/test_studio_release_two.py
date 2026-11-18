"""Release 2 uses a bounded workspace PDF response and a separate page preview."""
from subprocess import CompletedProcess
import urllib.parse
import urllib.request

import server
import workspace
from qa.engine_contracts.test_api_boundary import api


def test_statement_preview_is_scoped_and_inline(api, monkeypatch, tmp_path):
    monkeypatch.setattr(workspace, "WORKSPACES", tmp_path / "packages")
    slug = workspace.create("Preview fixture")["slug"]
    root = workspace.ws_path(slug)
    pdf = b"%PDF-1.4\n% fixture bytes\n%%EOF\n"
    (root / "problem.pdf").write_bytes(pdf)
    (root / "private.pdf").write_bytes(pdf)
    route = api["base"] + "/api/workspaces/" + slug + "/statement-pdf"
    with urllib.request.urlopen(route + "?path=problem.pdf", timeout=10) as result:
        assert result.read() == pdf
        assert result.headers["Content-Type"] == "application/pdf"
        assert result.headers["Content-Disposition"].startswith("inline")
        assert result.headers["X-Frame-Options"] == "DENY"
    with urllib.request.urlopen(api["base"] + "/", timeout=10) as result:
        assert result.headers["X-Frame-Options"] == "DENY"

    for path, status in (("private.pdf", 404), ("problem_statement/problem.en.pdf", 404)):
        query = urllib.parse.urlencode({"path": path})
        assert api["call"]("/api/workspaces/" + slug + "/statement-pdf?" + query)[0] == status
    monkeypatch.setattr(server.shutil, "which", lambda _name: None)
    assert api["call"]("/api/workspaces/" + slug + "/statement-pdf?path=problem.pdf&preview=first-page")[0] == 503
    png = b"\x89PNG\r\n\x1a\n" + b"page fixture"

    def render(args, *, input, capture_output, timeout, check):
        assert args == ["pdftocairo", "-png", "-singlefile", "-f", "1", "-l", "1",
                        "-scale-to", "1400", "-", "-"]
        assert input == pdf and capture_output and timeout == 8 and not check
        return CompletedProcess(args, 0, png, b"")

    monkeypatch.setattr(server.shutil, "which", lambda _name: "pdftocairo")
    monkeypatch.setattr(server.subprocess, "run", render)
    with urllib.request.urlopen(route + "?path=problem.pdf&preview=first-page", timeout=10) as result:
        assert result.read() == png
        assert result.headers["Content-Type"] == "image/png"
    (root / "problem.pdf").write_bytes(b"<html>fixture that must stay inert</html>")
    assert api["call"]("/api/workspaces/" + slug + "/statement-pdf?path=problem.pdf")[0] == 422
