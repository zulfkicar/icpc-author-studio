"""Shared schemas for events, clarification, approvals and packages.

These are intentionally small, dependency-free dataclasses. They are the
contract between the graph runtime, HTTP layer and UI. The UI must render the
readable fields first and may expose `raw` on demand.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

EventStage = Literal[
    "plan", "generate", "validate", "answers", "measure",
    "verify", "review", "export", "clarify", "approve",
]
EventStatus = Literal[
    "queued", "running", "passed", "failed", "cancelled",
    "stale", "blocked", "info",
]


@dataclass
class Event:
    run_id: str
    seq: int
    at: str
    stage: EventStage
    tool: str = ""
    intent: str = ""
    status: EventStatus = "info"
    duration_ms: float = 0.0
    summary: str = ""
    detail: str = ""
    artifacts: list[str] = field(default_factory=list)
    raw: str = ""

    def __post_init__(self) -> None:
        if self.seq < 1:
            raise ValueError("Event seq must be >= 1")
        if self.duration_ms < 0:
            raise ValueError("Event duration must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return {
            "runId": data["run_id"],
            "seq": data["seq"],
            "at": data["at"],
            "stage": data["stage"],
            "tool": data["tool"],
            "intent": data["intent"],
            "status": data["status"],
            "durationMs": data["duration_ms"],
            "summary": data["summary"],
            "detail": data["detail"],
            "artifacts": data["artifacts"],
            "raw": data["raw"],
        }


@dataclass
class ClarificationQuestion:
    id: str
    question: str
    why: str = ""
    options: list[str] = field(default_factory=list)
    recommended: str = ""
    allow_free_text: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ClarificationRequest:
    id: str
    chat_id: str
    questions: list[ClarificationQuestion]
    blocking: bool = True

    def __post_init__(self) -> None:
        if not self.questions:
            raise ValueError("At least one clarification question is required")
        if len(self.questions) > 3:
            raise ValueError("Ask at most three questions at a time")
        if len({item.id for item in self.questions}) != len(self.questions):
            raise ValueError("Clarification ids must be unique")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "chatId": self.chat_id,
            "blocking": self.blocking,
            "questions": [item.to_dict() for item in self.questions],
        }


@dataclass
class ApprovalRequest:
    id: str
    chat_id: str
    action: str
    command: list[str] = field(default_factory=list)
    path: str = ""
    diff: str = ""
    risk: str = "medium"
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PackageMetadata:
    name: str
    uuid: str = ""
    version: str = ""
    type: str = "pass-fail"
    time_limit: float = 1.0
    memory_mb: int = 256
    output_mb: int = 8
    code_kb: int = 128
    license: str = "unknown"
    source: str = ""
    rights_owner: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_event_dict(value: dict) -> bool:
    required = ("runId", "seq", "at", "stage", "status")
    if not isinstance(value, dict) or any(key not in value for key in required):
        return False
    return value["stage"] in set(EventStage.__args__) and value["status"] in set(EventStatus.__args__)
