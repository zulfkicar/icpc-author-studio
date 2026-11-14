"""Graph state: IDs and compact summaries only.

Full records live in the application ledger.  Reducers merge evidence maps by
stable ID only when payload hashes agree; decisions are versioned records in the
ledger, not an additive list.
"""
from __future__ import annotations

from typing import Annotated, Any, NotRequired, TypedDict


def merge_evidence(left: dict | None, right: dict | None) -> dict:
    merged = dict(left or {})
    for key, value in (right or {}).items():
        if key in merged and merged[key] != value:
            raise ValueError(f"conflicting evidence payload for {key}")
        merged[key] = value
    return merged


def keep_last(left: Any, right: Any) -> Any:
    return right if right is not None else left


class EngineState(TypedDict, total=False):
    run_id: str
    workspace_id: str
    controller_epoch: int
    goal_generation: int
    revision: str
    steering_epoch: int
    applied_author_seq: int
    goal_text: str
    decisions: list[dict]
    engagement: str
    explanation_depth: str
    delegation: dict | None
    grant: dict | None
    budget: dict
    contributions: list[dict]
    findings: list[dict]
    evidence_ids: list[str]
    explanation_requests: list[dict]
    pending_interaction_id: str | None
    continuation: dict | None
    plan: dict | None
    admission: dict | None
    child_result: dict | None
    wake: dict | None
    next_route: str
    handoff_ref: str | None
    stage_return: dict | None
    error: str | None
    progress: list[dict]
    action_signatures: list[str]
    resume_after_handoff: bool
    current_explanation_id: str | None
    evidence_summary: Annotated[dict, merge_evidence]
    last_result_key: str | None


class CollaborationInput(TypedDict, total=False):
    run_id: str
    ctx: dict
    args: dict
    phase: str
    procedure: str
    admission: dict
    continuation: dict | None
    retrieved: dict
    draft: dict
    package: dict
    result: dict


class CollaborationOutput(TypedDict, total=False):
    result: dict


class InvestigationInput(TypedDict, total=False):
    run_id: str
    ctx: dict
    args: dict
    phase: str
    admission: dict
    continuation: dict | None
    plan: dict
    operation_id: str
    result: dict
    next_phase: str


class InvestigationOutput(TypedDict, total=False):
    result: dict


class EditingInput(TypedDict, total=False):
    run_id: str
    ctx: dict
    args: dict
    phase: str
    admission: dict
    continuation: dict | None
    patch: dict
    result: dict
    next_phase: str


class EditingOutput(TypedDict, total=False):
    result: dict


class ReviewInput(TypedDict, total=False):
    run_id: str
    ctx: dict
    args: dict
    admitted_artifacts: list[str]
    brief: dict
    findings: dict
    result: dict


class ReviewOutput(TypedDict, total=False):
    result: dict


ParentRoutes = {
    "reconcile": {"frame_goal", "select_action", "admit_action", "await_human",
                  "await_operation", "handoff"},
    "frame_goal": {"select_action", "admit_action", "handoff"},
    "select_action": {"admit_action", "assess", "handoff"},
    "admit_action": {"collaboration", "investigation", "editing", "review",
                     "await_human", "assess", "handoff"},
    "assess": {"reconcile", "await_human", "await_operation", "handoff"},
    "await_human": {"reconcile"},
    "await_operation": {"reconcile"},
    "handoff": set(),
    "collaboration": {"assess"},
    "investigation": {"assess"},
    "editing": {"assess"},
    "review": {"assess"},
}


def validate_route(source: str, route: str) -> str:
    allowed = ParentRoutes.get(source)
    if allowed is None:
        raise ValueError(f"unknown router source {source!r}")
    if route not in allowed:
        raise ValueError(f"invalid successor {route!r} from {source!r}; allowed {sorted(allowed)}")
    return route
