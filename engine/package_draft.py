"""Draft files for the supported weighted-interval package profile."""
from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from problem_titles import latex_text

from .domain import MAX_COORD, MAX_N, MAX_REWARD, MAX_SUM, oracle_subset, parse_instance, render_instance
from .schemas import Model


class DraftCase(Model):
    group: Literal["sample", "secret"]
    input: str = Field(min_length=3, max_length=480)
    purpose: str = Field(min_length=1, max_length=160)

    @field_validator("input")
    @classmethod
    def canonical_input(cls, value: str) -> str:
        if any(not token.isascii() or not token.isdecimal() for token in value.split()):
            raise ValueError("draft cases require unsigned ASCII integers")
        instance = parse_instance(value)
        if instance.n > 12:
            raise ValueError("draft cases allow at most 12 bookings")
        return render_instance(instance)


class PackageDraft(Model):
    title: str = Field(min_length=1, max_length=80)
    story: str = Field(min_length=1, max_length=1200)
    solution_cpp: str = Field(min_length=1, max_length=8000)
    wrong_answer_cpp: str = Field(min_length=1, max_length=5000)
    editorial: str = Field(min_length=1, max_length=2400)
    tests: list[DraftCase] = Field(min_length=3, max_length=12)

    @model_validator(mode="after")
    def check_package(self):
        for source in (self.solution_cpp, self.wrong_answer_cpp):
            if not source.strip() or "```" in source or "\0" in source:
                raise ValueError("provide raw C++ source without Markdown fences")
        if self.solution_cpp.strip() == self.wrong_answer_cpp.strip():
            raise ValueError("the reference and intentionally wrong source must differ")
        if len({test.input for test in self.tests}) != len(self.tests):
            raise ValueError("a draft contains duplicate inputs")
        secrets = sum(test.group == "secret" for test in self.tests)
        if secrets == len(self.tests) or secrets < 2:
            raise ValueError("at least one sample and two distinct secret cases are required")
        return self


class PackageRepair(Model):
    solution_cpp: str = Field(min_length=1, max_length=8000)


def _statement(draft: PackageDraft, semantics: str) -> str:
    boundary = ("A booking may start at the exact time another booking finishes."
                if semantics == "half_open" else
                "A booking must start strictly after the finish of the previous booking.")
    return rf"""\documentclass{{article}}
\newcommand{{\problemname}}{{{latex_text(draft.title.strip())}}}
\begin{{document}}
\section*{{\problemname}}
{latex_text(draft.story.strip())}

Select a subset of bookings on one resource with maximum total reward.
{boundary} Each booking may be selected at most once. Identical bookings can appear in the input.
\section*{{Input}}
The first line contains $n$ ($1 \le n \le {MAX_N}$).
Each of the next $n$ lines contains three integers $s$, $f$, and $w$,
where $0 \le s < f \le {MAX_COORD}$ and $1 \le w \le {MAX_REWARD}$.
They denote the start, finish and reward of a booking.
\section*{{Output}}
Print the maximum possible total reward as one integer.
\end{{document}}
"""


def _validator() -> str:
    return f'''import sys


def valid(data):
    tokens = data.split()
    if not tokens or any(not token.isascii() or not token.isdecimal() for token in tokens):
        return False
    try:
        values = list(map(int, tokens))
    except ValueError:
        return False
    n = values[0]
    if not 1 <= n <= {MAX_N} or len(values) != 1 + 3 * n:
        return False
    total = 0
    for start, finish, reward in zip(values[1::3], values[2::3], values[3::3]):
        if not (0 <= start < finish <= {MAX_COORD} and 1 <= reward <= {MAX_REWARD}):
            return False
        total += reward
    return total <= {MAX_SUM}


sys.exit(42 if valid(sys.stdin.read()) else 1)
'''


def package_files(draft: PackageDraft, semantics: str) -> list[dict]:
    """Use host paths and derive bounded expected answers independently of the model."""
    if semantics not in ("half_open", "closed"):
        raise ValueError("recorded endpoint semantics are required")
    files = [
        {"kind": "statement", "path": "problem_statement/problem.en.tex", "text": _statement(draft, semantics)},
        {"kind": "solution", "path": "submissions/accepted/reference.cpp", "text": draft.solution_cpp},
        {"kind": "negative", "path": "submissions/wrong_answer/baseline.cpp", "text": draft.wrong_answer_cpp},
        {"kind": "validator", "path": "input_validators/validate.py", "text": _validator()},
        {"kind": "editorial", "path": "editorial/solution.md", "text": draft.editorial},
    ]
    counts = {"sample": 0, "secret": 0}
    for test in draft.tests:
        instance = parse_instance(test.input)
        counts[test.group] += 1
        path = f"data/{test.group}/{counts[test.group]:02d}.in"
        value = oracle_subset(instance, semantics=semantics, max_jobs=12)["value"]
        files.append({"kind": "test", "path": path, "text": test.input, "purpose": test.purpose,
                      "oracleExpected": value})
    return [{**file, "text": file["text"].strip() + "\n"} for file in files]
