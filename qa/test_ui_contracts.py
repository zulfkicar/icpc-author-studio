"""Static UI safety, shell and dialog contracts.

These checks are intentionally cheap and deterministic: they catch the mistakes
that a rendered test cannot see everywhere (a removed ID, a reintroduced native
dialog, a missing landmark). Rendered behaviour is covered by the CDP scripts.
"""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
HTML = (ROOT / "web" / "index.html").read_text("utf-8")
JS = (ROOT / "web" / "app.js").read_text("utf-8")
CSS = (ROOT / "web" / "style.css").read_text("utf-8")

DIALOGS = ["new-dialog", "settings-dialog", "context-dialog", "action-dialog", "palette-dialog"]
NATIVE_DIALOG = re.compile(r"(?<![\w.$-])(?:window\.)?(prompt|confirm|alert)\s*\(")


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS {name}")
        return
    print(f"  FAIL {name} {detail}")
    raise AssertionError(name)


def check_native_dialogs():
    offenders = []
    for path in sorted((ROOT / "web").glob("*.js")):
        for number, line in enumerate(path.read_text("utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*"):
                continue
            match = NATIVE_DIALOG.search(line)
            if match:
                offenders.append(f"{path.name}:{number}:{match.group(1)}")
    check("no native prompt/confirm/alert", not offenders, ", ".join(offenders))


def check_ui_ids():
    manifest_path = ROOT / "qa" / "ui_ids.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    actual = set(re.findall(r'\bid="([^"]+)"', HTML))
    missing = sorted(set(manifest) - actual)
    check("ui id manifest resolves", not missing, ", ".join(missing))
    check("ui id manifest is populated", len(manifest) >= 100, str(len(manifest)))


def check_dialog_controller():
    check("dialog controller ships", (ROOT / "web" / "dialogs.js").exists())
    check("every dialog routes through the controller", JS.count("AuthorDialogs.open") >= 3 and "openSettings" in JS)
    for dialog in DIALOGS:
        block = re.search(rf'<dialog id="{dialog}"[^>]*>', HTML)
        check(f"{dialog} exists", bool(block))
        check(f"{dialog} is labelled", 'aria-labelledby' in block.group(0))
        check(f"{dialog} is described", 'aria-describedby' in block.group(0))
    check("dialog controller owns cancel", "requestClose" in (ROOT / "web" / "dialogs.js").read_text("utf-8"))
    check("quick open and command palette wired", "openPalette" in JS and 'key.toLowerCase() === "k"' in JS and 'key.toLowerCase() === "p"' in JS)


def main():
    check("run output truncates", "slice(0, 16000)" in JS)
    check("run output is textContent", '$("run-output").textContent' in JS)
    check("log area scrolls", ".run-output" in CSS and "overflow: auto" in CSS)
    check("status labels include text", "escapeHtml(check.status)" in JS and "escapeHtml(s.verdict)" in JS)
    check("busy guard exists", "state.fileBusy" in JS)
    check("xss escape used", "function escapeHtml" in JS)
    check("test labels are textual", 'result.pass ? "PASS" : "FAIL"' in JS)
    check("tab close glyph", 'close.textContent = "\\u00d7"' in JS)
    check("no literal question-mark actions", 'treeAction("?"' not in JS)
    check("judge0 quick run wired", 'judge0-run' in HTML and 'runJudge0' in JS and 'judge0Url' in JS)
    check("isolate quick run wired", 'isolate-run' in HTML and 'runIsolate' in JS and 'isolateUrl' in JS)
    check("group scoring rendered", 'renderGroupMatrix' in JS and 'report.groups' in JS)

    # Five-region shell contracts.
    for region, klass in [
        ("activity rail", "activity-rail"),
        ("navigator", "navigator"),
        ("editor group", "editor-group"),
        ("agent panel", "agent-panel"),
        ("status bar", "statusbar"),
    ]:
        check(f"{region} exists", f'class="{klass}' in HTML or f" {klass}" in HTML)
    check("regions are tagged", HTML.count('data-region="') >= 3)
    check("agent panel is the chat", 'class="chat-pane agent-panel"' in HTML)
    check("editor group is central", 'id="editor-group"' in HTML and 'class="right editor-group"' in HTML)
    check("navigator holds the problem card", 'id="problem-card"' in HTML and 'class="left navigator"' in HTML)
    check("grid uses navigator/agent widths", "--nav-width" in CSS and "--agent-width" in CSS)
    check("no iframe editor", "<iframe" not in HTML)
    check("status bar has backend health", all(
        token in HTML for token in ["status-judge0", "status-isolate", "status-executor"]
    ))
    check("status bar has cursor and verify", 'id="status-cursor"' in HTML and 'id="status-verify"' in HTML)
    check("skip links exist", HTML.count('class="skip-link"') >= 2)
    check("activity rail has six sections", HTML.count("data-activity=") >= 6)

    check_native_dialogs()
    check_ui_ids()
    check_dialog_controller()
    print("UI CONTRACT TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
