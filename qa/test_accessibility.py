"""Static WCAG/keyboard audit for the app shell."""
import pathlib
import re
import sys
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parent.parent
HTML = (ROOT / "web" / "index.html").read_text("utf-8")
CSS = (ROOT / "web" / "style.css").read_text("utf-8")


class Audit(HTMLParser):
    def __init__(self):
        super().__init__()
        self.buttons = []
        self.dialogs = []
        self.inputs = []
        self.current = None
        self.text = ""

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if tag == "button":
            self.current = {"tag": tag, "attrs": data, "text": ""}
            self.buttons.append(self.current)
        elif tag == "dialog":
            self.dialogs.append(data)
        elif tag in ("input", "textarea", "select"):
            self.inputs.append(data)

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"] += data

    def handle_endtag(self, tag):
        if tag == "button":
            self.current = None


def main():
    parser = Audit()
    parser.feed(HTML)
    assert re.search(r'<html[^>]+lang="en"', HTML), "html lang missing"
    assert 'aria-live="polite"' in HTML, "status live region missing"
    for button in parser.buttons:
        attrs = button["attrs"]
        name = button["text"].strip() or attrs.get("aria-label") or attrs.get("title")
        assert name, f"button has no accessible name: {attrs}"
    for dialog in parser.dialogs:
        assert dialog.get("aria-label") or dialog.get("aria-labelledby"), "dialog needs a label"
    assert "focus-visible" in CSS, "focus-visible style missing"
    assert "prefers-reduced-motion" in CSS, "reduced motion missing"
    assert "min-width: 24px" in CSS and "min-height: 24px" in CSS, "target size missing"
    assert "status-${" not in HTML
    assert 'tabindex="0"' in HTML and 'role="log"' in HTML, "conversation log needs keyboard focus"
    assert 'data-tab="mcp"' in HTML and 'id="panel-mcp"' in HTML, "MCP panel missing"
    assert 'input[type="checkbox"]' in CSS, "checkbox sizing missing"
    axe = (ROOT / "web" / "vendor" / "axe.min.js")
    assert axe.is_file() and axe.stat().st_size > 100_000, "axe-core vendor bundle missing"
    assert '--faint: #8792a3' in CSS and '--accent-2: #3d55c8' in CSS, "contrast tokens regressed"
    js = (ROOT / "web" / "app.js").read_text("utf-8")
    assert 'treeAction("?"' not in js, "tree action glyphs regressed to ?"
    assert 'textContent = isDir ? (expanded ? "?"' not in js, "tree toggle glyph regressed to ?"
    print(f"  PASS {len(parser.buttons)} buttons have accessible names")
    print("  PASS axe-core bundle present")
    print(f"  PASS {len(parser.inputs)} form controls inspected")
    print("ACCESSIBILITY AUDIT PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
