"""Runtime-validated durable records for the C2 engine.

TypedDict annotations alone do not validate durable records (03 Â§2), so all
records that cross an API, persistence or effect boundary are Pydantic models
with ``extra="forbid"``.  Payloads that could smuggle authority are tagged and
validated explicitly; the host owns IDs, actor, sequence and epochs.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = 1

RunStatus = Literal[
    "idle",
    "running",
    "waiting_human",
    "waiting_worker",
    "stage_returned",
    "awaiting_author",
    "incomplete",
    "blocked",
    "cancelled",
]

StageOutcome = Literal[
    "stage_returned",
    "awaiting_author",
    "incomplete",
    "blocked",
    "cancelled",
    "delivery_complete",
]

ChildStatus = Literal["complete", "needs_human", "pending", "conflict", "incomplete", "failed"]

ReturnKind = Literal[
    "first_valid_witness", "campaign_complete", "explanation_delivered", "patch_reviewed"
]

InteractionKind = Literal[
    "semantics",
    "approach_choice",
    "proof_challenge",
    "explanation",
    "test_contribution",
    "repair_review",
    "delegation",
    "export_approval",
]

InputKind = Literal["new_goal", "steer", "contribute", "respond", "set_engagement", "cancel", "chat_turn"]

ResponseKind = Literal[
    "semantic_choice",
    "approach_preference",
    "claim",
    "contribution",
    "request_explanation",
    "edit_proposal",
    "authorize_effect",
    "reject",
    "defer",
]

OperationStatus = Literal[
    "admitted", "pending", "completed", "cancelled", "incomplete", "failed", "outcome_unknown"
]

ProducerKind = Literal["deterministic", "model", "human", "formal_checker"]

Freshness = Literal["current", "stale"]

Hex64 = str
_PROPOSAL_HASH = re.compile(r"^[0-9a-f]{64}$")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RevisionV1(Model):
    id: str
    parent_id: str | None = None
    files: list[dict] = Field(default_factory=list)
    spec_hash: str = ""
    profile_hash: str = ""
    prompt_bundle_hash: str = ""
    skill_manifest_hash: str = ""
    compiler_identity: str | None = None
    worker_image_identity: str | None = None
    created_by: str = "engine"
    created_at: str = ""


class AuthorInputV1(Model):
    """A stored author input.  IDs/seq/actor are server-owned."""

    id: str
    run_id: str
    kind: InputKind
    text: str = ""
    payload: dict | None = None
    expected_generation: int | None = None
    referenced_artifacts: list[str] = Field(default_factory=list)
    seq: int
    application_status: Literal[
        "received", "applied", "needs_disambiguation", "conflict", "superseded", "cancelled"
    ] = "received"
    client_request_id: str
    original_hash: str
    resolves_input_id: str | None = None
    supersedes_input_id: str | None = None
    interpretation_ref: str | None = None
    received_at: str = ""
    applied_at: str | None = None


class SemanticChoice(Model):
    requirement_id: str
    option_id: str | None = None
    definition_text: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self):
        if (self.option_id is None) == (self.definition_text is None):
            raise ValueError("semantic_choice requires exactly one of option_id or definition_text")
        return self


class ApproachPreference(Model):
    approach_id: str
    rationale: str | None = None


class ClaimPayload(Model):
    text: str
    assumption_ids: list[str] = Field(default_factory=list)
    supporting_refs: list[str] = Field(default_factory=list)


class ContributionPayload(Model):
    kind: Literal["code", "lemma", "test", "idea"]
    original_blob_ref: str
    target_claim_ids: list[str] = Field(default_factory=list)
    attribution: str | None = None


class RequestExplanation(Model):
    target_ref: str
    question: str
    depth: Literal["brief", "standard", "detailed"] | None = None


class EditProposal(Model):
    base_proposal_hash: str
    replacement_blob_ref: str
    rationale: str | None = None


class AuthorizeEffect(Model):
    effect_manifest_hash: str
    grant_scope_ref: str
    decision: Literal["approve"] = "approve"


class RejectPayload(Model):
    target_ref: str
    reason: str | None = None


class DeferPayload(Model):
    target_ref: str
    requested_next_step: str | None = None


_PAYLOAD_TYPES: dict[str, type[Model]] = {
    "semantic_choice": SemanticChoice,
    "approach_preference": ApproachPreference,
    "claim": ClaimPayload,
    "contribution": ContributionPayload,
    "request_explanation": RequestExplanation,
    "edit_proposal": EditProposal,
    "authorize_effect": AuthorizeEffect,
    "reject": RejectPayload,
    "defer": DeferPayload,
}


def validate_response_payload(kind: str, payload: dict) -> Model:
    """Validate a tagged response payload and reject extra authority fields."""
    if kind not in _PAYLOAD_TYPES:
        raise ValueError(f"Unsupported response kind: {kind}")
    for forbidden in ("actor_id", "run_id", "seq", "received_seq", "controller_epoch", "grant"):
        if forbidden in payload:
            raise ValueError(f"{forbidden} is server-owned and may not be supplied")
    return _PAYLOAD_TYPES[kind].model_validate(payload)


class HumanResponseV1(Model):
    id: str
    interaction_id: str
    run_id: str
    actor_id: str
    client_request_id: str
    expected_revision: str | None = None
    expected_goal_generation: int | None = None
    expected_proposal_hash: str | None = None
    kind: ResponseKind
    payload: dict
    received_seq: int
    received_at: str = ""
    status: Literal["receipt", "conflict"] = "receipt"


class HumanInteractionV1(Model):
    id: str
    run_id: str
    kind: InteractionKind
    revision: str
    goal_generation: int
    proposal_hash: str
    affected_claim_ids: list[str] = Field(default_factory=list)
    prompt_ref: str = ""
    why: str = ""
    option_ids: list[str] = Field(default_factory=list)
    options: list[dict] = Field(default_factory=list)
    recommendation: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    expected_response_schema: str = "TaggedHumanResponseV1"
    dependent_operations: list[str] = Field(default_factory=list)
    blocking: bool = True
    status: Literal["proposed", "pending", "answered", "superseded", "withdrawn"] = "pending"
    response_ids: list[str] = Field(default_factory=list)
    resolution_response_id: str | None = None
    created_at: str = ""


class ContributionV1(Model):
    id: str
    actor_kind: Literal["human", "agent", "imported"]
    actor_id: str
    source_input_id: str | None
    kind: Literal["code", "lemma", "test", "idea"]
    original_blob_hash: str
    derived_artifact_refs: list[str] = Field(default_factory=list)
    revision: str
    claim_ids: list[str] = Field(default_factory=list)
    validation_status: Literal["unvalidated", "valid", "invalid", "tested"] = "unvalidated"
    attribution: str = ""
    supersedes: str | None = None
    created_at: str = ""


class DelegationV1(Model):
    id: str
    goal_generation: int
    objective: str
    permitted_operations: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    claim_scope: list[str] = Field(default_factory=list)
    budget_ceiling: dict = Field(default_factory=dict)
    deadline: str | None = None
    return_predicate: dict
    grant_ref: str
    status: Literal["active", "returned", "revoked", "exhausted"] = "active"
    return_kind: ReturnKind = "campaign_complete"
    return_target_refs: list[str] = Field(default_factory=list)
    required_evidence_kinds: list[str] = Field(default_factory=list)
    created_at: str = ""


class GrantV1(Model):
    id: str
    actor_id: str
    source_input_id: str
    run_id: str
    goal_generation: int
    operation_kinds: list[str] = Field(default_factory=list)
    artifact_or_claim_scope: list[str] = Field(default_factory=list)
    budget_id: str = ""
    expires_at: str | None = None
    revoked_at: str | None = None
    created_at: str = ""


class OperationResultV1(Model):
    operation_id: str
    request_hash: str
    input_revision: str
    status: OperationStatus
    classification: str = "pending"
    actual_limits: dict = Field(default_factory=dict)
    usage: dict = Field(default_factory=dict)
    artifacts: dict = Field(default_factory=dict)
    truncation: dict = Field(default_factory=dict)
    error_code: str | None = None
    retryability: str = "unknown"
    evidence_ids: list[str] = Field(default_factory=list)
    worker_identity: str | None = None
    created_at: str = ""


class EvidenceV1(Model):
    id: str
    producer_kind: ProducerKind
    producer_version: str
    operation_id: str
    input_refs: list[str] = Field(default_factory=list)
    dependency_hashes: dict = Field(default_factory=dict)
    domain: str | None = None
    seed: int | None = None
    enumeration_order: str | None = None
    budget_requested: dict = Field(default_factory=dict)
    usage_observed: dict = Field(default_factory=dict)
    outcome: str
    artifact_refs: list[str] = Field(default_factory=list)
    environment_ref: str | None = None
    visibility: Literal["author", "review", "private"] = "author"
    freshness: Freshness = "current"
    classification: str = ""
    created_at: str = ""


class FindingV1(Model):
    id: str
    claim_id: str | None = None
    revision: str
    origin_role: str
    origin_model: str | None = None
    severity: Literal["info", "low", "medium", "high", "blocking"] = "info"
    allegation: str
    evidence_refs: list[str] = Field(default_factory=list)
    suggested_discriminator: str | None = None
    status: Literal[
        "open", "investigating", "repair_proposed", "resolved", "disputed", "superseded"
    ] = "open"
    disposition_reason: str | None = None
    resolution_evidence_refs: list[str] = Field(default_factory=list)
    resolver_kind: Literal["model", "human", "deterministic", "review"] | None = None
    supersedes: str | None = None
    created_at: str = ""


class ExplanationV1(Model):
    id: str
    revision: str
    claim_refs: list[str] = Field(default_factory=list)
    audience_depth: Literal["brief", "standard", "detailed"] = "standard"
    question: str = ""
    short_answer: str = ""
    worked_example_ref: str | None = None
    assumption_to_code_links: list[dict] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    next_author_actions: list[str] = Field(default_factory=list)
    current: bool = True
    created_at: str = ""


class HandoffV1(Model):
    id: str
    goal_generation: int
    revision: str
    last_applied_author_seq: int
    outcome: StageOutcome
    decisions: list[dict] = Field(default_factory=list)
    contributions: list[dict] = Field(default_factory=list)
    completed_work: list[dict] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    current_evidence: list[str] = Field(default_factory=list)
    invalidations: list[dict] = Field(default_factory=list)
    remaining_budget: dict = Field(default_factory=dict)
    next_actions: list[str] = Field(default_factory=list)
    stage_return: dict | None = None
    created_at: str = ""


class StageReturnContract(Model):
    kind: ReturnKind
    target_refs: list[str] = Field(default_factory=list)
    required_evidence_kinds: list[str] = Field(default_factory=list)
    description: str = ""


class StageReturnV1(Model):
    contract: StageReturnContract
    satisfied: bool
    evidence_refs: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    reason: str = ""


class ApprovalV1(Model):
    id: str
    run_id: str = ""
    human_actor: str
    revision: str
    action_kind: str
    effect_manifest_hash: str
    evidence_root_hash: str = ""
    goal_generation: int
    steering_epoch: int
    profile_hash: str = ""
    decision: Literal["approve", "reject"] = "approve"
    created_at: str = ""
    invalidated_at: str | None = None


class WakeV1(Model):
    wake_id: str
    run_id: str
    wait_id: str
    reason: Literal["response", "steering", "cancel", "worker_receipt", "deadline"]
    durable_record_ref: str
    created_at: str = ""
    controller_epoch: int | None = None


class PlanV1(Model):
    """A model-proposed next action.  It carries no execution authority."""

    action: Literal["collaborate", "investigate", "edit", "review", "ask", "finish"]
    intent: str = ""
    target_claim_ids: list[str] = Field(default_factory=list)
    expected_observation: str = ""
    args: dict = Field(default_factory=dict)
    requested_budget: dict = Field(default_factory=dict)
    on_failure: str = "advisory"


class GoalProposalV1(Model):
    ready: bool
    objective: str = ""
    requirements: list[dict] = Field(default_factory=list)
    open_questions: list[dict] = Field(default_factory=list)
    spec_diff: list[dict] = Field(default_factory=list)


class ReviewFinding(Model):
    allegation: str
    cited_artifact: str
    span: str = ""
    severity: Literal["info", "low", "medium", "high", "blocking"] = "medium"
    uncertainty: str = ""
    proposed_discriminator: str | None = None


class ReviewFindingsV1(Model):
    coverage: list[str] = Field(default_factory=list)
    findings: list[ReviewFinding] = Field(default_factory=list)
    no_findings: bool = True


class CollaborationDraftV1(Model):
    short_answer: str = ""
    worked_example: str = ""
    alternatives: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    next_author_actions: list[str] = Field(default_factory=list)
    assumption_to_code_links: list[dict] = Field(default_factory=list)


class InterpretDraftV1(Model):
    summary: str = ""
    cause: str = ""
    first_violated_invariant: str = ""
    uncertainty: list[str] = Field(default_factory=list)
    next_author_actions: list[str] = Field(default_factory=list)
    proposed_next_action: str = "none"


class PatchDraftV1(Model):
    path: str
    before: str = ""
    after: str
    rationale: str = ""
    affected_claim_ids: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)


class InvestigationDesign(Model):
    candidate_ref: str
    hypothesis_claim: str = ""
    claim_text: str = ""
    domain: dict = Field(default_factory=lambda: {"kind": "witness", "name": "weighted_greedy"})
    expected_observation: str = ""
    failure_diagnostic: str = ""


class OperationEnvelopeV1(Model):
    schema_version: int = SCHEMA_VERSION
    operation_id: str
    run_id: str
    expected_revision: str
    goal_generation: int
    steering_epoch: int
    controller_epoch: int
    reservation_id: str
    kind: str
    inputs: dict
    budget: dict
    publish_kinds: list[str] = Field(default_factory=list)

    @field_validator("budget")
    @classmethod
    def _bounded_budget(cls, value: dict) -> dict:
        for key in ("cases", "wall_ms", "memory_mib", "output_bytes"):
            if key in value:
                number = value[key]
                if not isinstance(number, (int, float)) or isinstance(number, bool):
                    raise ValueError(f"budget.{key} must be numeric")
                if number <= 0:
                    raise ValueError(f"budget.{key} must be positive")
        return value


class CapabilityRecord(Model):
    id: str
    name: str
    operation_kinds: list[str]
    visibility: list[str]
    can_execute: bool
    can_approve: bool = False
    can_mutate: bool = False
    profile: str = "batch-exact-integer-v1"


class GateCheck(Model):
    gate: str
    status: Literal["implemented", "deterministic-tested", "browser-tested", "real-worker-tested", "real-model-qualified", "pending", "deferred", "unsupported"]
    evidence: list[str] = Field(default_factory=list)
