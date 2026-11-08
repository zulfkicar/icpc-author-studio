"""Typed graph state for the authoring agent."""
from __future__ import annotations

import operator
from typing import Annotated, NotRequired

from langchain.agents import AgentState


def merge_skills(left, right):
    """Merge concurrent skill loads/unloads without losing either update."""
    merged = dict(left or {}) if isinstance(left, dict) else {}
    incoming = dict(right or {}) if isinstance(right, dict) else {}
    merged.update(incoming)
    return merged


class AuthorState(AgentState):
    slug: NotRequired[str]
    chat_id: NotRequired[str]
    brief: NotRequired[str]
    requirements: NotRequired[list[str]]
    decisions: Annotated[list[dict], operator.add]
    open_questions: NotRequired[list[str]]
    active_skills: NotRequired[Annotated[dict[str, bool], merge_skills]]
    clarifications: Annotated[list[dict], operator.add]
    pending_clarification: NotRequired[dict]
    focus: NotRequired[str]
    mode: NotRequired[str]
    selected_context: NotRequired[list[str]]
    verification: NotRequired[dict]


MAX_BRIEF = 4000
MAX_REQUIREMENTS = 100
MAX_DECISIONS = 50
MAX_QUESTIONS = 50
MAX_CONTEXT_FILES = 25


def clean_brief(value) -> str:
    return " ".join(str(value or "").split())[:MAX_BRIEF]


def clean_list(value, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        text = " ".join(str(item or "").split())[:500]
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def clean_decisions(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if not isinstance(item, dict):
            continue
        question = " ".join(str(item.get("question") or "").split())[:500]
        answer = " ".join(str(item.get("answer") or "").split())[:2000]
        if not question or not answer:
            continue
        out.append({
            "question": question,
            "answer": answer,
            "rationale": " ".join(str(item.get("rationale") or "").split())[:1000],
            "source": " ".join(str(item.get("source") or "").split())[:300],
        })
        if len(out) >= MAX_DECISIONS:
            break
    return out
