"""Start a disposable Studio with deterministic long chats and large reports."""
from pathlib import Path
import argparse
import json
import mimetypes
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--baseline-web", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_relative_to(ROOT / "tmp") or root.exists():
        parser.error("Use a new fixture directory inside the local tmp directory.")
    root.mkdir(parents=True)
    os.environ.update(AUTHOR_AGENT_ENGINE_ROOT=str(root / "engine"), AUTHOR_AGENT_WORKSPACES_ROOT=str(root / "packages"),
                      AUTHOR_AGENT_ENGINE_DEMO="0", AUTHOR_AGENT_ENGINE_LIVE_MODEL="0")
    import server
    import studio
    import workspace
    from engine.chat import ChatService

    service = server.engine_service()
    fixtures = []
    for messages, files, tests in [(100, 50, 120), (500, 300, 1200)]:
        name = f"Timing fixture {messages} turns"
        run_id = service.create_run(workspace_id="performance-fixture", idea=name, title=name)["runId"]
        store = service.store(run_id)
        for seq in range(1, messages + 1):
            store.append_chat_message(run_id, role="author" if seq % 2 else "assistant", kind="message",
                                      text=f"Turn {seq:03d} of {messages}. Reproducible note on the prefix invariant, bounds and sample cases.")
        linked = studio.link_package(service, run_id, {"name": name, "expectedSlug": None}, server.workspace_lock)
        slug = linked["slug"]
        fixture_cases = [f"data/secret/case-{seq:03d}.in" for seq in range(files)]
        for path in fixture_cases:
            target = workspace.resolve(slug, path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("1 2\n", encoding="utf-8")
        workspace.set_report(slug, {"status": "failed", "snapshot": workspace.snapshot_hash(slug), "at": workspace.now(),
            "errors": ["Synthetic timing report"], "tests": [
                {"kind": "secret" if idx % 3 else "sample", "group": f"group-{idx % 4}",
                 "path": fixture_cases[idx % files], "test": f"timing/{idx:04d}",
                 "solutions": [{"path": "submissions/accepted/reference.py", "verdict": "WA" if idx % 13 == 0 else "AC"}]}
                for idx in range(tests)]})
        fixtures.append({"runId": run_id, "slug": slug, "messages": messages, "files": files, "tests": tests})

    if args.baseline_web:
        original_static = server.Handler.static_file
        original_view = ChatService.view
        baseline = args.baseline_web.resolve()

        def serve_baseline(handler, path):
            filename = "studio.html" if path == "/" else path.lstrip("/")
            if filename not in {"studio.html", "studio.css", "engine.js", "studio.js", "studio-navigation.js"}:
                return original_static(handler, path)
            data = (baseline / filename).read_bytes()
            handler.send_response(200)
            handler.send_header("Content-Type", mimetypes.guess_type(filename)[0] + "; charset=utf-8")
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            handler.wfile.write(data)

        def baseline_view(self, run_id, **kwargs):
            info = original_view(self, run_id, **kwargs)
            info["chatMessages"] = self.service.store(run_id).list_chat_messages(run_id, limit=200)
            return info

        server.Handler.static_file = serve_baseline
        ChatService.view = baseline_view
    (root / "fixtures.json").write_text(json.dumps(fixtures), encoding="utf-8")
    sys.argv = [sys.argv[0], "--port", str(args.port)]
    server.main()


if __name__ == "__main__":
    main()
