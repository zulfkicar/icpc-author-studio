"""Disk/write failure and corrupt-checkpoint fail-closed tests."""
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from author_studio.classic import graph_agent
from author_studio.packages import workspace


def main():
    created = workspace.create("QA Disk DB", "failure")
    slug = created["slug"]
    chat = workspace.ensure_chats(slug)["activeChat"]
    try:
        workspace.write_text(slug, "blocker", "not a directory", source="test")
        try:
            workspace.write_text(slug, "blocker/child.txt", "x", source="test")
        except OSError as exc:
            print("  PASS write failure surfaced", type(exc).__name__)
        else:
            raise AssertionError("write should fail when parent is a file")

        workspace.checkpoint_path(slug).write_bytes(b"this is not sqlite")
        try:
            graph_agent.list_history(slug, chat)
        except Exception as exc:
            print("  PASS corrupt checkpoint fails closed", type(exc).__name__)
        else:
            raise AssertionError("corrupt checkpoint should fail closed")
    finally:
        shutil.rmtree(workspace.ws_path(slug), ignore_errors=True)
    print("DISK/DB FAILURE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
