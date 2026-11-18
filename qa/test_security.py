"""Security/adversarial unit tests that do not need a provider."""
import pathlib
import shutil
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from author_studio import config
from author_studio.packages import workspace


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS {name}")
        return
    print(f"  FAIL {name} {detail}")
    raise AssertionError(name)


def expect_error(name, fn, exc=(ValueError, FileNotFoundError)):
    try:
        fn()
    except exc:
        check(name, True)
    else:
        check(name, False, "expected an error")


def main():
    created = workspace.create("QA Security", "security")
    slug = created["slug"]
    chat = workspace.ensure_chats(slug)["activeChat"]
    try:
        expect_error("path traversal rejected", lambda: workspace.resolve(slug, "../escape"))
        expect_error("agent state write rejected", lambda: workspace.write_text(slug, ".agent/x", "x"))
        expect_error("absolute path rejected", lambda: workspace.resolve(slug, "/etc/passwd"))
        expect_error("invalid chat id rejected", lambda: workspace.snapshot_turn(slug, "../chat"))

        # A malicious snapshot must not escape the staging directory.
        archive = workspace._snapshots_root(slug, chat) / "malicious.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../escaped.txt", "bad")
        expect_error("zip slip rejected", lambda: workspace.restore_snapshot(slug, chat, "malicious"))
        check("zip slip did not write", not (workspace.ws_path(slug).parent / "escaped.txt").exists())

        key = "xpl_1234567890abcdef"
        redacted = config.redact(f"key={key}")
        check("secret redacted", key not in redacted, redacted)
        check("public hides key", "apiKey" not in config.public({"apiKey": key}))
    finally:
        shutil.rmtree(workspace.ws_path(slug), ignore_errors=True)
    print("SECURITY TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
