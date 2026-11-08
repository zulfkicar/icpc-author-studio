"""Static UI safety contracts for logs, ANSI/XSS and status labels."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
HTML = (ROOT / "web" / "index.html").read_text("utf-8")
JS = (ROOT / "web" / "app.js").read_text("utf-8")
CSS = (ROOT / "web" / "style.css").read_text("utf-8")


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS {name}")
        return
    print(f"  FAIL {name} {detail}")
    raise AssertionError(name)


def main():
    check("run output truncates", "slice(0, 16000)" in JS)
    check("run output is textContent", "output.textContent = parts.join" in JS)
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
    print("UI CONTRACT TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
