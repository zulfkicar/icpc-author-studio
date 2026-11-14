"""Parent StateGraph and four narrowly projected subgraphs.

Routing discipline: every child returns through ``assess``; each transition is
one validated conditional edge.  No node mixes a static successor with
``Command.goto``.  Child subgraphs receive ids + compact context, return one
result envelope, and never share parent authority.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .budget import BudgetExhausted, ModelGateway, parse_utc
from .clock import CrashInjected, Failpoints
from .context import (assemble, artifact_context, contribution_context,
                      conversation_context, procedure_index)
from .diagnostic import (
    oracle_for,
    run_campaign,
    run_diagnostic,
)
from .domain import (
    Instance,
    InvalidInput,
    Job,
    finite_domain,
    parse_instance,
    render_instance,
    witness_contained_pair,
    witness_duplicate_jobs,
    witness_large_reward,
    witness_two_touching,
    witness_weighted_greedy,
)
from .graph_state import (
    CollaborationInput,
    CollaborationOutput,
    EditingInput,
    EditingOutput,
    EngineState,
    InvestigationInput,
    InvestigationOutput,
    ReviewInput,
    ReviewOutput,
    validate_route,
)
from .input_service import InputService
from .model import PROVIDER_ERRORS, validate_with
from .interpretation import canonical_endpoint_option, unquoted
from .package_check import MAX_REPAIRS, check_reference
from .package_draft import PackageDraft, PackageRepair, package_files
from .policy import PolicyDenied, operation_supported
from .projection import ProjectionManager
from .prompts import bundle_hash, prompt
from .procedures import compose_selection, read_skill_resource
from .schemas import (
    CollaborationDraftV1,
    EvidenceV1,
    ExplanationV1,
    FindingV1,
    GoalProposalV1,
    HandoffV1,
    HumanInteractionV1,
    InterpretDraftV1,
    InvestigationDesign,
    OperationEnvelopeV1,
    OperationResultV1,
    PatchDraftV1,
    PlanV1,
    ReviewFindingsV1,
    StageReturnContract,
    canonical_json,
    sha256_text,
)
from .stage import contract_from_delegation, evaluate_stage_return
from .store import ApplicationStore, LedgerError, PublicationBlocked
from .worker import WorkerUnavailable

TERMINAL_OPERATION = {"completed", "failed", "incomplete", "cancelled", "outcome_unknown"}

FIXTURE_SOURCES = {
    "weighted_greedy": witness_weighted_greedy,
    "touching": witness_two_touching,
    "contained": witness_contained_pair,
    "large_reward": witness_large_reward,
    "duplicates": witness_duplicate_jobs,
}


@dataclass
class Runtime:
    store: ApplicationStore
    inputs: InputService
    gateway: ModelGateway
    worker: Any
    clock: Clock | None = None
    projection: ProjectionManager | None = None
    failpoints: Failpoints = field(default_factory=Failpoints)
    fixture_dir: str | None = None
    model_name: str = "fake-model-v1"

    def __post_init__(self) -> None:
        self.clock = self.clock or self.store.clock

    @property
    def store_root(self):
        return self.store.root

    def candidate_source(self, run_id: str, ref: object) -> tuple[str, str, str]:
        """Resolve an offered reference to its canonical ID, source and label."""
        metadata = ref if isinstance(ref, dict) else {}
        if metadata:
            ref = metadata.get("artifact_id")
        if not isinstance(ref, str):
            raise LedgerError("Candidate needs a current artifact or contribution ID")
        if ref.startswith("contrib-"):
            ref = "contribution:" + ref
        if ref.startswith("art-"):
            ref = "artifact:" + ref
        run = self.store.get_run(run_id)
        revision = run["observed_revision"]
        if ref.startswith("source:"):
            digest = ref.split(":", 1)[1]
            matches = [item for item in self.store.list_contributions(run_id)
                       if item["kind"] == "code" and item["revision"] == revision
                       and item["original_blob_hash"] == digest]
            if len(matches) != 1:
                raise LedgerError("Source hash does not identify a unique current code contribution")
            ref = "contribution:" + matches[0]["id"]
        if ref.startswith("contribution:"):
            contribution = self.store.get_contribution(ref.split(":", 1)[1])
            if (contribution["run_id"] != run_id or contribution["revision"] != revision
                    or contribution["kind"] != "code"):
                raise LedgerError("Candidate is not a current code contribution for this run")
            digest, label = contribution["original_blob_hash"], contribution["id"]
        elif ref.startswith("artifact:"):
            artifact = self.store.get_artifact(ref.split(":", 1)[1])
            if (artifact["run_id"] != run_id or artifact["revision"] != revision
                    or not artifact["current"] or artifact["kind"] not in ("solution", "negative")
                    or not artifact["path"].endswith(".cpp")):
                raise LedgerError("Candidate is not a current C++ artifact for this run")
            digest, label = artifact["blob_hash"], artifact["id"]
        elif ref.startswith("fixture:") and not metadata:
            name = ref.split(":", 1)[1]
            if self.fixture_dir and re.fullmatch(r"[a-zA-Z0-9_-]+", name):
                root = Path(self.fixture_dir).resolve()
                path = (root / f"{name}.cpp").resolve()
                if path.parent == root and path.is_file():
                    return ref, path.read_text(encoding="utf-8"), name
            raise LedgerError(f"Unknown engine fixture {name!r}")
        else:
            raise LedgerError(f"Unsupported candidate reference {ref[:160]!r}")
        if metadata.get("sha256", digest) != digest or metadata.get("revision", revision) != revision:
            raise LedgerError("Candidate hash or revision does not match the current source")
        return ref, self.store.get_blob(digest).decode("utf-8"), label


def _run(runtime: Runtime, run_id: str) -> dict:
    return runtime.store.get_run(run_id)


def _ctx(runtime: Runtime, state: dict) -> dict:
    run = _run(runtime, state["run_id"])
    collab = runtime.inputs.collaboration(state["run_id"])
    delegation = runtime.store.active_delegation(state["run_id"])
    grant = runtime.store.active_grant(state["run_id"])
    return {
        "run_id": state["run_id"],
        "goal_generation": int(run["goal_generation"]),
        "revision": run["observed_revision"],
        "steering_epoch": int(run["steering_epoch"]),
        "controller_epoch": int(run["controller_epoch"]),
        "applied_author_seq": int(run["applied_author_seq"]),
        "goal_text": run["goal_text"],
        "decisions": collab.get("decisions", []),
        "engagement": collab.get("engagement", "together"),
        "explanation_depth": collab.get("explanation_depth", "standard"),
        "delegation": delegation,
        "grant": grant,
        "budget": runtime.store.budget_view(state["run_id"]),
        "contributions": runtime.store.list_contributions(state["run_id"]),
        "findings": runtime.store.list_findings(state["run_id"]),
        "evidence_ids": [e["id"] for e in runtime.store.list_evidence(state["run_id"])
                         if e["freshness"] == "current"],
        "editDenied": bool(collab.get("edit_denied")),
        "editIntent": (collab.get("author_edit_intent") or {}).get("value", "neutral"),
        "editGranted": "edit" in set((grant or {}).get("operation_kinds") or []),
        "editScope": list((grant or {}).get("scope") or []),
        "reservation_id": (state.get("continuation") or {}).get("reservation_id"),
    }


def _decision_map(ctx: dict) -> dict[str, dict]:
    return {str(d.get("requirementId")): d for d in (ctx.get("decisions") or [])}


def _interaction_id(card: dict) -> str:
    return "int-" + sha256_text(card)[:14]


def _get_or_create_interaction(runtime: Runtime, run_id: str, *, kind: str, prompt_text: str,
                               why: str, options: list[dict], recommendation: str | None,
                               affected: list[str] | None = None,
                               dependent: list[str] | None = None,
                               evidence_refs: list[str] | None = None) -> dict:
    if kind not in ("semantics", "approach_choice", "proof_challenge", "explanation",
                    "test_contribution", "repair_review", "delegation", "export_approval"):
        raise LedgerError(f"unsupported interaction kind {kind!r}")
    if not options or len(options) > 3:
        raise LedgerError("a decision card needs one to three options")
    for option in options:
        if not isinstance(option, dict) or not option.get("id") or not option.get("label"):
            raise LedgerError("each option needs id and label")
    run = _run(runtime, run_id)
    card = {
        "kind": kind, "prompt": prompt_text[:2000], "why": why[:2000],
        "options": options, "recommendation": recommendation,
        "revision": run["observed_revision"], "generation": int(run["goal_generation"]),
        "affected": affected or [], "evidence": evidence_refs or [],
    }
    interaction_id = _interaction_id(card)
    existing = runtime.store.pending_interaction(run_id)
    if existing and existing["id"] == interaction_id:
        return existing
    interaction = HumanInteractionV1(
        id=interaction_id, run_id=run_id, kind=kind,
        revision=run["observed_revision"],
        goal_generation=int(run["goal_generation"]),
        proposal_hash=sha256_text(card),
        affected_claim_ids=affected or [],
        prompt_ref=prompt_text,
        why=why,
        option_ids=[str(o["id"]) for o in options],
        options=options,
        recommendation=recommendation,
        evidence_refs=evidence_refs or [],
        dependent_operations=dependent or [],
    )
    return runtime.store.create_interaction(interaction)


def _reserve(runtime: Runtime, run_id: str, *, action_id: str, plan: dict | None = None,
             cases: int | None = None) -> dict:
    if hasattr(plan, "model_dump"):
        plan = plan.model_dump()
    budget = _run(runtime, run_id)
    remaining = runtime.store.budget_view(run_id)["modelAttemptsRemaining"]
    attempts = min(3, max(0, int(remaining)))
    requested = (plan or {}).get("requested_budget") or {}
    case_need = int(cases if cases is not None else requested.get("cases") or 0)
    delegation = runtime.store.active_delegation(run_id)
    if delegation:
        ceiling = delegation.get("budget_ceiling") or {}
        if "cases" in ceiling:
            case_need = min(case_need, int(ceiling["cases"])) if case_need else int(ceiling["cases"])
    if attempts <= 0:
        raise BudgetExhausted("no model attempts remain", reason="attempts")
    return runtime.store.reserve_action(
        run_id, action_id=action_id, attempts_limit=attempts,
        cases=max(0, case_need), wall_ms=90_000,
    )


def _set_continuation(runtime: Runtime, run_id: str, **fields: Any) -> dict:
    run = _run(runtime, run_id)
    continuation = {
        "action_id": fields.get("action_id"),
        "child": fields.get("child"),
        "phase": fields.get("phase"),
        "request_hash": fields.get("request_hash"),
        "input_revision": run["observed_revision"],
        "goal_generation": int(run["goal_generation"]),
        "steering_epoch": int(run["steering_epoch"]),
        "reservation_id": fields.get("reservation_id"),
        "artifact_refs": fields.get("artifact_refs") or [],
        "operation_id": fields.get("operation_id"),
        "interaction_id": fields.get("interaction_id"),
        "args": fields.get("args") or {},
    }
    runtime.store.update_run(run_id, continuation_json=canonical_json(continuation),
                             active_operation_id=continuation.get("operation_id"))
    return continuation


def _clear_continuation(runtime: Runtime, run_id: str) -> None:
    runtime.store.update_run(run_id, continuation_json=None, active_operation_id=None)


def _path_in_scope(path: str, scope: list[str]) -> bool:
    paths = [item[5:] for item in scope if isinstance(item, str) and item.startswith("path:")]
    if not paths:
        return True
    normalized = str(path or "").replace("\\", "/").lstrip("./")
    return "*" in paths or normalized in paths


def _edit_authorization(runtime: Runtime, run_id: str, path: str,
                        collab: dict) -> tuple[bool, str]:
    """Re-check the current host edit authority at publication time.

    Admission is not publication: a queued diff must still have a live,
    path-scoped grant (or a specific author-edited proposal) at commit time.
    """
    if collab.get("edit_denied"):
        return False, "authorization_denied"
    if collab.get("patch_edits"):
        return True, "author_edit"
    grant = runtime.store.active_grant(run_id)
    if not grant or "edit" not in set(grant.get("operation_kinds") or []):
        return False, "authorization_required"
    if grant.get("revoked_at"):
        return False, "grant_revoked"
    if grant.get("expires_at") and parse_utc(grant["expires_at"]) and \
            parse_utc(grant["expires_at"]) < runtime.clock.now():
        return False, "grant_expired"
    run = runtime.store.get_run(run_id)
    if int(grant.get("goal_generation") or 0) != int(run["goal_generation"]):
        return False, "grant_stale_generation"
    if not _path_in_scope(path, list(grant.get("scope") or [])):
        return False, "out_of_scope"
    return True, "grant"


def _check_allowed_action(ctx: dict, plan: PlanV1) -> str | None:
    """Host check of preconditions; returns a denial reason or None."""
    if plan.action in ("ask", "collaborate"):
        return None
    grant = ctx.get("grant")
    delegation = ctx.get("delegation")
    ops = set((grant or {}).get("operation_kinds") or [])
    permitted = set((delegation or {}).get("permitted_operations") or [])
    if plan.action == "investigate":
        needed = {"differential_search", "replay_diagnostic"}
        allowed = (ops | permitted) & needed
        if not allowed:
            return "investigation requires a granted diagnostic operation"
        return None
    if plan.action == "edit":
        if ctx.get("editDenied"):
            return "authorization_denied"
        if not ctx.get("editGranted") and ctx.get("editIntent") == "information":
            return "information_only"
        path = str((plan.args or {}).get("path") or "")
        if ctx.get("editGranted") and path and not _path_in_scope(path, ctx.get("editScope") or []):
            return "out_of_scope"
        # Admission never writes files.  The editing child validates the exact
        # diff and requests this concrete effect when the grant does not cover it.
        return None
    if plan.action == "review":
        if "read_artifact" not in ops and "read_artifact" not in permitted and not ops:
            return "review requires a read grant"
        return None
    return None


# --------------------------------------------------------------------------- parent nodes
def build_parent(runtime: Runtime, checkpointer):
    def reconcile(state: EngineState) -> dict:
        run_id = state["run_id"]
        epoch = int(state.get("controller_epoch") or 0)
        runtime.store.log_controller(run_id, epoch, "reconcile")
        summary = runtime.inputs.apply_inbox(run_id)
        resp_semantic, response_summary = runtime.inputs.apply_responses(run_id)
        if resp_semantic:
            summary["semantic_change"] = True
        runtime.store.consume_settled_wakes(run_id, epoch)
        runtime.failpoints.hit("reconcile.after_apply")
        summary.setdefault("explanation_requests", [])
        summary["explanation_requests"].extend(response_summary.get("explanation_requests") or [])
        run = _run(runtime, run_id)
        ctx = _ctx(runtime, state)
        if run["status"] == "cancelled":
            _cancel_worker_operations(runtime, run_id)
            return {"next_route": "handoff",
                    "child_result": {"status": "cancelled", "kind": "cancelled"},
                    "progress": ["cancelled"]}
        # A pending ambiguity gets a concrete decision card; it is not consent.
        if summary.get("authorization_ambiguity"):
            ambiguity = summary["authorization_ambiguity"]
            paths = ambiguity.get("paths") or []
            target = paths[0] if paths else "the proposed file"
            plan = PlanV1.model_validate({
                "action": "ask",
                "intent": "Clarify whether a concrete file edit is authorized.",
                "args": {"interaction": {
                    "kind": "delegation",
                    "prompt": (
                        "Do you authorize an edit"
                        + (f" to {target}" if paths else " to the managed checkout")
                        + f"? Your note was: \"" + str(ambiguity.get("text") or "")[:400] + "\""
                    ),
                    "why": "The instruction is tentative or unclear; edit authority is not established.",
                    "options": [
                        {"id": "authorize", "label": "Authorize this edit scope",
                         "consequence": "allows one scoped revision after validation",
                         "scopePaths": paths},
                        {"id": "read_only", "label": "Keep the checkout read-only",
                         "consequence": "no file change; the stage remains diagnostic"},
                    ],
                    "recommendation": None,
                    "affectedClaimIds": [],
                    "dependentOperations": ["edit"],
                    "allow_reask": True,
                    "scopePaths": paths,
                }},
            })
            return {"plan": plan.model_dump(), "admission": None, "continuation": None,
                    "child_result": None, "next_route": "admit_action",
                    "progress": ["edit_authorization_ambiguity"]}
        if summary.get("needs_disambiguation"):
            input_id = summary["needs_disambiguation"][0]
            item = runtime.store.get_input(input_id)
            plan = PlanV1.model_validate({
                "action": "ask",
                "intent": "Clarify one consequential ambiguity before dependent effects.",
                "args": {"interaction": {
                    "kind": "semantics",
                    "prompt": (
                        "You wrote: \"" + item["text"][:400] + "\". Which concrete endpoint rule should "
                        "apply to touching jobs?"
                    ),
                    "why": summary.get("disambiguation_reason") or
                           "A dependent investigation/publication is fenced until this is decided.",
                    "options": [
                        {"id": "half_open", "label": "Half-open (touching jobs allowed)",
                         "consequence": "finish <= start is compatible"},
                        {"id": "closed", "label": "Closed (touching jobs conflict)",
                         "consequence": "finish < start is required"},
                    ],
                    "recommendation": None,
                    "affectedClaimIds": ["S2"],
                    "dependentOperations": ["diagnostic"],
                    "allow_reask": True,
                }},
            })
            return {"plan": plan.model_dump(), "admission": None, "continuation": None,
                    "child_result": None, "next_route": "admit_action",
                    "progress": ["needs_disambiguation"]}
        # A requested explanation reuses the receipt instead of launching an
        # unsolicited experiment (CR07).  The host prepares the complete plan.
        requests = list(state.get("explanation_requests") or [])
        if not requests:
            requests = []
            for item in runtime.store.list_inputs(run_id):
                payload = item.get("payload") or {}
                if item["status"] == "applied" and payload.get("kind") == "request_explanation":
                    requests.append({
                        "question": (payload.get("payload") or {}).get("question") or item["text"],
                        "targetRef": (payload.get("payload") or {}).get("target_ref"),
                        "depth": (payload.get("payload") or {}).get("depth"),
                    })
        if requests:
            request = requests[-1]
            depth = request.get("depth") or ctx["explanation_depth"]
            plan = PlanV1.model_validate({
                "action": "collaborate",
                "intent": "Answer the author's current question from the qualified receipt.",
                "target_claim_ids": [],
                "expected_observation": "current explanation artifact",
                "args": {"procedure": "COL-EXPLAIN", "question": request.get("question") or "",
                         "target_ref": request.get("targetRef"), "depth": depth,
                         "explanation_only": True},
                "requested_budget": {},
            })
            return {"plan": plan.model_dump(), "admission": None, "continuation": None,
                    "child_result": None, "next_route": "admit_action",
                    "progress": ["explanation_request"]}
        continuation = None
        if run["continuation_json"]:
            continuation = json.loads(run["continuation_json"])
        if continuation and continuation.get("child") == "await_human":
            # A wait continuation is meaningful only while its interaction is
            # pending.  After an answer it must not loop back into the wait.
            if runtime.store.pending_interaction(run_id) is None:
                continuation = None
                _clear_continuation(runtime, run_id)
        if continuation:
            operation_id = continuation.get("operation_id")
            if operation_id:
                operation = runtime.store.get_operation(operation_id)
                if operation["status"] in TERMINAL_OPERATION:
                    return {
                        "continuation": continuation,
                        "admission": {"child": continuation["child"], "phase": "interpret",
                                      "reuse": True, "reservation_id": continuation["reservation_id"],
                                      "operation_id": operation_id, "args": continuation.get("args") or {}},
                        "next_route": "admit_action", "progress": ["resume_interpret"],
                    }
                if _operation_expired(runtime, operation):
                    _expire_operation(runtime, operation)
                    return {"next_route": "handoff",
                            "child_result": {"status": "incomplete",
                                             "kind": "worker_deadline"},
                            "continuation": None, "progress": ["deadline_exceeded"]}
                if operation.get("raw_receipt"):
                    return {
                        "continuation": continuation,
                        "admission": {"child": continuation["child"], "phase": "dispatch",
                                      "reuse": True, "reservation_id": continuation["reservation_id"],
                                      "operation_id": operation_id, "args": continuation.get("args") or {}},
                        "next_route": "admit_action", "progress": ["resume_dispatch"],
                    }
                return {"continuation": continuation, "next_route": "await_operation",
                        "progress": ["pending_operation"]}
            if continuation.get("child"):
                return {
                    "continuation": continuation,
                    "admission": {"child": continuation["child"],
                                  "phase": continuation.get("phase"),
                                  "reuse": True,
                                  "reservation_id": continuation["reservation_id"],
                                  "operation_id": continuation.get("operation_id"),
                                  "args": continuation.get("args") or {}},
                    "next_route": "admit_action", "progress": ["resume_child"],
                }
        pending = runtime.store.pending_interaction(run_id)
        if pending:
            return {"next_route": "await_human", "pending_interaction_id": pending["id"],
                    "progress": ["pending_decision"]}
        delegation = ctx.get("delegation")
        if delegation and delegation.get("deadline"):
            deadline = parse_utc(delegation["deadline"])
            if deadline and runtime.clock.now() > deadline:
                runtime.store.append_event(run_id, "delegation_expired", role="host",
                                           payload={"delegationId": delegation["id"]})
                runtime.store.set_delegation_status(delegation["id"], "exhausted")
                return {"next_route": "handoff",
                        "child_result": {"status": "incomplete", "kind": "deadline_expired"},
                        "progress": ["deadline_expired"]}
        return {"next_route": "frame_goal", "admission": None, "continuation": None,
                "child_result": None, "plan": None, "progress": ["framing"]}

    def frame_goal(state: EngineState) -> dict:
        run_id = state["run_id"]
        ctx = _ctx(runtime, state)
        run = _run(runtime, run_id)
        decisions = _decision_map(ctx)
        collab = runtime.inputs.collaboration(run_id)
        if "endpoint_semantics" in decisions:
            if collab.get("frame_generation") != int(run["goal_generation"]):
                collab["goal_ready"] = True
                collab["frame_generation"] = int(run["goal_generation"])
                collab["requirements"] = [
                    {"id": "S1", "text": "labelled jobs"},
                    {"id": "S2", "text": "half-open endpoints: " +
                     str(decisions["endpoint_semantics"].get("optionId") or
                         decisions["endpoint_semantics"].get("definitionText"))},
                    {"id": "S3", "text": "each job at most once"},
                    {"id": "S4", "text": "maximise total reward"},
                    {"id": "S5", "text": "output the maximum value including the empty set"},
                ]
                runtime.store.update_run(run_id, collaboration_json=canonical_json(collab))
            return {"next_route": "select_action", "goal_generation": int(run["goal_generation"]),
                    "progress": ["goal_ready"]}
        # A model interpretation is optional; the host can always ask the one
        # consequential question without inventing an answer.
        reservation = runtime.store.read_one(
            "SELECT id FROM reservations WHERE run_id=? AND action_id=?",
            (run_id, f"deliberate:frame:{run['goal_generation']}"),
        )
        if reservation is None:
            reservation = _reserve(runtime, run_id,
                                   action_id=f"deliberate:frame:{run['goal_generation']}")
        outcome = None
        try:
            outcome = runtime.gateway.call(
                run_id=run_id, reservation_id=reservation["id"], node="frame_goal",
                prompt=prompt("frame_goal"),
                context={"runId": run_id, "goal": run["goal_text"][:8000], "decisions": ctx["decisions"],
                         "authorContext": contribution_context(runtime, run_id),
                         "authorArtifacts": artifact_context(runtime, run_id),
                         "conversation": conversation_context(runtime, run_id),
                         "engagement": ctx["engagement"]},
                validate=validate_with(GoalProposalV1), schema_name="GoalProposalV1",
            )
        except BudgetExhausted:
            outcome = None
        if outcome is not None and outcome.error_kind in PROVIDER_ERRORS:
            return {"child_result": {"status": "incomplete", "kind": outcome.error_kind},
                    "next_route": "handoff"}
        if outcome is not None and outcome.ok and outcome.data.open_questions:
            question = outcome.data.open_questions[0]
            model_options = question.get("options") or []
            endpoint_options = [
                {**option, "id": canonical_endpoint_option(option.get("id"))}
                for option in model_options if isinstance(option, dict)
            ]
            if len(endpoint_options) != 2 or {o["id"] for o in endpoint_options} != {"half_open", "closed"}:
                endpoint_options = []
            plan = PlanV1.model_validate({
                "action": "ask", "intent": "Clarify a consequential specification choice.",
                "args": {"interaction": {
                    "kind": "semantics",
                    "prompt": str(question.get("question") or ""),
                    "why": str(question.get("why") or
                               "The answer changes feasible solutions and dependent evidence."),
                    "options": endpoint_options or [
                        {"id": "half_open", "label": "Half-open (touching allowed)"},
                        {"id": "closed", "label": "Closed (touching conflicts)"},
                    ],
                    "recommendation": canonical_endpoint_option(question.get("recommendation")),
                    "affectedClaimIds": ["S2"],
                    "dependentOperations": ["diagnostic"],
                }},
            })
            return {"plan": plan.model_dump(), "next_route": "admit_action",
                    "progress": ["semantic_question"]}
        plan = PlanV1.model_validate({
            "action": "ask", "intent": "Ask the one consequential endpoint question.",
            "args": {"interaction": {
                "kind": "semantics",
                "prompt": "May [0,1) and [1,2) both run (a room is free exactly at the finish time)?",
                "why": "This changes feasible subsets, the predecessor comparison and all dependent evidence.",
                "options": [
                    {"id": "half_open", "label": "Half-open: yes, touching jobs are compatible",
                     "consequence": "predecessor test uses finish <= start"},
                    {"id": "closed", "label": "Closed: no, touching jobs conflict",
                     "consequence": "predecessor test uses finish < start"},
                ],
                "recommendation": None, "affectedClaimIds": ["S2"],
                "dependentOperations": ["diagnostic"],
            }},
        })
        return {"plan": plan.model_dump(), "next_route": "admit_action",
                "progress": ["semantic_question_fallback"]}

    def select_action(state: EngineState) -> dict:
        run_id = state["run_id"]
        ctx = _ctx(runtime, state)
        run = _run(runtime, run_id)
        action_id = f"deliberate:select:{run['goal_generation']}:{run['applied_author_seq']}:{run['observed_revision']}"
        delegation = ctx.get("delegation")
        case_hint = 100
        if delegation and (delegation.get("budget_ceiling") or {}).get("cases"):
            case_hint = int(delegation["budget_ceiling"]["cases"])
        try:
            reservation = _reserve(runtime, run_id, action_id=action_id,
                                   cases=case_hint)
        except BudgetExhausted:
            return {"child_result": {"status": "incomplete", "kind": "budget_exhausted"},
                    "next_route": "assess", "progress": ["budget_exhausted"]}
        evidence = [
            {"id": e["id"], "classification": e["classification"], "outcome": e["outcome"],
             "freshness": e["freshness"]}
            for e in runtime.store.list_evidence(run_id)
        ]
        outcome = runtime.gateway.call(
            run_id=run_id, reservation_id=reservation["id"], node="plan",
            prompt=prompt("plan"),
            context={
                "runId": run_id,
                "goal": run["goal_text"][:8000],
                "generation": ctx["goal_generation"],
                "revision": ctx["revision"],
                "decisions": ctx["decisions"],
                "authorContext": contribution_context(runtime, run_id),
                "authorArtifacts": artifact_context(runtime, run_id),
                "conversation": conversation_context(runtime, run_id),
                "procedureIndex": procedure_index(),
                "findings": [{"id": f["id"], "claim": f["claim_id"], "status": f["status"],
                              "severity": f["severity"]} for f in ctx["findings"]],
                "evidence": evidence,
                "delegation": ({"returnKind": delegation.get("return_kind"),
                                "returnPredicate": delegation.get("return_predicate"),
                                "permitted": delegation.get("permitted_operations"),
                                "exclusions": delegation.get("exclusions")}
                               if delegation else None),
                "grant": ctx["grant"]["operation_kinds"] if ctx["grant"] else [],
                "budget": ctx["budget"],
                "engagement": ctx["engagement"],
                "explanationDepth": ctx["explanation_depth"],
                "deliverySupported": False,
            },
            validate=validate_with(PlanV1), schema_name="PlanV1",
        )
        if not outcome.ok:
            return {"child_result": {"status": "failed",
                                     "kind": outcome.error_kind if outcome.error_kind in PROVIDER_ERRORS else "model_contract",
                                     "error": outcome.error_kind or "model failure"},
                    "next_route": "assess", "progress": ["model_failed"]}
        plan = outcome.data
        if plan.action == "collaborate" and plan.args.get("procedure") == "COL-PACKAGE":
            author = runtime.store.read_one(
                """SELECT chat_messages.id, chat_messages.text FROM chat_messages
                   JOIN inputs ON inputs.id=chat_messages.input_id
                   WHERE chat_messages.run_id=? AND chat_messages.role='author' AND inputs.status='applied'
                   AND inputs.seq<=? ORDER BY chat_messages.seq DESC LIMIT 1""",
                (run_id, ctx["applied_author_seq"]),
            )
            plan = plan.model_copy(update={"args": {
                "procedure": "COL-PACKAGE", "source_turn": (author or {}).get("id"),
                "question": (author or {}).get("text", "")[:4000],
            }, "requested_budget": {}})
        return {"plan": plan.model_dump(), "next_route": "admit_action", "progress": ["plan"]}

    def admit_action(state: EngineState) -> dict:
        run_id = state["run_id"]
        ctx = _ctx(runtime, state)
        run = _run(runtime, run_id)
        if run["status"] == "cancelled":
            return {"child_result": {"status": "cancelled", "kind": "cancelled"},
                    "next_route": "handoff"}
        admission = state.get("admission")
        if admission and admission.get("reuse"):
            persisted = json.loads(run["continuation_json"] or "null") or {}
            if (persisted.get("child") == admission.get("child")
                    and persisted.get("phase") == admission.get("phase")):
                return {"admission": admission, "next_route": admission["child"],
                        "progress": ["continuation_reused"]}
            # A stale routing channel after END must not resume an old child.
            admission = None
        raw_plan = state.get("plan")
        if not raw_plan:
            return {"child_result": {"status": "failed", "kind": "no_plan"},
                    "next_route": "assess"}
        try:
            plan = PlanV1.model_validate(raw_plan)
        except Exception as exc:  # noqa: BLE001
            return {"child_result": {"status": "failed", "kind": "invalid_plan",
                                     "error": str(exc)[:500]}, "next_route": "assess"}
        if plan.action == "ask":
            card = (plan.args or {}).get("interaction")
            if not isinstance(card, dict):
                return {"child_result": {"status": "failed", "kind": "invalid_plan"},
                        "next_route": "assess"}
            requirement = _requirement_for_card(card, ctx)
            if requirement and requirement in _decision_map(ctx) and not card.get("allow_reask"):
                # A settled question is never reissued (C11).
                return {"child_result": {"status": "complete", "kind": "redundant_question",
                                         "reason": f"{requirement} is already decided"},
                        "next_route": "assess", "progress": ["settled_question_not_reissued"]}
            interaction = _get_or_create_interaction(
                runtime, run_id, kind=str(card.get("kind") or "semantics"),
                prompt_text=str(card.get("prompt") or plan.intent),
                why=str(card.get("why") or ""),
                options=list(card.get("options") or []),
                recommendation=card.get("recommendation"),
                affected=list(card.get("affectedClaimIds") or []),
                dependent=list(card.get("dependentOperations") or []),
                evidence_refs=list(card.get("evidenceRefs") or []),
            )
            _set_continuation(runtime, run_id, action_id=sha256_text(plan.model_dump()),
                              child="await_human", phase="wait", interaction_id=interaction["id"],
                              reservation_id=None, args={})
            runtime.store.update_run(run_id, status="waiting_human",
                                     pending_interaction_id=interaction["id"])
            runtime.failpoints.hit("admit_action.after_interaction")
            return {"pending_interaction_id": interaction["id"], "next_route": "await_human",
                    "progress": ["question_issued"]}
        if plan.action == "finish":
            return {"child_result": {"status": "complete", "kind": "finish",
                                     "reason": plan.intent or "model finish request"},
                    "next_route": "assess", "progress": ["finish_requested"]}
        denial = _check_allowed_action(ctx, plan)
        if denial == "authorization_required":
            interaction = _get_or_create_interaction(
                runtime, run_id, kind="delegation",
                prompt_text=plan.intent or "Authorize this concrete repair scope?",
                why="A patch changes files; the current grant does not cover an edit.",
                options=[
                    {"id": "approve", "label": "Authorize this repair scope",
                     "consequence": "publishes one revision and invalidates dependent evidence"},
                    {"id": "reject", "label": "Keep the source unchanged",
                     "consequence": "returns a diagnostic/explanation stage"},
                ],
                recommendation=None,
                affected=list(plan.target_claim_ids),
            )
            runtime.store.update_run(run_id, status="waiting_human",
                                     pending_interaction_id=interaction["id"])
            _set_continuation(runtime, run_id, action_id=sha256_text(plan.model_dump()),
                              child="await_human", phase="wait", interaction_id=interaction["id"])
            return {"pending_interaction_id": interaction["id"], "next_route": "await_human",
                    "progress": ["edit_authorization_requested"]}
        if denial:
            return {"child_result": {"status": "failed", "kind": "admission_denied",
                                     "error": denial}, "next_route": "assess"}
        child = {"collaborate": "collaboration", "investigate": "investigation",
                 "edit": "editing", "review": "review"}[plan.action]
        phase = {"collaboration": "compose", "investigation": "design",
                 "editing": "draft", "review": "brief"}[child]
        signature = sha256_text({"action": plan.action, "args": plan.args,
                                 "generation": ctx["goal_generation"],
                                 "revision": ctx["revision"]})
        signatures = list(state.get("action_signatures") or []) + [signature]
        if signatures.count(signature) >= 3:
            return {"child_result": {"status": "incomplete", "kind": "nonprogress"},
                    "next_route": "assess", "progress": ["nonprogress_stop"]}
        try:
            reservation = _reserve(runtime, run_id, action_id="action:" + signature, plan=plan)
        except BudgetExhausted:
            return {"child_result": {"status": "incomplete", "kind": "budget_exhausted"},
                    "next_route": "assess"}
        continuation = _set_continuation(
            runtime, run_id, action_id=signature, child=child, phase=phase,
            request_hash=signature, reservation_id=reservation["id"],
            args=_admission_args(plan),
        )
        runtime.store.append_event(run_id, "action_admitted", role="host", payload={
            "action": plan.action, "child": child, "reservationId": reservation["id"],
            "intent": plan.intent, "generation": ctx["goal_generation"],
        })
        return {"admission": {"child": child, "phase": phase, "reuse": False,
                              "reservation_id": reservation["id"],
                              "args": continuation["args"], "action": plan.action},
                "continuation": continuation,
                "next_route": child, "action_signatures": signatures,
                "progress": ["action_admitted"]}

    def assess(state: EngineState) -> dict:
        run_id = state["run_id"]
        run = _run(runtime, run_id)
        result = dict(state.get("child_result") or {})
        ctx = _ctx(runtime, state)
        if run["status"] == "cancelled":
            return {"child_result": {"status": "cancelled", "kind": "cancelled"},
                    "next_route": "handoff"}
        if runtime.store.received_inputs(run_id):
            return {"next_route": "reconcile", "progress": ["new_input_reconcile"]}
        status = result.get("status")
        if status == "needs_human":
            interaction = runtime.store.pending_interaction(run_id)
            if interaction:
                return {"next_route": "await_human",
                        "pending_interaction_id": interaction["id"]}
            return {"child_result": {**result, "status": "incomplete"},
                    "next_route": "handoff"}
        if result.get("pending_operation"):
            return {"next_route": "await_operation",
                    "continuation": json.loads(run["continuation_json"] or "null")}
        if status == "conflict":
            if state.get("progress", [])[-2:] == ["conflict", "conflict"]:
                return {"next_route": "handoff", "child_result": result}
            return {"next_route": "reconcile", "progress": list(state.get("progress") or []) + ["conflict"]}
        if status in ("failed", "incomplete", "outcome_unknown"):
            return {"next_route": "handoff", "child_result": result}
        if status == "cancelled":
            return {"next_route": "handoff", "child_result": result}
        if status != "complete":
            return {"next_route": "handoff",
                    "child_result": {**result, "status": "incomplete", "kind": "unknown_result"}}
        kind = str(result.get("kind") or "")
        delegation = ctx.get("delegation")
        contract = contract_from_delegation(delegation)
        if contract is None:
            stored = _run(runtime, run_id)["stage_contract_json"]
            if stored:
                contract = StageReturnContract.model_validate(json.loads(stored))
        if contract is not None:
            stage = evaluate_stage_return(runtime.store, run_id, contract)
            if stage.satisfied:
                return {"next_route": "handoff", "stage_return": stage.model_dump(),
                        "child_result": result, "progress": ["stage_return"]}
            if delegation is None:
                return {"next_route": "handoff", "child_result": result,
                        "stage_return": stage.model_dump()}
        # A completed explanation ends the turn unless a new author goal exists.
        if kind in ("explanation", "claim_challenge", "test_validation", "package_draft", "patch_rejected"):
            return {"next_route": "handoff", "child_result": result,
                    "progress": ["turn_complete"]}
        if kind == "finish":
            return {"next_route": "handoff", "child_result": result,
                    "progress": ["author_finish"]}
        if kind == "patch":
            return {"next_route": "handoff", "child_result": result,
                    "progress": ["patch_stage"]}
        if ctx["budget"]["modelAttemptsRemaining"] <= 0:
            return {"next_route": "handoff",
                    "child_result": {**result, "status": "incomplete",
                                     "kind": "budget_exhausted"}}
        # Evidence completed; choose the next useful action (e.g. explanation).
        return {"next_route": "reconcile", "progress": ["continue"]}

    def await_human(state: EngineState) -> dict:
        run_id = state["run_id"]
        run = _run(runtime, run_id)
        if run["status"] == "cancelled":
            return {"next_route": "reconcile"}
        interaction = runtime.store.pending_interaction(run_id)
        if interaction is None:
            return {"next_route": "reconcile", "progress": ["decision_not_pending"]}
        wait_id = interaction["id"]
        wake = runtime.store.next_pending_wake(run_id, wait_id)
        if wake:
            runtime.store.mark_wake_delivered(wake["wake_id"], int(state.get("controller_epoch") or 0))
            runtime.store.consume_wake(wake["wake_id"], int(state.get("controller_epoch") or 0),
                                       wait_id=wait_id, checkpoint_ref="await_human")
            return {"wake": wake, "next_route": "reconcile",
                    "pending_interaction_id": interaction["id"]}
        envelope = interrupt({
            "wait": "human",
            "runId": run_id,
            "waitId": wait_id,
            "interactionId": interaction["id"],
            "why": interaction["why"],
            "card": {
                "kind": interaction["kind"], "prompt": interaction["prompt_ref"],
                "options": interaction["options"], "recommendation": interaction["recommendation"],
                "revision": interaction["revision"], "goalGeneration": interaction["goal_generation"],
                "proposalHash": interaction["proposal_hash"],
            },
        })
        _validate_wake(runtime, run_id, envelope, wait_id)
        runtime.failpoints.hit("await_human.after_resume")
        runtime.store.mark_wake_delivered(envelope["wake_id"], int(state.get("controller_epoch") or 0))
        runtime.store.consume_wake(envelope["wake_id"], int(state.get("controller_epoch") or 0),
                                   wait_id=wait_id, checkpoint_ref="await_human")
        return {"wake": envelope, "next_route": "reconcile"}

    def await_operation(state: EngineState) -> dict:
        run_id = state["run_id"]
        run = _run(runtime, run_id)
        if run["status"] == "cancelled":
            return {"next_route": "reconcile"}
        continuation = json.loads(run["continuation_json"] or "null") or {}
        operation_id = continuation.get("operation_id")
        if operation_id:
            operation = runtime.store.get_operation(operation_id)
            if operation["status"] in TERMINAL_OPERATION:
                return {"next_route": "reconcile", "progress": ["receipt_available"]}
        wake = runtime.store.next_pending_wake(run_id, "operation:" + str(operation_id))
        if wake is None:
            wake = runtime.store.next_pending_wake(run_id)
        if wake:
            runtime.store.mark_wake_delivered(wake["wake_id"], int(state.get("controller_epoch") or 0))
            runtime.store.consume_wake(wake["wake_id"], int(state.get("controller_epoch") or 0),
                                       wait_id="operation:" + str(operation_id),
                                       checkpoint_ref="await_operation")
            return {"wake": wake, "next_route": "reconcile"}
        envelope = interrupt({
            "wait": "operation", "runId": run_id,
            "waitId": "operation:" + str(operation_id),
            "operationId": operation_id,
            "why": "Waiting for a durable worker receipt, steering, cancellation or deadline.",
        })
        _validate_wake(runtime, run_id, envelope, "operation:" + str(operation_id))
        runtime.failpoints.hit("await_operation.after_resume")
        runtime.store.mark_wake_delivered(envelope["wake_id"], int(state.get("controller_epoch") or 0))
        runtime.store.consume_wake(envelope["wake_id"], int(state.get("controller_epoch") or 0),
                                   wait_id="operation:" + str(operation_id),
                                   checkpoint_ref="await_operation")
        return {"wake": envelope, "next_route": "reconcile"}

    def handoff(state: EngineState) -> dict:
        run_id = state["run_id"]
        run = _run(runtime, run_id)
        ctx = _ctx(runtime, state)
        result = dict(state.get("child_result") or {})
        stage = state.get("stage_return")
        if stage is None and ctx.get("delegation") is not None:
            stage = evaluate_stage_return(
                runtime.store, run_id, contract_from_delegation(ctx["delegation"])
            ).model_dump()
        if run["status"] == "cancelled":
            outcome = "cancelled"
        elif stage is not None and stage.get("satisfied"):
            outcome = "stage_returned"
        elif result.get("status") in ("failed", "incomplete", "outcome_unknown"):
            outcome = "incomplete"
        elif result.get("status") == "cancelled":
            outcome = "cancelled"
        else:
            outcome = "awaiting_author"
        handoff = _build_handoff(runtime, run_id, outcome, stage, result)
        runtime.store.add_handoff(run_id, handoff)
        runtime.store.update_run(run_id, status=("stage_returned" if outcome == "stage_returned"
                                                 else "awaiting_author" if outcome == "awaiting_author"
                                                 else "cancelled" if outcome == "cancelled"
                                                 else "incomplete"),
                                 stop_reason=result.get("kind") or outcome)
        delegation = ctx.get("delegation")
        if delegation and outcome in ("stage_returned", "incomplete"):
            runtime.store.set_delegation_status(
                delegation["id"], "returned" if outcome == "stage_returned" else "exhausted"
            )
        _clear_continuation(runtime, run_id)
        return {"handoff_ref": handoff.id, "next_route": "end", "progress": ["handoff"]}

    builder = StateGraph(EngineState)
    builder.add_node("reconcile", reconcile)
    builder.add_node("frame_goal", frame_goal)
    builder.add_node("select_action", select_action)
    builder.add_node("admit_action", admit_action)
    builder.add_node("collaboration", _child_node(runtime, build_collaboration(runtime), "collaboration"))
    builder.add_node("investigation", _child_node(runtime, build_investigation(runtime), "investigation"))
    builder.add_node("editing", _child_node(runtime, build_editing(runtime), "editing"))
    builder.add_node("review", _child_node(runtime, build_review(runtime), "review"))
    builder.add_node("assess", assess)
    builder.add_node("await_human", await_human)
    builder.add_node("await_operation", await_operation)
    builder.add_node("handoff", handoff)
    builder.add_edge(START, "reconcile")
    builder.add_conditional_edges("reconcile", _router("reconcile", "next_route"))
    builder.add_conditional_edges("frame_goal", _router("frame_goal", "next_route"))
    builder.add_conditional_edges("select_action", _router("select_action", "next_route"))
    builder.add_conditional_edges("admit_action", _router("admit_action", "next_route"))
    builder.add_edge("collaboration", "assess")
    builder.add_edge("investigation", "assess")
    builder.add_edge("editing", "assess")
    builder.add_edge("review", "assess")
    builder.add_conditional_edges("assess", _router("assess", "next_route"))
    builder.add_edge("await_human", "reconcile")
    builder.add_edge("await_operation", "reconcile")
    builder.add_edge("handoff", END)
    return builder.compile(checkpointer=checkpointer)


def _router(source: str, key: str):
    def route(state: EngineState) -> str:
        value = str(state.get(key) or "")
        if value == "end":
            value = "handoff"
        return validate_route(source, value)

    return route


def _child_node(runtime: Runtime, subgraph, name: str):
    def node(state: EngineState) -> dict:
        admission = state.get("admission") or {}
        ctx = _ctx(runtime, state)
        payload = {
            "run_id": state["run_id"],
            "ctx": ctx,
            "args": admission.get("args") or (state.get("plan") or {}).get("args") or {},
            "phase": admission.get("phase") or "start",
            "continuation": state.get("continuation"),
            "admission": admission,
        }
        try:
            persisted = json.loads(runtime.store.get_run(state["run_id"])["continuation_json"] or "{}")
        except Exception:  # noqa: BLE001
            persisted = {}
        if persisted.get("args"):
            payload["args"] = {**persisted["args"], **payload["args"]}
        try:
            out = subgraph.invoke(payload)
            result = out.get("result") or {"status": "failed", "kind": "empty_child_result"}
        except CrashInjected:
            raise
        except Exception as exc:  # noqa: BLE001 - classify child failure at the boundary
            import traceback

            detail = traceback.format_exc()[-4000:]
            runtime.store.append_event(state["run_id"], "child_error", role="host",
                                       payload={"child": name, "error": detail})
            result = {"status": "failed", "kind": "child_error",
                      "error": f"{type(exc).__name__}: {exc}", "traceback": detail}
        return {"child_result": result,
                "progress": list(state.get("progress") or []) + [name + ":" + str(result.get("kind"))]}

    return node


def _requirement_for_card(card: dict, ctx: dict) -> str | None:
    if card.get("kind") == "semantics":
        return "endpoint_semantics"
    if card.get("kind") == "approach_choice":
        return "approach_choice"
    return None


def _contribution_brief(contribution: dict) -> dict:
    return {"id": contribution["id"], "kind": contribution["kind"],
            "attribution": contribution["attribution"],
            "validation": contribution["validation_status"],
            "blobHash": contribution["original_blob_hash"]}


def _admission_args(plan: PlanV1) -> dict:
    args = dict(plan.args or {})
    if plan.action == "investigate":
        args.setdefault("claim_id", "H1")
        args.setdefault("expected_observation", plan.expected_observation)
    if plan.requested_budget:
        args.setdefault("requested_budget", dict(plan.requested_budget))
    return args


def _build_handoff(runtime: Runtime, run_id: str, outcome: str, stage: dict | None,
                   result: dict) -> HandoffV1:
    run = _run(runtime, run_id)
    collab = runtime.inputs.collaboration(run_id)
    contributions = runtime.store.list_contributions(run_id)
    evidence = runtime.store.list_evidence(run_id)
    findings = runtime.store.list_findings(run_id)
    explanation = runtime.store.current_explanation(run_id)
    budget = runtime.store.budget_view(run_id)
    open_questions = [
        f"{f['severity']}: {f['allegation']}" for f in findings
        if f["status"] in ("open", "investigating", "repair_proposed", "disputed")
    ]
    if not explanation and not any(e["freshness"] == "current" for e in evidence):
        open_questions.append("No current explanation or evidence has been committed yet.")
    completed = []
    for item in evidence:
        completed.append({"evidenceId": item["id"], "outcome": item["outcome"],
                          "classification": item["classification"],
                          "freshness": item["freshness"]})
    invalidations = [
        {"evidenceId": e["id"], "reason": "superseded generation"} for e in evidence
        if e["freshness"] == "stale"
    ]
    next_actions = [
        "Author: inspect the current explanation and evidence facets.",
        "Continue by sending a new input; a stage return does not resume by itself.",
        "Delivery/export remains unsupported in V0-V3.",
    ]
    if stage is not None and not stage.get("satisfied"):
        next_actions.insert(0, "Typed return not satisfied: " + "; ".join(stage.get("unresolved") or []))
    if result.get("status") in ("failed", "incomplete", "outcome_unknown"):
        next_actions.insert(0, f"Stage incomplete: {result.get('kind') or result.get('status')}")
    return HandoffV1(
        id="handoff-" + sha256_text({"run": run_id, "revision": run["observed_revision"],
                                     "outcome": outcome, "seq": run["applied_author_seq"]})[:14],
        goal_generation=int(run["goal_generation"]),
        revision=run["observed_revision"],
        last_applied_author_seq=int(run["applied_author_seq"]),
        outcome=outcome,
        decisions=list(collab.get("decisions") or []),
        contributions=[{"id": c["id"], "kind": c["kind"], "actorKind": c["actor_kind"],
                        "attribution": c["attribution"], "blobHash": c["original_blob_hash"],
                        "validation": c["validation_status"]} for c in contributions],
        completed_work=completed,
        open_questions=open_questions,
        current_evidence=[e["id"] for e in evidence if e["freshness"] == "current"],
        invalidations=invalidations,
        remaining_budget=budget,
        next_actions=next_actions,
        stage_return=stage,
    )


def _validate_wake(runtime: Runtime, run_id: str, envelope: Any, wait_id: str) -> None:
    if not isinstance(envelope, dict):
        raise LedgerError("resume payload is not a host wake envelope")
    wake_id = str(envelope.get("wake_id") or "")
    if not wake_id:
        raise LedgerError("resume payload lacks a wake id")
    row = runtime.store.read_one("SELECT * FROM wake_outbox WHERE wake_id=?", (wake_id,))
    if row is None or row["run_id"] != run_id:
        raise LedgerError("resume payload does not name a durable wake for this run")
    if str(envelope.get("reason") or "") not in ("response", "steering", "cancel",
                                                  "worker_receipt", "deadline"):
        raise LedgerError("forged wake reason")
    if row["reason"] != envelope.get("reason"):
        raise LedgerError("wake reason does not match the durable record")
    if row["wait_id"] not in (wait_id, "boundary"):
        raise LedgerError("wake targets a different wait")

# --------------------------------------------------------------------------- subgraphs
def _gateway(runtime: Runtime, reservation_id: str | None, *, run_id: str, node: str,
             context: dict, schema, prompt_name: str):
    if not reservation_id:
        return None
    try:
        return runtime.gateway.call(
            run_id=run_id, reservation_id=reservation_id, node=node,
            prompt=prompt(prompt_name), context=context,
            validate=validate_with(schema), schema_name=getattr(schema, "__name__", str(schema)),
        )
    except BudgetExhausted:
        return None


def _current_evidence_rows(runtime: Runtime, run_id: str) -> list[dict]:
    return [e for e in runtime.store.list_evidence(run_id) if e["freshness"] == "current"]


def _witness_evidence(runtime: Runtime, run_id: str, target_ref: str | None) -> dict | None:
    rows = _current_evidence_rows(runtime, run_id)
    if target_ref:
        for row in rows:
            if target_ref in (row["id"], *(row.get("artifact_refs") or [])):
                return row
    for row in rows:
        if row.get("classification") == "counterexample":
            return row
    return rows[-1] if rows else None


def _continuation_update(runtime: Runtime, run_id: str, **changes: Any) -> dict:
    run = runtime.store.get_run(run_id)
    continuation = json.loads(run["continuation_json"] or "{}")
    continuation.update(changes)
    runtime.store.update_run(run_id, continuation_json=canonical_json(continuation))
    return continuation


def build_collaboration(runtime: Runtime):
    def package_basis(ctx: dict) -> dict:
        return {key: ctx[key] for key in ("revision", "goal_generation", "steering_epoch", "applied_author_seq")}

    def save_package(state: CollaborationInput, package: dict) -> dict:
        _continuation_update(runtime, state["run_id"], package=package)
        return {"package": package}

    def package_failure(kind: str, *, conflict: bool = False) -> dict:
        return {"result": {"status": "conflict" if conflict else "incomplete", "kind": kind}}

    def retrieve(state: CollaborationInput) -> dict:
        args = dict(state.get("args") or {})
        ctx = state["ctx"]
        procedure = str(args.get("procedure") or "COL-EXPLAIN")
        selection = compose_selection(procedure, resource_ids=list(args.get("resources") or []))
        if "error" in selection:
            return {"result": {"status": "failed", "kind": "resource_missing",
                               "error": selection["error"]}}
        assembled = assemble(runtime, state["run_id"], procedure=procedure,
                             resource_ids=list(args.get("resources") or []),
                             contribution_ids=list(args.get("contribution_ids") or []))
        retrieved: dict[str, Any] = {
            "procedure": procedure, "selection": selection, "assembled": assembled,
            "depth": args.get("depth") or ctx.get("explanation_depth", "standard"),
            "question": args.get("question") or "",
            "target_ref": args.get("target_ref"),
            "facts": {},
        }
        run_id = state["run_id"]
        # Human test contribution validation (COL-TEST) is deterministic.
        if procedure == "COL-TEST":
            contribution_id = args.get("contribution_id")
            if contribution_id:
                claimed = args.get("expected")
                try:
                    contribution = runtime.store.get_contribution(contribution_id)
                    body = runtime.store.get_blob(contribution["original_blob_hash"]).decode("utf-8")
                    instance = parse_instance(body)
                    oracle = oracle_for(instance)
                    valid = claimed is None or int(claimed) == int(oracle["value"])
                    retrieved["test_check"] = {
                        "contributionId": contribution_id,
                        "instance": render_instance(instance),
                        "oracleValue": oracle["value"],
                        "claimed": claimed,
                        "valid": valid,
                        "reason": "" if valid else f"claimed {claimed}, oracle {oracle['value']}",
                    }
                except (InvalidInput, LedgerError, ValueError) as exc:
                    retrieved["test_check"] = {
                        "contributionId": contribution_id, "valid": False,
                        "classification": "invalid_input", "reason": str(exc),
                    }
        # A false compatibility claim is refuted with a concrete legal pair.
        if args.get("claim_check") == "compatible_prefix_all":
            claim_id = args.get("contribution_id")
            instance = _fixture_instance(str(args.get("witness") or "conflict_pair"))
            conflict = _find_conflict_pair(instance)
            retrieved["claim_check"] = {
                "claimId": claim_id, "claim": "if job i is chosen, every earlier job is compatible",
                "refuted": conflict is not None,
                "pair": conflict,
                "input": render_instance(instance),
                "classification": "counterexample" if conflict else "agreement",
            }
        if procedure == "COL-EXPLAIN":
            evidence = _witness_evidence(runtime, run_id, args.get("target_ref"))
            if evidence is None:
                retrieved["missing_evidence"] = True
            else:
                retrieved["facts"] = _facts_from_evidence(runtime, evidence)
                retrieved["evidence_id"] = evidence["id"]
        return {"retrieved": retrieved}

    def compose(state: CollaborationInput) -> dict:
        retrieved = dict(state.get("retrieved") or {})
        ctx = state["ctx"]
        admission = state.get("admission") or {}
        if retrieved.get("procedure") == "COL-PACKAGE":
            run_id = state["run_id"]
            args = state.get("args") or {}
            source_turn = args.get("source_turn")
            decision = _decision_map(ctx).get("endpoint_semantics") or {}
            semantics = canonical_endpoint_option(decision.get("optionId"))
            if not source_turn or semantics is None:
                return {"result": {"status": "incomplete", "kind": "package_draft_needs_chat_decision"}}
            action_id = (state.get("continuation") or {}).get("action_id")
            current_draft = [a for a in runtime.store.list_artifacts(run_id, current_only=True)
                             if a["provenance"].get("packageDraft") and a["revision"] == ctx["revision"]
                             and a["generation"] == ctx["goal_generation"]]
            received = [a["id"] for a in current_draft if a["provenance"].get("actionId") == action_id]
            if received:
                return {"result": {"status": "complete", "kind": "package_draft", "artifact_ids": received}}
            persisted = json.loads(runtime.store.get_run(run_id)["continuation_json"] or "{}").get("package")
            if persisted is not None:
                return ({"package": persisted} if persisted["basis"] == package_basis(ctx)
                        else package_failure("stale_draft", conflict=True))
            previous_draft = [
                {"path": a["path"], "text": runtime.store.artifact_body(a["id"]).decode("utf-8"),
                 "oracleExpected": a["provenance"].get("oracleExpected"), "sha256": a["blob_hash"]}
                for a in current_draft if a["kind"] in ("solution", "negative", "test")
            ]
            outcome = _gateway(
                runtime, admission.get("reservation_id"), run_id=run_id,
                node="collaboration.package_draft", prompt_name="collaboration.package_draft",
                context={"goal": ctx["goal_text"][:4000], "authorRequest": args.get("question"),
                         "problemTitle": runtime.store.get_run(run_id)["title"],
                         "endpointSemantics": semantics, "decisions": ctx["decisions"],
                         "previousDraft": previous_draft, "context": retrieved["assembled"]}, schema=PackageDraft,
            )
            if outcome is None or not outcome.ok:
                reason = outcome.error_kind if outcome else "budget_exhausted"
                return {"result": {"status": "incomplete", "kind": (
                    "invalid_package_draft" if reason == "schema" else reason or "model_contract"
                )}}
            instruction = unquoted(args.get("question") or "").casefold()
            author_hold = re.search(
                r"\b(?:do not|don['’]t|never|without)\s+(?:(?:automatically|actually)\s+)?(?:run|execute|compile)\b"
                r"|\b(?:before|prior to)\s+(?:running|executing|compiling)\b", instruction,
            )
            worker = runtime.worker.describe()
            allowed = _check_allowed_action(ctx, PlanV1(action="investigate")) is None
            execute = bool(worker.get("real") and worker.get("configured") and allowed and not author_hold)
            return save_package(state, {"draft": outcome.data.model_dump(), "round": 0, "basis": package_basis(ctx),
                                        "source_turn": source_turn, "action": action_id, "semantics": semantics,
                                        "decision": decision, "execute": execute})
        draft = None
        if retrieved.get("test_check") is not None or retrieved.get("claim_check") is not None:
            draft = {}
        else:
            outcome = _gateway(
                runtime, admission.get("reservation_id"), run_id=state["run_id"],
                node="collaboration.compose", prompt_name="collaboration.compose",
                context={
                    "runId": state["run_id"],
                    "procedure": retrieved.get("procedure"),
                    "selectedResources": [s["id"] for s in retrieved.get("selection", {}).get("selected", [])],
                    "selectedMethods": (retrieved.get("assembled") or {}).get("methods", {}),
                    "authorContext": (retrieved.get("assembled") or {}).get("authorContext", {}),
                    "authorArtifacts": (retrieved.get("assembled") or {}).get("authorArtifacts", {}),
                    "conversation": (retrieved.get("assembled") or {}).get("conversation", {}),
                    "procedureIndex": (retrieved.get("assembled") or {}).get("procedureIndex", []),
                    "contextBudget": {
                        "chars": (retrieved.get("assembled") or {}).get("chars"),
                        "maxChars": (retrieved.get("assembled") or {}).get("maxChars"),
                        "truncated": (retrieved.get("assembled") or {}).get("truncated"),
                    },
                    "question": retrieved.get("question"),
                    "depth": retrieved.get("depth"),
                    "facts": retrieved.get("facts"),
                    "decisions": ctx.get("decisions"),
                    "evidence": [{"id": e["id"], "classification": e["classification"]}
                                 for e in _current_evidence_rows(runtime, state["run_id"])],
                    "engagement": ctx.get("engagement"),
                },
                schema=CollaborationDraftV1,
            )
            if outcome is not None and outcome.ok:
                draft = outcome.data.model_dump()
            elif retrieved.get("missing_evidence"):
                return {"result": {"status": "needs_human", "kind": "missing_evidence",
                                   "reason": "explanation requested without a current qualified receipt"}}
            else:
                draft = {}
        return {"draft": draft}

    def package_check(state: CollaborationInput) -> dict:
        package = state["package"]
        try:
            receipt = check_reference(runtime, state["ctx"], package["action"],
                                      package_files(PackageDraft.model_validate(package["draft"]), package["semantics"]),
                                      package["semantics"], package["round"])
        except PublicationBlocked as exc:
            return package_failure(exc.kind, conflict=exc.kind in ("stale_draft", "input_barrier"))
        if receipt["status"] == "candidate_failed" and package["round"] >= MAX_REPAIRS:
            return package_failure("reference_repair_exhausted")
        if receipt["status"] not in ("pass", "candidate_failed"):
            return package_failure("package_check_" + receipt["status"])
        return {"package": {**package, "receipt": receipt}}

    def package_repair(state: CollaborationInput) -> dict:
        run_id, package = state["run_id"], state["package"]
        try:
            runtime.store.require_package_context(run_id, state["ctx"])
        except PublicationBlocked as exc:
            return package_failure(exc.kind, conflict=True)
        outcome = _gateway(
            runtime, (state.get("admission") or {}).get("reservation_id"), run_id=run_id,
            node="collaboration.package_repair", prompt_name="collaboration.package_repair",
            context={"goal": state["ctx"]["goal_text"][:4000], "endpointSemantics": package["semantics"],
                     "source": package["draft"]["solution_cpp"], "failedCheck": package["receipt"]["failure"],
                     "checkId": package["receipt"]["id"]}, schema=PackageRepair,
        )
        if not outcome or not outcome.ok:
            return package_failure((outcome.error_kind if outcome else None) or "reference_repair_budget_exhausted")
        try:
            repaired = PackageDraft.model_validate({**package["draft"], "solution_cpp": outcome.data.solution_cpp})
        except ValueError:
            return package_failure("invalid_reference_repair")
        if repaired.solution_cpp.strip() == package["draft"]["solution_cpp"].strip():
            return package_failure("reference_repair_unchanged")
        return save_package(state, {**package, "draft": repaired.model_dump(), "round": package["round"] + 1,
                                    "receipt": None})

    def package_publish(state: CollaborationInput) -> dict:
        package = state["package"]
        adapter = runtime.gateway.adapter
        provider = adapter.describe_capabilities().get("model") if hasattr(adapter, "describe_capabilities") else None
        try:
            ids = runtime.store.publish_package_draft(
                state["run_id"], package_files(PackageDraft.model_validate(package["draft"]), package["semantics"]),
                context=state["ctx"], source_turn=package["source_turn"], action_id=package["action"],
                model=provider or runtime.model_name, endpoint_decision=package["decision"], check=package.get("receipt"),
            )
        except PublicationBlocked as exc:
            return package_failure(exc.kind, conflict=exc.kind in ("stale_draft", "input_barrier"))
        return {"result": {"status": "complete", "kind": "package_draft", "artifact_ids": ids}}

    def validate(state: CollaborationInput) -> dict:
        run_id = state["run_id"]
        retrieved = dict(state.get("retrieved") or {})
        draft = dict(state.get("draft") or {})
        ctx = state["ctx"]
        if state.get("result") is not None:
            return {"result": state["result"]}
        if retrieved.get("missing_evidence"):
            return {"result": {"status": "needs_human", "kind": "missing_evidence"}}
        if retrieved.get("test_check") is not None:
            check = retrieved["test_check"]
            contribution_id = check.get("contributionId")
            if contribution_id:
                runtime.store.set_contribution_validation(
                    contribution_id, "valid" if check.get("valid") else "invalid"
                )
                contribution = runtime.store.get_contribution(contribution_id)
                invalid = check.get("classification") == "invalid_input" or "required" in str(check.get("reason"))
                finding = FindingV1(
                    id="finding-" + sha256_text({"run": run_id, "contrib": contribution_id})[:12],
                    claim_id=contribution_id, revision=contribution["revision"],
                    origin_role="host", severity="medium",
                    allegation=(("Invalid test input: " + str(check.get("reason")))
                                if invalid else
                                ("Test expectation conflicts with the independent oracle: "
                                 + str(check.get("reason") if not check.get("valid") else "valid test"))),
                    evidence_refs=[], status="open" if not check.get("valid") else "resolved",
                    disposition_reason=check.get("reason"),
                    resolver_kind="deterministic",
                )
                runtime.store.upsert_finding(run_id, finding)
            return {"result": {"status": "complete", "kind": "test_validation", "check": check,
                               "finding_id": finding.id if contribution_id else None}}
        if retrieved.get("claim_check") is not None:
            check = dict(retrieved["claim_check"])
            claim_id = check.get("claimId")
            finding = None
            if check.get("refuted"):
                pair = check.get("pair") or {}
                finding = FindingV1(
                    id="finding-" + sha256_text({"run": run_id, "claim": claim_id, "pair": pair})[:12],
                    claim_id=claim_id, revision=ctx["revision"], origin_role="host",
                    severity="high",
                    allegation=("Claim refuted: selected job i can be compatible with an earlier overlapping "
                                "job. Conflicting pair " + json.dumps(pair)),
                    evidence_refs=[], suggested_discriminator="Use the compatible prefix p(i).",
                    status="open", resolver_kind="deterministic",
                )
                runtime.store.upsert_finding(run_id, finding)
            contribution_snippet = dict(draft)
            explanation = ExplanationV1(
                id="expl-" + sha256_text({"run": run_id, "claim": claim_id, "rev": ctx["revision"]})[:12],
                revision=ctx["revision"], claim_refs=[claim_id] if claim_id else [],
                audience_depth=ctx.get("explanation_depth", "standard"),
                question=retrieved.get("question") or "Challenge the disputed compatibility claim",
                short_answer=(
                    "The valid exclude-case lemma is preserved and credited. The added claim that every earlier "
                    "job is compatible is false: under half-open semantics two overlapping earlier jobs can both "
                    "precede i. Replace only that clause with the compatible-prefix statement."
                ),
                worked_example_ref=check.get("input"),
                assumption_to_code_links=[{"assumption": "half-open compatibility; finish-sorted jobs",
                                           "code_ref": "predecessor lower_bound/upper_bound span",
                                           "line_span": ""}],
                evidence_refs=[],
                alternatives=["restate the recurrence over p(i) without the false clause"],
                uncertainty=["the full optimality induction remains a proof obligation"],
                next_author_actions=["review the corrected prefix claim", "accept or dispute the finding"],
            )
            runtime.store.add_explanation(run_id, explanation)
            return {"result": {"status": "complete", "kind": "claim_challenge",
                               "finding_id": finding.id if finding else None,
                               "explanation_id": explanation.id, "claim_refuted": bool(finding)}}
        facts = dict(retrieved.get("facts") or {})
        depth = retrieved.get("depth") or "standard"
        evidence_id = retrieved.get("evidence_id")
        links = list(depth_links(depth, facts))
        uncertainty = list(draft.get("uncertainty") or [])
        if facts.get("classification") != "counterexample":
            uncertainty.append("no disagreement is established; agreement is bounded to the recorded domain")
        short = str(draft.get("short_answer") or "").strip()
        headline = facts.get("headline") or "No current diagnostic witness is available."
        if short:
            headline = headline + " " + short
        explanation = ExplanationV1(
            id="expl-" + sha256_text({"run": run_id, "evidence": evidence_id,
                                      "rev": ctx["revision"], "q": retrieved.get("question")})[:12],
            revision=ctx["revision"],
            claim_refs=[facts.get("claim_id")] if facts.get("claim_id") else [],
            audience_depth=depth,
            question=retrieved.get("question") or "Explain the current diagnostic",
            short_answer=headline,
            worked_example_ref=facts.get("input"),
            assumption_to_code_links=links,
            evidence_refs=[evidence_id] if evidence_id else [],
            alternatives=list(draft.get("alternatives") or []),
            uncertainty=uncertainty,
            next_author_actions=list(draft.get("next_author_actions") or
                                     facts.get("next_author_actions") or []),
        )
        runtime.store.add_explanation(run_id, explanation)
        return {"result": {"status": "complete", "kind": "explanation",
                           "explanation_id": explanation.id, "facts": facts}}

    builder = StateGraph(CollaborationInput)
    builder.add_node("retrieve", retrieve)
    builder.add_node("compose", compose)
    builder.add_node("validate", validate)
    builder.add_node("package_check", package_check)
    builder.add_node("package_repair", package_repair)
    builder.add_node("package_publish", package_publish)
    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", "compose")
    builder.add_conditional_edges("compose", lambda state: (
        "validate" if not state.get("package") else "package_check" if state["package"]["execute"] else "package_publish"
    ), ["validate", "package_check", "package_publish"])
    builder.add_conditional_edges("package_check", lambda state: (
        END if state.get("result") else "package_publish" if state["package"]["receipt"]["status"] == "pass" else "package_repair"
    ), [END, "package_publish", "package_repair"])
    builder.add_conditional_edges("package_repair", lambda state: END if state.get("result") else "package_check",
                                  [END, "package_check"])
    builder.add_edge("package_publish", END)
    builder.add_edge("validate", END)
    return builder.compile()


def depth_links(depth: str, facts: dict) -> list[dict]:
    if depth == "brief" or not facts:
        return []
    links = []
    if facts.get("assumption"):
        links.append({"assumption": facts["assumption"],
                      "code_ref": facts.get("code_ref") or "candidate source",
                      "line_span": facts.get("code_span") or ""})
    if depth == "detailed":
        links.append({"assumption": "optimality induction over the compatible prefix",
                      "code_ref": "p(i) predecessor search", "line_span": ""})
    return links


def _facts_from_evidence(runtime: Runtime, evidence: dict) -> dict:
    artifacts = evidence.get("artifact_refs") or []
    facts: dict[str, Any] = {
        "evidence_id": evidence["id"],
        "classification": evidence["classification"],
        "claim_id": "H1" if evidence["classification"] == "counterexample" else None,
        "next_author_actions": ["inspect the receipt", "request a repair review only if the claim is refuted"],
    }
    for ref in artifacts:
        try:
            body = runtime.store.get_blob(ref)
            payload = json.loads(body.decode("utf-8"))
        except (LedgerError, json.JSONDecodeError):
            continue
        if payload.get("kind") == "diagnostic_witness":
            facts.update({
                "input": payload.get("input"),
                "expected": payload.get("expected"),
                "actual": payload.get("actual"),
                "legal": payload.get("legal", True),
                "assumption": payload.get("assumption"),
                "invariant": payload.get("invariant"),
                "code_spans": payload.get("code_spans") or [],
                "code_ref": (payload.get("code_spans") or [{}])[0].get("text") if payload.get("code_spans") else "",
                "code_span": (f"line {payload.get('code_spans')[0].get('line')}"
                              if payload.get("code_spans") else ""),
                "comparison": payload.get("comparison"),
            })
            facts["headline"] = (
                f"On the legal input {payload.get('input')!r}, the independent subset oracle gives "
                f"{payload.get('expected')} while the candidate returns {payload.get('actual')}. "
                f"The first violated invariant is: {payload.get('invariant') or payload.get('comparison')}."
            )
    if "input" not in facts and evidence["outcome"] == "campaign":
        facts["headline"] = (
            f"The candidate agreed with the subset oracle on the declared finite domain "
            f"({evidence.get('usage_observed', {}).get('completed', '?')} cases completed). "
            "This is bounded executable agreement, not a proof."
        )
        facts["next_author_actions"] = ["inspect the campaign receipt", "state the remaining proof obligation"]
    return facts


def _fixture_instance(name: str) -> Instance:
    if name == "conflict_pair":
        return Instance((Job(0, 3, 5, 0), Job(2, 4, 6, 1)))
    if name in FIXTURE_SOURCES:
        return FIXTURE_SOURCES[name]()
    raise LedgerError(f"unknown fixture {name!r}")


def _find_conflict_pair(instance: Instance) -> dict | None:
    # The claim is about "earlier" jobs overlapping a chosen later job.
    for i in range(instance.n):
        for j in range(i):
            a, b = instance.jobs[j], instance.jobs[i]
            if not (a.finish <= b.start or b.finish <= a.start):
                return {"earlier": j, "later": i, "earlierJob": [a.start, a.finish, a.reward],
                        "laterJob": [b.start, b.finish, b.reward]}
    return None

def _build_instances(spec: dict, case_cap: int) -> list[Instance]:
    kind = str((spec or {}).get("kind") or "witness")
    if kind in ("witness", "named"):
        return [_fixture_instance(str(spec.get("name") or "weighted_greedy"))]
    if kind == "instance":
        return [_instance_from_json(spec)]
    if kind == "cases":
        return [_instance_from_json(entry) for entry in (spec.get("instances") or [])[:case_cap]]
    if kind == "finite":
        types = tuple(tuple(int(x) for x in entry) for entry in (spec.get("types") or
                     [(0, 1, 1), (1, 2, 1), (0, 2, 3), (0, 1, 3), (1, 2, 3), (0, 2, 1)]))
        lengths = tuple(int(x) for x in (spec.get("lengths") or (1, 2, 3, 4)))
        if any(n < 1 or n > 20 for n in lengths):
            raise InvalidInput("finite domain lengths must be within the oracle bound of 1 to 20 jobs")
        return finite_domain(types, lengths, limit=case_cap)
    if kind in ("default_finite", "domain"):
        return finite_domain()[:case_cap]
    raise InvalidInput(f"unknown domain kind {kind!r}")


def _instance_from_json(value: dict) -> Instance:
    jobs = []
    raw_jobs = value.get("jobs") if isinstance(value, dict) else None
    if raw_jobs is None:
        raise InvalidInput("instance needs a jobs list")
    for label, job in enumerate(raw_jobs):
        if isinstance(job, dict):
            start, finish, reward = int(job["start"]), int(job["finish"]), int(job["reward"])
        else:
            start, finish, reward = (int(job[0]), int(job[1]), int(job[2]))
        jobs.append(Job(start, finish, reward, label))
    instance = Instance(tuple(jobs))
    tokens = 1 + 3 * instance.n
    parsed = parse_instance(render_instance(instance))
    if parsed.n != instance.n or tokens != 1 + 3 * parsed.n:
        raise InvalidInput("instance did not round-trip")
    return instance


def _operation_expired(runtime: "Runtime", operation: dict) -> bool:
    if not operation.get("dispatched_at"):
        return False
    try:
        reservation = runtime.store.get_reservation(operation["reservation_id"])
    except LedgerError:
        return False
    started = parse_utc(operation["dispatched_at"])
    if started is None:
        return False
    import datetime as _dt

    deadline = started + _dt.timedelta(milliseconds=max(1, int(reservation["wall_ms"] or 90_000)))
    return runtime.clock.now() >= deadline


def _expire_operation(runtime: "Runtime", operation: dict) -> None:
    job_id = operation.get("job_id")
    cancel = getattr(runtime.worker, "cancel", None)
    confirmed = False
    if cancel is not None and job_id:
        try:
            confirmed = bool(cancel(job_id))
        except Exception:  # noqa: BLE001
            confirmed = False
    runtime.store.mark_operation_status(
        operation["operation_id"], "incomplete", classification="worker_deadline")
    runtime.store.commit_operation_result(operation["operation_id"], OperationResultV1(
        operation_id=operation["operation_id"], request_hash=operation["request_hash"],
        input_revision=operation["input_revision"], status="incomplete",
        classification="worker_deadline", error_code="deadline_exceeded",
        retryability="resumable",
    ))
    runtime.store.append_event(operation["run_id"], "operation_deadline", role="host",
                               payload={"operationId": operation["operation_id"],
                                        "workerCancelled": confirmed})


def _cancel_worker_operations(runtime: "Runtime", run_id: str) -> list[dict]:
    out = []
    cancel = getattr(runtime.worker, "cancel", None)
    for operation in runtime.store.list_operations(run_id):
        if operation["status"] not in ("admitted", "pending"):
            continue
        job_id = operation.get("job_id")
        confirmed = False
        if cancel is not None and job_id:
            try:
                confirmed = bool(cancel(job_id))
            except Exception:  # noqa: BLE001
                confirmed = False
        status = "cancelled" if confirmed else "outcome_unknown"
        classification = "cancelled_by_user" if confirmed else "cancellation_unconfirmed"
        runtime.store.mark_operation_status(operation["operation_id"], status,
                                            classification=classification)
        runtime.store.commit_operation_result(operation["operation_id"], OperationResultV1(
            operation_id=operation["operation_id"], request_hash=operation["request_hash"],
            input_revision=operation["input_revision"], status=status,
            classification=classification, retryability="not_retryable",
        ))
        runtime.store.append_event(run_id, "worker_cancel", role="host",
                                   payload={"operationId": operation["operation_id"],
                                            "confirmed": confirmed})
        out.append({"operationId": operation["operation_id"], "status": status,
                    "confirmed": confirmed})
    return out


def _publication_fence(runtime: Runtime, operation: dict, writer_epoch: int,
                       run: dict) -> tuple[bool, list[str]]:
    from .policy import operation_supported

    reasons: list[str] = []
    if int(writer_epoch) != int(run["controller_epoch"]):
        reasons.append("controller_epoch")
    if int(operation["goal_generation"]) != int(run["goal_generation"]):
        reasons.append("goal_generation")
    if str(operation["input_revision"]) != str(run["observed_revision"]):
        reasons.append("revision")
    grant = runtime.store.active_grant(run["run_id"])
    grant_kinds = list((grant or {}).get("operation_kinds") or [])
    if not operation_supported(str(operation["kind"]), grant_kinds):
        reasons.append("capability")
    pending_barrier = [i for i in runtime.store.list_inputs(run["run_id"])
                       if i["status"] in ("received", "interpreting") and i["barrier"]]
    if pending_barrier:
        reasons.append("pending_barrier")
    if int(operation["steering_epoch"]) != int(run["steering_epoch"]):
        continuation = json.loads(run["continuation_json"] or "null") or {}
        rebased = (continuation.get("operation_id") == operation["operation_id"] and
                   int(continuation.get("steering_epoch") or -1) == int(run["steering_epoch"]))
        if not rebased:
            reasons.append("steering_epoch")
    return (not reasons), reasons


def _evaluate_campaign(runtime: Runtime, raw: dict, instances: list[Instance],
                       semantics: str = "half_open") -> dict:
    declared = len(instances)
    cases = raw.get("cases") or []
    attempted = len(cases)
    valid = completed = 0
    first = None
    for index, case in enumerate(cases):
        if index >= declared:
            break
        instance = instances[index]
        oracle = oracle_for(instance, semantics=semantics)
        if case.get("status") != "ok":
            valid = valid  # an execution failure is not agreement
            if first is None:
                first = {"caseId": case.get("case_id"), "classification": case.get("status"),
                         "error": case.get("error"), "input": render_instance(instance)}
            continue
        valid += 1
        completed += 1
        text = str(case.get("output") or "").strip()
        if not re.fullmatch(r"-?\d+", text):
            if first is None:
                first = {"caseId": case.get("case_id"), "classification": "invalid_output",
                         "output": text[:80], "input": render_instance(instance)}
            continue
        if int(text) != int(oracle["value"]):
            if first is None:
                first = {"caseId": case.get("case_id"), "classification": "counterexample",
                         "input": render_instance(instance), "expected": oracle["value"],
                         "actual": int(text), "comparison": f"expected {oracle['value']}, got {text}"}
    complete = raw.get("status") == "completed" and attempted >= declared and \
        not raw.get("truncation") and completed == declared
    if first is not None and first.get("classification") == "counterexample":
        classification = "counterexample"
    elif first is not None:
        classification = first.get("classification") or "worker_error"
    elif complete:
        classification = "agreement"
    elif raw.get("status") in ("failed", "incomplete"):
        classification = str(raw.get("classification") or "incomplete")
    else:
        classification = "incomplete"
    return {"attempted": attempted, "valid": valid, "completed": completed,
            "declared": declared, "complete": complete, "first_mismatch": first,
            "classification": classification}


def _witness_artifact(runtime: Runtime, run_id: str, plan: dict, raw: dict, instances: list[Instance],
                      evaluation: dict) -> dict:
    instance = instances[0]
    oracle = oracle_for(instance)
    case = (raw.get("cases") or [{}])[0]
    actual = None
    try:
        actual = int(str(case.get("output")).strip())
    except (TypeError, ValueError):
        actual = case.get("output")
    ref = str(plan.get("candidate_ref") or "")
    spans = _code_spans(runtime, run_id, plan.get("candidate_ref"))
    if "greedy" in ref or "earliest" in ref:
        invariant = ("the earliest-finish greedy exchange preserves job count but not total reward; "
                     "the long interval's weight is lost")
    elif any("<" in s.get("text", "") and "<=" not in s.get("text", "") and "finish" in s.get("text", "")
             for s in spans):
        invariant = ("the predecessor test uses strict finish < start, so it rejects a legal touching "
                     "predecessor under half-open semantics")
    elif "base" in ref:
        invariant = "the DP base/index mapping reads the wrong compatible prefix"
    else:
        invariant = "the candidate differs from the independently enumerated subset optimum"
    return {
        "kind": "diagnostic_witness",
        "input": render_instance(instance),
        "legal": True,
        "expected": oracle["value"],
        "actual": actual,
        "candidateRef": plan.get("candidate_ref"),
        "claimId": plan.get("claim_id") or "H1",
        "classification": evaluation.get("classification"),
        "comparison": (evaluation.get("first_mismatch") or {}).get("comparison")
        or ("agreement on this witness" if evaluation.get("classification") == "agreement" else ""),
        "invariant": invariant,
        "assumption": "half-open endpoints; finish <= start is compatible",
        "code_spans": spans,
    }


def _code_spans(runtime: Runtime, run_id: str, candidate_ref: str | None) -> list[dict]:
    try:
        _, source, _ = runtime.candidate_source(run_id, candidate_ref)
    except (LedgerError, ValueError):
        return []
    from .diagnostic import code_spans
    return code_spans(source)


def _publish_diagnostic(runtime: Runtime, operation: dict, raw: dict, plan: dict,
                        instances: list[Instance], writer_epoch: int) -> dict:
    run = runtime.store.get_run(operation["run_id"])
    allowed, reasons = _publication_fence(runtime, operation, writer_epoch, run)
    raw_blob = runtime.store.put_blob(canonical_json(raw).encode("utf-8"), kind="worker-receipt")
    if raw.get("status") == "outcome_unknown":
        result = OperationResultV1(
            operation_id=operation["operation_id"], request_hash=operation["request_hash"],
            input_revision=operation["input_revision"], status="outcome_unknown",
            classification="infrastructure_error",
            artifacts={"rawReceipt": raw_blob}, usage={"unknown": True},
            error_code="worker_outcome_unknown", retryability="resumable",
        )
        runtime.store.commit_operation_result(operation["operation_id"], result)
        runtime.store.append_event(operation["run_id"], "worker_outcome_unknown", role="worker",
                                   payload={"operationId": operation["operation_id"],
                                            "rawReceipt": raw_blob})
        return {"status": "failed", "kind": "outcome_unknown", "rawReceipt": raw_blob,
                "result": result.model_dump()}
    if raw.get("status") == "cancelled":
        result = OperationResultV1(
            operation_id=operation["operation_id"], request_hash=operation["request_hash"],
            input_revision=operation["input_revision"], status="cancelled",
            classification="cancelled_by_user", artifacts={"rawReceipt": raw_blob},
            retryability="not_retryable",
        )
        runtime.store.commit_operation_result(operation["operation_id"], result)
        runtime.store.append_event(operation["run_id"], "worker_cancelled", role="worker",
                                   payload={"operationId": operation["operation_id"],
                                            "rawReceipt": raw_blob})
        return {"status": "cancelled", "kind": "cancelled", "rawReceipt": raw_blob,
                "result": result.model_dump()}
    evaluation = _evaluate_campaign(runtime, raw, instances,
                                    plan.get("oracle_semantics") or "half_open")
    is_single = len(instances) == 1 and str(plan.get("domain", {}).get("kind") or "witness") not in (
        "finite", "cases", "default_finite")
    if is_single:
        instance = instances[0]
        case = (raw.get("cases") or [{}])[0]
        mismatch = None
        semantics = plan.get("oracle_semantics") or "half_open"
        text_value = str(case.get("output") or "").strip()
        oracle_value = oracle_for(instance, semantics=semantics)["value"]
        product_value = oracle_for(instance)["value"]
        shared = False
        if case.get("status") != "ok":
            mismatch = f"{case.get('status')}: {case.get('error') or case.get('message')}"
            classification = case.get("status") or raw.get("classification") or "worker_error"
        elif not re.fullmatch(r"-?\d+", text_value):
            mismatch = "candidate output is not a single integer"
            classification = "invalid_output"
        elif int(text_value) != int(oracle_value):
            mismatch = f"expected {oracle_value}, candidate returned {text_value}"
            classification = "counterexample"
        elif semantics != "half_open" and int(product_value) != int(oracle_value):
            classification = "shared_semantics_defect"
            shared = True
            mismatch = (
                f"both the supplied oracle ({oracle_value}) and the candidate ({text_value}) use "
                f"the {semantics} convention; the product half-open reading is {product_value}"
            )
        else:
            classification = "agreement"
        artifact = _witness_artifact(runtime, operation["run_id"], plan, raw, instances, {
            "classification": classification,
            "first_mismatch": {"comparison": mismatch} if mismatch else None,
        })
        artifact.update({"oracleSemantics": semantics, "productExpected": product_value,
                         "sharedSemanticsDefect": shared})
        if shared:
            artifact["expected"] = oracle_value
            artifact["actual"] = text_value
        artifact_blob = runtime.store.put_blob(canonical_json(artifact).encode("utf-8"),
                                               kind="witness")
        evidence = EvidenceV1(
            id="ev-" + sha256_text({"run": operation["run_id"], "op": operation["operation_id"]})[:14],
            producer_kind="deterministic",
            producer_version="worker+subset-oracle-v1",
            operation_id=operation["operation_id"],
            input_refs=[artifact_blob],
            dependency_hashes={"candidate": str(plan.get("candidate_ref")),
                               "semantics": plan.get("oracle_semantics") or "half_open"},
            domain=str(plan.get("domain", {}).get("kind") or "witness"),
            budget_requested=plan.get("budget") or {},
            usage_observed={"cases": 1, "complete": True, "claimId": plan.get("claim_id") or "H1"},
            outcome="witness" if classification == "counterexample" else "failure",
            artifact_refs=[artifact_blob],
            environment_ref=raw.get("worker_identity"),
            freshness="current" if allowed else "stale",
            classification=classification,
        )
        if not allowed:
            evidence = EvidenceV1(**{
                **evidence.model_dump(), "freshness": "stale", "outcome": "stale_receipt",
                "visibility": "author", "classification": "counterexample" if mismatch else "agreement",
            })
        result = OperationResultV1(
            operation_id=operation["operation_id"], request_hash=operation["request_hash"],
            input_revision=operation["input_revision"],
            status="completed" if allowed else "incomplete",
            classification=classification if allowed else "stale",
            actual_limits={"cases": 1}, usage={"cases": 1},
            artifacts={"witness": artifact_blob, "rawReceipt": raw_blob},
            evidence_ids=[evidence.id], worker_identity=raw.get("worker_identity"),
            retryability="not_retryable",
        )
        runtime.store.commit_operation_result(operation["operation_id"], result, evidence)
        if not allowed:
            runtime.store.append_event(operation["run_id"], "publication_denied", role="host",
                                       payload={"operationId": operation["operation_id"],
                                                "reasons": reasons, "rawReceipt": raw_blob})
            return {"status": "conflict", "kind": "stale_publication", "reasons": reasons,
                    "evidence_id": evidence.id, "artifact": artifact,
                    "rawReceipt": raw_blob, "result": result.model_dump()}
        return {"status": "complete", "kind": "diagnostic", "classification": classification,
                "evidence_id": evidence.id, "artifact": artifact, "artifactBlob": artifact_blob,
                "rawReceipt": raw_blob, "result": result.model_dump(), "evaluation": evaluation}

    # Campaign (multi-case) publication.
    artifact = {
        "kind": "campaign_report",
        "declared": evaluation["declared"], "attempted": evaluation["attempted"],
        "valid": evaluation["valid"], "completed": evaluation["completed"],
        "complete": evaluation["complete"], "classification": evaluation["classification"],
        "firstMismatch": evaluation["first_mismatch"],
        "candidateRef": plan.get("candidate_ref"),
    }
    artifact_blob = runtime.store.put_blob(canonical_json(artifact).encode("utf-8"),
                                           kind="campaign")
    evidence = EvidenceV1(
        id="ev-" + sha256_text({"run": operation["run_id"], "op": operation["operation_id"]})[:14],
        producer_kind="deterministic", producer_version="worker+subset-oracle-v1",
        operation_id=operation["operation_id"], input_refs=[artifact_blob],
        dependency_hashes={"candidate": str(plan.get("candidate_ref"))},
        domain=str(plan.get("domain", {}).get("kind") or "finite"),
        budget_requested=plan.get("budget") or {},
        usage_observed={"cases": evaluation["attempted"],
                        "complete": evaluation["complete"],
                        "completed": evaluation["completed"],
                        "declared": evaluation["declared"],
                        "claimId": plan.get("claim_id") or "H1"},
        outcome="campaign", artifact_refs=[artifact_blob],
        environment_ref=raw.get("worker_identity"),
        freshness="current" if allowed else "stale",
        classification=evaluation["classification"],
    )
    result = OperationResultV1(
        operation_id=operation["operation_id"], request_hash=operation["request_hash"],
        input_revision=operation["input_revision"],
        status="completed" if allowed else "incomplete",
        classification=evaluation["classification"] if allowed else "stale",
        actual_limits={"cases": evaluation["attempted"]},
        usage={"cases": evaluation["attempted"]},
        artifacts={"campaign": artifact_blob, "rawReceipt": raw_blob},
        truncation=raw.get("truncation") or {},
        evidence_ids=[evidence.id], worker_identity=raw.get("worker_identity"),
        retryability="not_retryable",
    )
    runtime.store.commit_operation_result(operation["operation_id"], result, evidence)
    if not allowed:
        runtime.store.append_event(operation["run_id"], "publication_denied", role="host",
                                   payload={"operationId": operation["operation_id"],
                                            "reasons": reasons, "rawReceipt": raw_blob})
        return {"status": "conflict", "kind": "stale_publication", "reasons": reasons,
                "evidence_id": evidence.id, "artifact": artifact, "rawReceipt": raw_blob,
                "result": result.model_dump()}
    return {"status": "complete", "kind": "diagnostic",
            "classification": evaluation["classification"], "evidence_id": evidence.id,
            "artifact": artifact, "artifactBlob": artifact_blob, "rawReceipt": raw_blob,
            "result": result.model_dump(), "evaluation": evaluation}

def build_investigation(runtime: Runtime):
    def route_phase(state: InvestigationInput) -> dict:
        phase = str(state.get("phase") or "design")
        return {"next_phase": phase if phase in ("design", "qualify", "dispatch", "interpret") else "design"}

    def design(state: InvestigationInput) -> dict:
        args = dict(state.get("args") or {})
        ctx = state["ctx"]
        design = dict(args)
        needed = {"candidate_ref", "domain"}
        if not needed.issubset(design):
            outcome = _gateway(
                runtime, (state.get("admission") or {}).get("reservation_id"),
                run_id=state["run_id"], node="investigation.design",
                prompt_name="investigation.design",
                context={"goal": ctx.get("goal_text"), "claim": args.get("claim_text"),
                         "authorAlternative": args.get("approach"),
                         "decisions": ctx.get("decisions"),
                         "authorContext": contribution_context(runtime, state["run_id"]),
                         "authorArtifacts": artifact_context(runtime, state["run_id"]),
                         "conversation": conversation_context(runtime, state["run_id"]),
                         "budget": ctx.get("budget")},
                schema=InvestigationDesign,)
            if outcome is None or not outcome.ok:
                return {"result": {"status": "failed", "kind": "model_contract",
                                   "error": "discriminator design unavailable"}}
            design = outcome.data.model_dump()
        design.setdefault("claim_id", args.get("claim_id") or "H1")
        design["candidate_ref"] = design.get("candidate_ref") or args.get("candidate_ref")
        design["domain"] = design.get("domain") or args.get("domain") or {"kind": "witness",
                                                                         "name": "weighted_greedy"}
        if not design.get("candidate_ref"):
            return {"result": {"status": "failed", "kind": "invalid_plan",
                               "error": "no candidate reference"}}
        domain = design["domain"]
        if isinstance(domain, dict) and "kind" not in domain and design.get("targeted_cases"):
            # Older live plans put actual cases beside a prose domain. Keep only
            # the explicit inputs and compute expectations independently.
            try:
                targeted = design["targeted_cases"]
                if not isinstance(targeted, list) or not 1 <= len(targeted) <= 32:
                    raise ValueError("targeted_cases must contain 1 to 32 explicit inputs")
                design["domain"] = {"kind": "cases", "instances": [
                    {"jobs": [[j.start, j.finish, j.reward] for j in parse_instance(case["input"]).jobs]}
                    for case in targeted
                ]}
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                return {"result": {"status": "failed", "kind": "invalid_input", "error": str(exc)[:500]}}
        elif not isinstance(domain, dict) or not domain.get("kind"):
            return {"result": {"status": "failed", "kind": "invalid_input",
                               "error": "investigation requires a structured domain with a kind"}}
        if args.get("requested_budget") and "requested_budget" not in design:
            design["requested_budget"] = args["requested_budget"]
        _continuation_update(runtime, state["run_id"], args=design)
        return {"plan": design, "next_phase": "qualify"}

    def qualify(state: InvestigationInput) -> dict:
        plan = dict(state.get("plan") or {})
        ctx = state["ctx"]
        run_id = state["run_id"]
        try:
            ref, _, label = runtime.candidate_source(run_id, plan["candidate_ref"])
        except (LedgerError, ValueError) as exc:
            return {"result": {"status": "failed", "kind": "invalid_candidate",
                               "error": str(exc)[:500]}}
        plan["candidate_ref"] = ref
        case_cap = int((plan.get("requested_budget") or {}).get("cases") or 1)
        delegation = ctx.get("delegation")
        if delegation:
            ceiling = (delegation.get("budget_ceiling") or {}).get("cases")
            if ceiling:
                case_cap = min(case_cap, int(ceiling))
        budget = runtime.store.get_budget(run_id)
        remaining_cases = int(budget["cases_limit"]) - int(budget["cases_used"])
        case_cap = min(case_cap, remaining_cases)
        if case_cap < 1:
            return {"result": {"status": "incomplete", "kind": "budget_exhausted"}}
        try:
            instances = _build_instances(plan.get("domain") or {}, case_cap)
        except (InvalidInput, ValueError, KeyError, TypeError) as exc:
            return {"result": {"status": "failed", "kind": "invalid_input",
                               "error": str(exc)[:500]}}
        if not instances:
            return {"result": {"status": "failed", "kind": "invalid_input",
                               "error": "empty domain"}}
        for instance in instances:
            try:
                parse_instance(render_instance(instance))
                if instance.n > 20:
                    raise InvalidInput("oracle enumeration is bounded to 20 jobs")
            except InvalidInput as exc:
                return {"result": {"status": "failed", "kind": "invalid_input",
                                   "error": str(exc)[:500]}}
        # The admitted action owns one reservation; qualification reuses it.
        plan["cases"] = [render_instance(instance) for instance in instances]
        plan["budget"] = {"cases": len(instances), "wall_ms": 60_000,
                          "memory_mib": 256, "output_bytes": 1_048_576}
        _continuation_update(runtime, run_id, args={**plan, "candidate_label": label})
        return {"plan": plan, "next_phase": "dispatch"}

    def dispatch(state: InvestigationInput) -> dict:
        plan = dict(state.get("plan") or {})
        run_id = state["run_id"]
        admission = state.get("admission") or {}
        ctx = state["ctx"]
        reservation_id = admission.get("reservation_id") or (state.get("continuation") or {}).get("reservation_id")
        if not reservation_id:
            return {"result": {"status": "failed", "kind": "missing_reservation"}}
        if not plan.get("cases"):
            plan = dict((json.loads(runtime.store.get_run(run_id)["continuation_json"] or "{}")
                         .get("args") or {}))
        instances = [parse_instance(text) for text in plan.get("cases") or []]
        try:
            _, source, _ = runtime.candidate_source(run_id, plan.get("candidate_ref"))
        except (LedgerError, ValueError) as exc:
            return {"result": {"status": "failed", "kind": "invalid_candidate",
                               "error": str(exc)[:500]}}
        run = runtime.store.get_run(run_id)
        request_hash = sha256_text({
            "candidate": plan.get("candidate_ref"),
            "cases": plan.get("cases"),
            "revision": run["observed_revision"],
            "generation": run["goal_generation"],
            "oracleSemantics": plan.get("oracle_semantics") or "half_open",
        })
        existing = (state.get("continuation") or {}).get("operation_id")
        operation_id = existing or ("op-" + request_hash[:16])
        operation, created = runtime.store.admit_operation(
            run_id, operation_id=operation_id, kind="differential_search",
            request_hash=request_hash, input_revision=run["observed_revision"],
            goal_generation=int(run["goal_generation"]),
            steering_epoch=int(run["steering_epoch"]),
            controller_epoch=int(run["controller_epoch"]),
            reservation_id=reservation_id,
        )
        _continuation_update(runtime, run_id, phase="dispatch", operation_id=operation_id,
                             request_hash=request_hash, args={**plan, "candidate_label": plan.get("candidate_label")})
        if created:
            runtime.store.add_case_usage(run_id, len(instances))
            runtime.store.append_event(run_id, "operation_dispatched", role="host", payload={
                "operationId": operation_id, "cases": len(instances), "kind": "differential_search",
            })
        raw = operation.get("raw_receipt")
        if raw is None:
            job = {
                "job_id": "job:" + operation_id,
                "kind": "differential_search",
                "candidate": {"source": source, "language": "cpp"},
                "cases": [{"case_id": f"case-{i:05d}", "input": render_instance(instance)}
                          for i, instance in enumerate(instances)],
                "budget": plan.get("budget") or {"cases": len(instances)},
            }
            try:
                raw = runtime.worker.submit(job)
            except WorkerUnavailable as exc:
                runtime.store.mark_operation_status(operation_id, "failed",
                                                    classification="infrastructure_error")
                runtime.store.commit_operation_result(operation_id, OperationResultV1(
                    operation_id=operation_id, request_hash=request_hash,
                    input_revision=run["observed_revision"], status="failed",
                    classification="infrastructure_error", error_code=str(exc)[:1000],
                    retryability="resumable",
                ))
                return {"result": {"status": "failed", "kind": "worker_unavailable",
                                   "error": str(exc)[:1000]}}
            except Exception as exc:  # noqa: BLE001
                runtime.store.mark_operation_status(operation_id, "failed",
                                                    classification="infrastructure_error")
                runtime.store.commit_operation_result(operation_id, OperationResultV1(
                    operation_id=operation_id, request_hash=request_hash,
                    input_revision=run["observed_revision"], status="failed",
                    classification="infrastructure_error", error_code=str(exc)[:1000],
                    retryability="unknown",
                ))
                return {"result": {"status": "failed", "kind": "worker_error",
                                   "error": str(exc)[:1000]}}
            if raw.get("status") == "pending":
                runtime.store.stage_worker_receipt(operation_id, raw=raw,
                                                   job_id=str(raw.get("job_id") or job["job_id"]),
                                                   status="pending")
                runtime.store.append_event(run_id, "worker_pending", role="worker", payload={
                    "operationId": operation_id, "jobId": raw.get("job_id"),
                })
                return {"result": {"status": "pending", "kind": "worker_pending",
                                   "pending_operation": True,
                                   "operation_id": operation_id}}
            runtime.store.stage_worker_receipt(operation_id, raw=raw, job_id=job["job_id"],
                                               status="admitted")
            runtime.failpoints.hit("after_receipt_commit")
        published = _publish_diagnostic(runtime, operation, raw, plan, instances,
                                        int(run["controller_epoch"]))
        runtime.failpoints.hit("after_publication_before_checkpoint")
        if published.get("status") == "conflict":
            _continuation_update(runtime, run_id, phase="interpret", operation_id=operation_id)
            return {"result": published}
        _continuation_update(runtime, run_id, phase="interpret", operation_id=operation_id)
        return {"plan": plan, "operation_id": operation_id, "next_phase": "interpret",
                "result": None}

    def interpret(state: InvestigationInput) -> dict:
        run_id = state["run_id"]
        operation_id = (state.get("operation_id")
                        or (state.get("continuation") or {}).get("operation_id"))
        if not operation_id:
            return _done_interpret(runtime, run_id, {"status": "failed", "kind": "missing_operation"})
        operation = runtime.store.get_operation(operation_id)
        if operation["status"] not in TERMINAL_OPERATION:
            if operation.get("raw_receipt"):
                raw = operation["raw_receipt"]
                plan = dict((json.loads(runtime.store.get_run(run_id)["continuation_json"] or "{}")
                             .get("args") or {}))
                instances = [parse_instance(text) for text in plan.get("cases") or []]
                published = _publish_diagnostic(runtime, operation, raw, plan, instances,
                                                int(runtime.store.get_run(run_id)["controller_epoch"]))
                if published.get("status") == "conflict":
                    return {"result": published}
                operation = runtime.store.get_operation(operation_id)
            else:
                return _done_interpret(runtime, run_id, {"status": "pending", "kind": "worker_pending",
                                   "pending_operation": True})
        result = operation.get("result") or {}
        classification = str(result.get("classification") or operation["classification"])
        evidence_ids = list(result.get("evidence_ids") or [])
        if result.get("status") in ("failed", "incomplete", "outcome_unknown") and \
                classification in ("infrastructure_error", "stale"):
            return _done_interpret(runtime, run_id, {"status": "conflict" if classification == "stale" else "failed",
                               "kind": classification,
                               "operation_id": operation_id,
                               "evidence_id": (evidence_ids or [None])[0]})
        plan = dict((json.loads(runtime.store.get_run(run_id)["continuation_json"] or "{}")
                     .get("args") or {}))
        evidence = runtime.store.get_evidence(evidence_ids[0]) if evidence_ids else None
        if evidence is None:
            return _done_interpret(runtime, run_id, {"status": "failed", "kind": "no_evidence",
                               "operation_id": operation_id})
        artifact = {}
        if evidence.get("artifact_refs"):
            try:
                artifact = json.loads(runtime.store.get_blob(evidence["artifact_refs"][0]).decode("utf-8"))
            except (LedgerError, json.JSONDecodeError):
                artifact = {}
        claim_id = plan.get("claim_id") or artifact.get("claimId") or "H1"
        classification = evidence["classification"]
        model_outcome = _gateway(
            runtime, (state.get("admission") or {}).get("reservation_id"),
            run_id=run_id, node="investigation.interpret",
            prompt_name="investigation.interpret",
            context={"classification": classification,
                     "witness": {k: v for k, v in artifact.items() if k != "code_spans"},
                     "claim": claim_id, "budget": runtime.store.budget_view(run_id)},
            schema=InterpretDraftV1,
        )
        draft = (model_outcome.data.model_dump()
                 if model_outcome is not None and model_outcome.ok else {})
        if classification == "shared_semantics_defect":
            finding = FindingV1(
                id="finding-" + sha256_text({"run": run_id, "op": operation_id, "oracle": True})[:14],
                claim_id="oracle-" + str(plan.get("candidate_ref") or "independent"),
                revision=operation["input_revision"], origin_role="host",
                origin_model=runtime.model_name, severity="high",
                allegation=("The supplied oracle and the candidate agree because they share an endpoint "
                            f"assumption ({artifact.get('oracleSemantics')}); the product half-open reading "
                            f"is {artifact.get('productExpected')} versus their {artifact.get('expected')}."),
                evidence_refs=[evidence["id"]],
                status="investigating", resolver_kind="deterministic",
            )
            runtime.store.upsert_finding(run_id, finding)
            explanation = ExplanationV1(
                id="expl-" + sha256_text({"run": run_id, "shared": operation_id})[:12],
                revision=operation["input_revision"], claim_refs=[finding.claim_id],
                audience_depth=runtime.inputs.collaboration(run_id).get("explanation_depth", "standard"),
                question="Is the candidate wrong, or do the references share a semantic error?",
                short_answer=(
                    f"Agreement is not independent here. Both the supplied oracle and the candidate "
                    f"return {artifact.get('expected')} under the {artifact.get('oracleSemantics')} convention; "
                    f"the product's half-open oracle gives {artifact.get('productExpected')} on the same legal "
                    "touching input. Audit the oracle before patching the candidate."
                ),
                worked_example_ref=artifact.get("input"),
                evidence_refs=[evidence["id"]],
                uncertainty=["the oracle provenance must be re-derived independently"],
                next_author_actions=["re-derive the oracle from the endpoint decision",
                                     "do not patch the candidate until the shared assumption is resolved"],
            )
            runtime.store.add_explanation(run_id, explanation)
            return _done_interpret(runtime, run_id, {
                "status": "complete", "kind": "claim_challenge",
                "classification": classification, "evidence_id": evidence["id"],
                "artifact": artifact, "finding_id": finding.id,
                "explanation_id": explanation.id, "sharedOracle": True,
            })
        if classification == "counterexample":
            finding = FindingV1(
                id="finding-" + sha256_text({"run": run_id, "op": operation_id})[:14],
                claim_id=claim_id, revision=operation["input_revision"], origin_role="model",
                origin_model=runtime.model_name, severity="high",
                allegation=(f"Claim {claim_id} refuted on a legal input: "
                            f"expected {artifact.get('expected')}, candidate returned {artifact.get('actual')}."),
                evidence_refs=[evidence["id"]],
                suggested_discriminator=plan.get("failure_diagnostic") or "inspect the endpoint comparison",
                status="open", resolver_kind="deterministic",
            )
            runtime.store.upsert_finding(run_id, finding)
            return _done_interpret(runtime, run_id, {"status": "complete", "kind": "diagnostic",
                               "classification": classification, "claim_id": claim_id,
                               "evidence_id": evidence["id"], "artifact": artifact,
                               "finding_id": finding.id,
                               "summary": draft.get("summary") or artifact.get("comparison"),
                               "cause": draft.get("cause") or "",
                               "uncertainty": draft.get("uncertainty") or [
                                   "the full optimality argument remains a proof obligation"],
                               "next_author_actions": draft.get("next_author_actions") or []})
        if classification == "agreement":
            if artifact.get("complete"):
                collab = runtime.inputs.collaboration(run_id)
                collab.setdefault("approach_records", []).append({
                    "candidateRef": plan.get("candidate_ref"),
                    "classification": "agreement",
                    "declared": artifact.get("declared"),
                    "completed": artifact.get("completed"),
                    "complete": True,
                })
                runtime.store.update_run(run_id, collaboration_json=canonical_json(collab))
                ref = str(plan.get("candidate_ref") or "")
                if ref.startswith("contribution:"):
                    runtime.store.set_contribution_validation(ref.split(":", 1)[1], "tested")
            return _done_interpret(runtime, run_id, {"status": "complete", "kind": "diagnostic",
                               "classification": classification, "claim_id": claim_id,
                               "evidence_id": evidence["id"], "artifact": artifact,
                               "summary": draft.get("summary") or
                               f"candidate agreed on {artifact.get('completed')} of "
                               f"{artifact.get('declared')} declared cases",
                               "complete": bool(artifact.get("complete"))})
        if classification in ("compile_error", "candidate_runtime_error", "invalid_output", "invalid_input",
                               "time_limit", "memory_limit", "output_limit", "infrastructure_error",
                               "worker_protocol_error"):
            return _done_interpret(runtime, run_id, {"status": "failed", "kind": classification,
                               "evidence_id": evidence["id"], "operation_id": operation_id})
        return _done_interpret(runtime, run_id, {"status": "failed", "kind": classification,
                           "evidence_id": evidence["id"]})

    builder = StateGraph(InvestigationInput)
    builder.add_node("route_phase", route_phase)
    builder.add_node("design", design)
    builder.add_node("qualify", qualify)
    builder.add_node("dispatch", dispatch)
    builder.add_node("interpret", interpret)
    builder.add_edge(START, "route_phase")
    builder.add_conditional_edges("route_phase", _phase_router,
                                  {"design": "design", "qualify": "qualify",
                                   "dispatch": "dispatch", "interpret": "interpret"})
    builder.add_conditional_edges("design", _next_phase_router,
                                  {"qualify": "qualify", "interpret": "interpret", "__end__": END})
    builder.add_conditional_edges("qualify", _next_phase_router,
                                  {"dispatch": "dispatch", "__end__": END})
    builder.add_conditional_edges("dispatch", _result_router,
                                  {"interpret": "interpret", "__end__": END})
    builder.add_edge("interpret", END)
    return builder.compile()


def _done_interpret(runtime: Runtime, run_id: str, result: dict) -> dict:
    _clear_continuation(runtime, run_id)
    return {"result": result}


def _phase_router(state: dict) -> str:
    phase = str(state.get("next_phase") or "design")
    if phase not in ("design", "qualify", "dispatch", "interpret"):
        return "design"
    return phase


def _next_phase_router(state: dict) -> str:
    if state.get("result"):
        return "__end__"
    return str(state.get("next_phase") or "__end__")


def _result_router(state: dict) -> str:
    if state.get("result") and state["result"].get("status") in ("pending", "failed", "conflict"):
        return "__end__"
    if state.get("result") is not None:
        return "__end__"
    return str(state.get("next_phase") or "interpret")

def build_editing(runtime: Runtime):
    def draft(state: EditingInput) -> dict:
        run_id = state["run_id"]
        ctx = state["ctx"]
        args = dict(state.get("args") or {})
        run = runtime.store.get_run(run_id)
        collab = runtime.inputs.collaboration(run_id)
        review = (collab.get("pending_patch_review") or {})
        patch = None
        if args.get("patch") and isinstance(args["patch"], dict):
            patch = dict(args["patch"])
        if review:
            for _iid, entry in review.items():
                blob = entry.get("replacementBlobRef")
                if blob:
                    patch = {
                        "path": args.get("path") or entry.get("path") or "solution.cpp",
                        "after": runtime.store.get_blob(blob).decode("utf-8"),
                        "rationale": "author-edited proposal from the repair card",
                        "source": "author-edit",
                        "reviewedFrom": entry.get("baseProposalHash"),
                    }
                    break
        if patch is None and args.get("path") and args.get("after") is not None:
            patch = {"path": args["path"], "after": args["after"],
                     "rationale": args.get("rationale") or "",
                     "source": "author-or-test-supplied"}
        if patch is None:
            outcome = _gateway(
                runtime, (state.get("admission") or {}).get("reservation_id"),
                run_id=run_id, node="editing.draft", prompt_name="editing.draft",
                context={"changeBrief": args.get("changeBrief") or args.get("intent") or "",
                         "witness": args.get("witness"),
                         "revision": run["observed_revision"],
                         "files": runtime.store.get_revision(run["observed_revision"])["files"],
                         "authorContext": contribution_context(runtime, run_id),
                         "authorArtifacts": artifact_context(runtime, run_id),
                         "conversation": conversation_context(runtime, run_id),
                         "engagement": ctx.get("engagement")},
                schema=PatchDraftV1,
            )
            if outcome is None or not outcome.ok:
                return {"result": {"status": "failed", "kind": "model_contract",
                                   "error": "patch draft unavailable"}}
            patch = outcome.data.model_dump()
            patch["source"] = "model"
        patch["baseRevision"] = run["observed_revision"]
        return {"patch": patch}

    def validate_patch(state: EditingInput) -> dict:
        run_id = state["run_id"]
        patch = dict(state.get("patch") or {})
        ctx = state["ctx"]
        run = runtime.store.get_run(run_id)
        try:
            from .policy import canonical_workspace_path
            path = str(patch.get("path") or "")
            canonical_workspace_path(runtime.store.root / "checkout", path)
        except PolicyDenied as exc:
            return {"result": {"status": "failed", "kind": "unsafe_path", "error": str(exc)}}
        after = str(patch.get("after") or "")
        if len(after.encode("utf-8")) > 1 * 1024 * 1024:
            return {"result": {"status": "failed", "kind": "oversized_patch"}}
        revision = runtime.store.get_revision(run["observed_revision"])
        existing = next((f for f in revision["files"] if f.get("canonical_path") == path), None)
        before_hash = existing.get("hash") if existing else None
        before = ""
        if existing:
            try:
                before = runtime.store.get_blob(existing["hash"]).decode("utf-8")
            except LedgerError:
                before = ""
        after_blob = runtime.store.put_blob(after.encode("utf-8"), kind="patch-content")
        import difflib

        diff_text = "".join(difflib.unified_diff(
            before.splitlines(True), after.splitlines(True),
            fromfile=path + " (base " + str(run["observed_revision"]) + ")",
            tofile=path + " (proposed)",
        )) or f"--- {path}\n+++ {path}\n(no textual change)\n"
        diff_blob = runtime.store.put_blob(diff_text.encode("utf-8"), kind="diff")
        proposal_hash = sha256_text({"path": path, "beforeHash": before_hash,
                                     "afterHash": after_blob,
                                     "baseRevision": run["observed_revision"],
                                     "generation": run["goal_generation"]})
        patch.update({"proposalHash": proposal_hash, "beforeHash": before_hash,
                      "afterHash": after_blob, "before": before, "canonicalPath": path,
                      "diffBlob": diff_blob})
        _continuation_update(runtime, run_id, phase="validate_patch",
                             args={"patch": patch, "path": path})
        effective = dict(patch)
        collab = runtime.inputs.collaboration(run_id)
        author_edit = bool(collab.get("patch_edits"))
        if ctx.get("editDenied"):
            return {"result": {"status": "failed", "kind": "authorization_denied",
                               "reason": (collab.get("edit_denied") or {}).get("reason", "")}}
        if not ctx.get("editGranted") and ctx.get("editIntent") == "information" and not author_edit:
            return {"result": {"status": "failed", "kind": "information_only",
                               "reason": "the current author request is explanation/review, not an effect"}}
        if ctx.get("editGranted") and not _path_in_scope(path, ctx.get("editScope") or []):
            return {"result": {"status": "failed", "kind": "out_of_scope",
                               "scope": ctx.get("editScope") or []}}
        force_review = (ctx.get("delegation") or {}).get("return_kind") == "patch_reviewed"
        if (not ctx.get("editGranted") or force_review) and not author_edit:
            interaction = _get_or_create_interaction(
                runtime, run_id, kind="repair_review",
                prompt_text=("Apply this concrete " + path + " change? It replaces the current file "
                             "at the observed revision."),
                why="A file change is an effect. The author must authorize this exact diff.",
                options=[
                    {"id": "approve", "label": "Apply this exact diff",
                     "consequence": "creates one immutable revision and invalidates dependent evidence"},
                    {"id": "reject", "label": "Keep the source unchanged",
                     "consequence": "returns a diagnostic-only stage"},
                ],
                recommendation=None,
                affected=list(patch.get("affected_claim_ids") or []),
                evidence_refs=[patch["diffBlob"]],
            )
            runtime.store.update_run(run_id, status="waiting_human",
                                     pending_interaction_id=interaction["id"])
            _continuation_update(runtime, run_id, phase="validate_patch",
                                 interaction_id=interaction["id"], args={"patch": patch, "path": path})
            return {"result": {"status": "needs_human", "kind": "repair_authorization",
                               "interaction_id": interaction["id"], "patch": patch}}
        return {"patch": patch, "next_phase": "publish"}

    def publish(state: EditingInput) -> dict:
        run_id = state["run_id"]
        patch = dict(state.get("patch") or {})
        ctx = state["ctx"]
        run = runtime.store.get_run(run_id)
        # Publication is idempotent for the same proposal hash; a crash after
        # commit but before the graph checkpoint must not create a second revision.
        publication = runtime.store.get_publication(run_id, patch.get("proposalHash") or "")
        if publication is not None:
            existing = next((e for e in runtime.store.list_evidence(run_id)
                             if (e.get("dependency_hashes") or {}).get("proposalHash")
                             == patch.get("proposalHash")), None)
            return {"result": {"status": "complete", "kind": "patch",
                               "revision": publication["revision"],
                               "evidence_id": existing["id"] if existing else None,
                               "patch": {"proposalHash": patch.get("proposalHash")},
                               "replayed": True, "invalidated": []}}
        for existing in runtime.store.list_evidence(run_id):
            if existing.get("outcome") != "patch":
                continue
            if (existing.get("dependency_hashes") or {}).get("proposalHash") == patch.get("proposalHash"):
                return {"result": {"status": "complete", "kind": "patch",
                                   "revision": (existing.get("dependency_hashes") or {}).get("newRevision"),
                                   "evidence_id": existing["id"],
                                   "patch": {"proposalHash": patch.get("proposalHash")},
                                   "replayed": True, "invalidated": []}}
        if str(patch.get("baseRevision")) != str(run["observed_revision"]):
            return {"result": {"status": "conflict", "kind": "stale_patch",
                               "expectedRevision": patch.get("baseRevision"),
                               "currentRevision": run["observed_revision"]}}
        pending_barrier = [item for item in runtime.store.list_inputs(run_id)
                           if item["status"] in ("received", "interpreting") and item["barrier"]]
        if pending_barrier:
            # An uninterpreted author input fences the effect.  Return to
            # assess/reconcile before any file revision is created.
            return {"result": {"status": "conflict", "kind": "input_barrier",
                               "inputIds": [item["id"] for item in pending_barrier]}}
        collab = runtime.inputs.collaboration(run_id)
        allowed, auth_reason = _edit_authorization(
            runtime, run_id, patch.get("canonicalPath") or "", collab
        )
        if not allowed:
            return {"result": {"status": "failed", "kind": auth_reason,
                               "path": patch.get("canonicalPath")}}
        runtime.failpoints.hit("editing.before_publish")
        # Recheck the receipt barrier, canonical revision and live authority at
        # the commit point: a refusal may have arrived while this operation was
        # paused between the first check and the commit.
        run = runtime.store.get_run(run_id)
        if str(patch.get("baseRevision")) != str(run["observed_revision"]):
            return {"result": {"status": "conflict", "kind": "stale_patch",
                               "expectedRevision": patch.get("baseRevision"),
                               "currentRevision": run["observed_revision"]}}
        pending_barrier = [item for item in runtime.store.list_inputs(run_id)
                           if item["status"] in ("received", "interpreting")
                           and item["barrier"]]
        if pending_barrier:
            return {"result": {"status": "conflict", "kind": "input_barrier",
                               "inputIds": [item["id"] for item in pending_barrier]}}
        collab = runtime.inputs.collaboration(run_id)
        allowed, auth_reason = _edit_authorization(
            runtime, run_id, patch.get("canonicalPath") or "", collab
        )
        if not allowed:
            return {"result": {"status": "failed", "kind": auth_reason,
                               "path": patch.get("canonicalPath")}}
        revision = runtime.store.get_revision(run["observed_revision"])
        files = [f for f in revision["files"]
                 if f.get("canonical_path") != patch.get("canonicalPath")]
        body = runtime.store.get_blob(patch["afterHash"])
        files.append({
            "canonical_path": patch["canonicalPath"],
            "hash": patch["afterHash"],
            "size": len(body),
            "kind": "source",
            "visibility": "author",
        })
        try:
            published = runtime.store.publish_revision(
                run_id, revision["id"], files,
                expected_revision=patch.get("baseRevision") or "",
                expected_generation=ctx["goal_generation"],
                required_edit_path=patch.get("canonicalPath") or "",
                proposal_hash=patch.get("proposalHash") or "",
                created_by="author-authorized-patch",
            )
        except PublicationBlocked as exc:
            return {"result": {"status": "conflict", "kind": exc.kind,
                               "reason": str(exc),
                               "path": patch.get("canonicalPath")}}
        new_revision = published["revision"]
        patch_artifact = {
            "kind": "patch",
            "path": patch["canonicalPath"],
            "baseRevision": patch.get("baseRevision"),
            "newRevision": new_revision["id"],
            "beforeHash": patch.get("beforeHash"),
            "afterHash": patch.get("afterHash"),
            "proposalHash": patch.get("proposalHash"),
            "rationale": patch.get("rationale"),
            "source": patch.get("source"),
            "attribution": "author-or-model-proposed",
        }
        blob = runtime.store.put_blob(canonical_json(patch_artifact).encode("utf-8"),
                                      kind="patch")
        invalidated = runtime.store.invalidate_current_results(run_id, reason="authorized patch")
        evidence = EvidenceV1(
            id="ev-" + sha256_text({"run": run_id, "patch": patch.get("proposalHash")})[:14],
            producer_kind="deterministic", producer_version="managed-patch-v1",
            operation_id="patch-" + str(patch.get("proposalHash"))[:12],
            input_refs=[patch["afterHash"], patch.get("beforeHash") or ""],
            dependency_hashes={"baseRevision": patch.get("baseRevision") or "",
                               "newRevision": new_revision["id"],
                               "proposalHash": patch.get("proposalHash") or ""},
            domain="editing", outcome="patch", artifact_refs=[blob],
            environment_ref="immutable-revision-store", freshness="current",
            classification="patch",
        )
        runtime.store.add_evidence(run_id, evidence)
        collab = runtime.inputs.collaboration(run_id)
        if collab.get("pending_patch_review"):
            collab.pop("pending_patch_review", None)
            runtime.store.update_run(run_id, collaboration_json=canonical_json(collab))
        projection = None
        if runtime.projection is not None:
            base = {patch["canonicalPath"]: patch.get("beforeHash")}
            projection = runtime.projection.apply(run_id, new_revision["id"], files, base)
        runtime.failpoints.hit("editing.after_publish_before_checkpoint")
        runtime.store.append_event(run_id, "patch_published", role="host", payload={
            "path": patch["canonicalPath"], "revision": new_revision["id"],
            "proposalHash": patch.get("proposalHash"), "invalidated": invalidated,
            "projection": (projection or {}).get("state"),
        })
        return {"result": {"status": "complete", "kind": "patch",
                           "revision": new_revision["id"], "evidence_id": evidence.id,
                           "patch": patch_artifact, "projection": projection,
                           "invalidated": invalidated}}

    builder = StateGraph(EditingInput)
    builder.add_node("draft", draft)
    builder.add_node("validate_patch", validate_patch)
    builder.add_node("publish", publish)
    builder.add_edge(START, "draft")
    builder.add_conditional_edges("draft", _edit_router,
                                  {"validate_patch": "validate_patch", "__end__": END})
    builder.add_conditional_edges("validate_patch", _edit_router,
                                  {"publish": "publish", "__end__": END})
    builder.add_edge("publish", END)
    return builder.compile()


def _edit_router(state: dict) -> str:
    if state.get("result"):
        return "__end__"
    return str(state.get("next_phase") or "validate_patch")


def build_review(runtime: Runtime):
    def brief(state: ReviewInput) -> dict:
        ctx = state["ctx"]
        args = dict(state.get("args") or {})
        run_id = state["run_id"]
        refs = list(args.get("artifact_refs") or ctx.get("evidence_ids") or [])
        allowed: list[str] = []
        for ref in refs:
            try:
                runtime.store.get_evidence(ref)
                allowed.append(ref)
            except LedgerError:
                continue
        brief = {
            "question": args.get("question") or "Does the argument justify the implemented comparison?",
            "revision": ctx["revision"],
            "obligation_ids": args.get("obligation_ids") or [],
            "artifact_refs": allowed,
            "excluded": ["private_tests", "author_conversation", "credentials"],
            "budget": {"model_attempts_total": 3, "wall_seconds": 120},
            "result_schema": "ReviewFindingsV1",
        }
        return {"brief": brief, "admitted_artifacts": allowed}

    def challenge(state: ReviewInput) -> dict:
        brief = dict(state.get("brief") or {})
        outcome = _gateway(
            runtime, (state.get("admission") or {}).get("reservation_id"),
            run_id=state["run_id"], node="review.challenge", prompt_name="review.challenge",
            context=brief, schema=ReviewFindingsV1,
        )
        if outcome is None or not outcome.ok:
            return {"result": {"status": "incomplete", "kind": "review_failed",
                               "error": "review attempt ceiling exhausted"}}
        return {"findings": outcome.data.model_dump()}

    def validate_findings(state: ReviewInput) -> dict:
        run_id = state["run_id"]
        brief = dict(state.get("brief") or {})
        findings = dict(state.get("findings") or {})
        admitted = set(state.get("admitted_artifacts") or [])
        persisted = []
        for index, item in enumerate(findings.get("findings") or []):
            cited = str(item.get("cited_artifact") or "")
            if cited not in admitted:
                return {"result": {"status": "incomplete", "kind": "fabricated_citation",
                                   "citation": cited}}
            finding = FindingV1(
                id="finding-" + sha256_text({"run": run_id, "review": brief, "i": index})[:14],
                revision=brief.get("revision"), origin_role="review",
                origin_model=runtime.model_name,
                severity=item.get("severity") or "medium",
                allegation=str(item.get("allegation") or ""),
                evidence_refs=[cited],
                suggested_discriminator=item.get("proposed_discriminator"),
                status="open", resolver_kind="review",
            )
            runtime.store.upsert_finding(run_id, finding)
            persisted.append(finding.id)
        return {"result": {"status": "complete", "kind": "review",
                           "coverage": findings.get("coverage") or [],
                           "findings": persisted,
                           "noFindings": findings.get("no_findings", True)}}

    builder = StateGraph(ReviewInput)
    builder.add_node("brief", brief)
    builder.add_node("challenge", challenge)
    builder.add_node("validate_findings", validate_findings)
    builder.add_edge(START, "brief")
    builder.add_edge("brief", "challenge")
    builder.add_conditional_edges("challenge", _review_router,
                                  {"validate_findings": "validate_findings", "__end__": END})
    builder.add_edge("validate_findings", END)
    return builder.compile()


def _review_router(state: dict) -> str:
    return "__end__" if state.get("result") else "validate_findings"
