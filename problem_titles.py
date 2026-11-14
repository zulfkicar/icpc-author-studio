"""Render the author-supplied title in the formats used by Author Studio."""
from __future__ import annotations

import re


def validate_title(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Problem title must be text.")
    title = value.strip()
    if not 1 <= len(title) <= 100 or not title.isprintable():
        raise ValueError("Enter a problem title on one line, up to 100 characters.")
    return title


def latex_text(text: str) -> str:
    reserved = {"\\": r"\textbackslash{}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
    reserved.update({char: "\\" + char for char in "{}$&#_%"})
    return "".join(reserved.get(char, char) for char in text)


_TITLE_COMMAND = re.compile(
    r"^[ \t]*(?:\\(?:re)?newcommand[ \t]*\{\\problemname\}|\\problemname)[ \t]*\{", re.M,
)


def statement_title(text: str, title: str) -> str:
    """Update the title argument and retain every other statement byte."""
    match = _TITLE_COMMAND.search(text)
    if match is None:
        return text
    start = pos = match.end()
    depth = 1
    while pos < len(text):
        char = text[pos]
        if char == "\\":
            pos += 2
            continue
        if char == "%":
            end = text.find("\n", pos)
            pos = len(text) if end < 0 else end + 1
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[:start] + latex_text(title) + text[pos:]
        pos += 1
    return text
