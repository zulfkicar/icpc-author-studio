"""Workspace snapshot and restore tests."""
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from author_studio.packages import workspace


def check(name, condition, detail=""):
    if condition:
        print("  PASS", name)
        return
    print("  FAIL", name, detail)
    raise AssertionError(name)


def main():
    created = workspace.create("QA Snapshots", "snapshot test")
    slug = created["slug"]
    chat = workspace.ensure_chats(slug)["activeChat"]
    try:
        workspace.write_text(slug, "NOTES.md", "before\n", source="test")
        for _ in range(22):
            workspace.snapshot_turn(slug, chat)
        workspace.write_text(slug, "NOTES.md", "after\n", source="test")
        workspace.write_text(slug, "extra.txt", "extra\n", source="test")
        listing = workspace.list_snapshots(slug, chat)
        check("snapshot listed", bool(listing), listing)
        check("snapshot retention", len(listing) <= 20, len(listing))
        latest = listing[0]["id"]
        result = workspace.restore_snapshot(slug, chat, latest)
        check("snapshot restored", result["restored"], result)
        check("file restored", (workspace.ws_path(slug) / "NOTES.md").read_text("utf-8") == "before\n")
        check("extra removed", not (workspace.ws_path(slug) / "extra.txt").exists())
    finally:
        shutil.rmtree(workspace.ws_path(slug), ignore_errors=True)
    print("SNAPSHOT TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
