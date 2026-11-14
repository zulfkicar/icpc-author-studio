"""Typed StageReturn gate (V3).  DeliveryReady stays false/unsupported."""
from __future__ import annotations

import json

from .schemas import HandoffV1, StageReturnContract, StageReturnV1, canonical_json, sha256_text
from .store import ApplicationStore

RETURN_DESCRIPTIONS = {
    "first_valid_witness": "a qualified legal input and candidate/oracle receipt",
    "campaign_complete": "declared-domain completion counts",
    "explanation_delivered": "a current Explanation addressing the named question",
    "patch_reviewed": "a current diff and an explicit review disposition",
}


def contract_from_delegation(delegation: dict | None) -> StageReturnContract | None:
    if not delegation:
        return None
    predicate = delegation.get("return_predicate") or {}
    kind = delegation.get("return_kind") or predicate.get("kind") or "campaign_complete"
    if kind not in RETURN_DESCRIPTIONS:
        kind = "campaign_complete"
    return StageReturnContract(
        kind=kind,
        target_refs=list(delegation.get("return_target") or delegation.get("return_target_refs") or []),
        required_evidence_kinds=list(delegation.get("required_evidence") or
                                     delegation.get("required_evidence_kinds") or []),
        description=RETURN_DESCRIPTIONS[kind],
    )


def current_evidence(store: ApplicationStore, run_id: str) -> list[dict]:
    return [e for e in store.list_evidence(run_id) if e["freshness"] == "current"]


def review_dispositions(store: ApplicationStore, run_id: str) -> list[dict]:
    out = []
    for interaction in store.read_all(
        "SELECT * FROM interactions WHERE run_id=? AND status='answered' ORDER BY created_at", (run_id,)
    ):
        if interaction["kind"] != "repair_review":
            continue
        for response in store.responses_for(interaction["id"]):
            if response["applied"] and response["kind"] in ("edit_proposal", "authorize_effect",
                                                            "reject", "defer"):
                out.append({"interactionId": interaction["id"], "kind": response["kind"],
                            "responseId": response["id"]})
    return out


def evaluate_stage_return(store: ApplicationStore, run_id: str,
                          contract: StageReturnContract | None = None) -> StageReturnV1:
    run = store.get_run(run_id)
    if contract is None:
        stored = json.loads(run["stage_contract_json"] or "null")
        if stored:
            contract = StageReturnContract.model_validate(stored)
    if contract is None:
        return StageReturnV1(contract=StageReturnContract(
            kind="explanation_delivered", description=RETURN_DESCRIPTIONS["explanation_delivered"]),
            satisfied=False, reason="no typed stage contract is active")
    evidence = current_evidence(store, run_id)
    explanation = store.current_explanation(run_id)
    kind = contract.kind
    evidence_refs: list[str] = []
    unresolved: list[str] = []
    if kind == "first_valid_witness":
        witness = [
            e for e in evidence
            if e.get("classification") == "counterexample" and e.get("outcome") == "witness"
        ]
        evidence_refs = [e["id"] for e in witness]
        if not witness:
            unresolved.append("no qualified counterexample receipt is current")
            return StageReturnV1(contract=contract, satisfied=False, evidence_refs=evidence_refs,
                                 unresolved=unresolved, reason="witness not established")
        if contract.target_refs:
            linked = any(
                ref in contract.target_refs
                for e in witness
                for ref in (list(e.get("artifact_refs") or []) +
                            [str((e.get("usage_observed") or {}).get("claimId") or "")])
            )
            if not linked:
                unresolved.append("witness receipt is not linked to the delegated target")
                return StageReturnV1(contract=contract, satisfied=False, evidence_refs=evidence_refs,
                                     unresolved=unresolved, reason="witness not linked to target")
        return StageReturnV1(contract=contract, satisfied=True, evidence_refs=evidence_refs,
                             unresolved=[], reason="legal witness plus candidate/oracle receipt")
    if kind == "campaign_complete":
        campaigns = [
            e for e in evidence
            if e.get("outcome") == "campaign"
            and (e.get("domain") != "package_reference" or not contract.target_refs
                 or any((e.get("usage_observed") or {}).get(key) in contract.target_refs
                        for key in ("referenceId", "referencePath")))
        ]
        evidence_refs = [e["id"] for e in campaigns]
        if not campaigns:
            unresolved.append("no completed campaign receipt is current")
            return StageReturnV1(contract=contract, satisfied=False, evidence_refs=evidence_refs,
                                 unresolved=unresolved, reason="campaign not complete")
        complete = False
        for item in campaigns:
            usage = item.get("usage_observed") or {}
            complete = complete or bool(usage.get("complete"))
        if not complete:
            unresolved.append("campaign did not complete its declared domain")
            return StageReturnV1(contract=contract, satisfied=False, evidence_refs=evidence_refs,
                                 unresolved=unresolved, reason="campaign incomplete")
        return StageReturnV1(contract=contract, satisfied=True, evidence_refs=evidence_refs,
                             reason="declared finite domain completed")
    if kind == "explanation_delivered":
        if not explanation or not explanation.get("current"):
            unresolved.append("no current Explanation artifact")
            return StageReturnV1(contract=contract, satisfied=False, unresolved=unresolved,
                                 reason="explanation missing")
        if contract.target_refs:
            if not any(ref in contract.target_refs for ref in (explanation.get("claim_refs") or []) +
                       (explanation.get("evidence_refs") or [])):
                unresolved.append("current explanation does not address the delegated target")
                return StageReturnV1(contract=contract, satisfied=False,
                                     evidence_refs=list(explanation.get("evidence_refs") or []),
                                     unresolved=unresolved, reason="explanation addresses another target")
        if explanation.get("stale"):
            unresolved.append("explanation is stale")
            return StageReturnV1(contract=contract, satisfied=False, unresolved=unresolved,
                                 reason="explanation stale")
        return StageReturnV1(contract=contract, satisfied=True,
                             evidence_refs=list(explanation.get("evidence_refs") or []),
                             reason="current explanation addresses the named question")
    if kind == "patch_reviewed":
        patches = [e for e in evidence if e.get("outcome") == "patch"]
        dispositions = review_dispositions(store, run_id)
        evidence_refs = [e["id"] for e in patches]
        if not patches:
            unresolved.append("no current diff artifact")
            return StageReturnV1(contract=contract, satisfied=False, evidence_refs=evidence_refs,
                                 unresolved=unresolved, reason="diff missing")
        if not dispositions:
            unresolved.append("no explicit review disposition for the diff")
            return StageReturnV1(contract=contract, satisfied=False, evidence_refs=evidence_refs,
                                 unresolved=unresolved, reason="review disposition missing")
        return StageReturnV1(contract=contract, satisfied=True, evidence_refs=evidence_refs,
                             reason="current diff plus explicit review disposition")
    return StageReturnV1(contract=contract, satisfied=False, unresolved=["unknown return kind"],
                         reason="unknown return kind")


def delivery_supported() -> bool:
    """Delivery is a V5 capability; V3 never reports it."""
    return False


def refusal_payload(kind: str) -> dict:
    effects = sha256_text({"kind": kind, "effects": "none"})
    return {
        "supported": False,
        "status": "unsupported",
        "profile": "v0-v3",
        "reason": (
            "V0-V3 ends at a reviewable diagnostic, explanation or patch stage. "
            "Delivery/export and restore mutations require the V5 delivery profile and are disabled."
        ),
        "requestedKind": kind,
        "effectsApplied": 0,
        "effectsManifestHash": effects,
    }
