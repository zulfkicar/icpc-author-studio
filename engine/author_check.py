"""Durable admission and worker limits for author-invoked evidence checks."""
from __future__ import annotations

import json
import time
from typing import Annotated

from pydantic import StringConstraints

from .budget import parse_utc
from .domain.differential import CampaignBudget, CampaignError
from .graph import Runtime, _publication_fence
from .policy import PolicyDenied, operation_supported
from .schemas import EvidenceV1, Model, OperationResultV1, canonical_json, sha256_text
from .store import ApplicationStore, IdempotencyConflict, LedgerError, PublicationBlocked


class CheckRequest(Model):
    clientRequestId: Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_-]{1,100}$")]
    budget: CampaignBudget | None = None


def receipt(store: ApplicationStore, run_id: str, evidence_id: str, domain: str) -> dict:
    evidence = store.get_evidence(evidence_id)
    if evidence["run_id"] != run_id or evidence["domain"] != domain or evidence["visibility"] != "author":
        raise LedgerError("Unknown check receipt for this conversation")
    report = json.loads(store.get_blob(evidence["artifact_refs"][0]))
    return {"evidenceId": evidence_id, "freshness": evidence["freshness"], "report": report}


def current_campaign(runtime: Runtime, run_id: str, evidence_id: str) -> tuple[dict, dict]:
    store = runtime.store
    evidence = store.get_evidence(evidence_id)
    if (evidence["run_id"] != run_id or evidence["domain"] != "weighted_campaign"
            or evidence["visibility"] != "author"):
        raise LedgerError("Unknown campaign receipt for this conversation")
    if evidence["freshness"] != "current":
        raise PublicationBlocked("This campaign is earlier evidence. Run a new campaign with the current rules and source.")
    if not getattr(runtime.worker, "is_real", False) and not (evidence["environment_ref"] or "").startswith("fake-worker"):
        raise PublicationBlocked("This campaign used a real worker. Configure an isolated worker to run the check.")
    report = json.loads(store.get_blob(evidence["artifact_refs"][0]))
    manifest = json.loads(store.get_blob(report["manifest"]))
    collaboration = runtime.inputs.collaboration(run_id)
    decision = next((item for item in reversed(collaboration.get("decisions", []))
                     if item.get("requirementId") == "endpoint_semantics"), {})
    if (manifest["semantics"] not in ("half_open", "closed") or manifest["semantics"] != decision.get("optionId")
            or (manifest.get("endpointDecisionId") and manifest["endpointDecisionId"] != decision.get("id"))):
        raise PublicationBlocked("The endpoint rule changed. Run a new campaign under the current rule.")
    return report, manifest


def run_check(runtime: Runtime, run_id: str, evidence_id: str, request: CheckRequest, *, domain: str,
              prefix: str, operation_kind: str, defaults: dict, request_data: str | dict,
              prepare, evaluate, completed_statuses: tuple, outcome: str | None = None) -> dict:
    """Run under the caller's owner lease and publish a separate evidence receipt."""
    store = runtime.store
    run = store.get_run(run_id)
    requested = request.budget.model_dump() if request.budget else defaults
    operation_id = f"op-{prefix}-" + sha256_text({"run": run_id, "request": request.clientRequestId})[:16]
    request_hash = sha256_text({"evidence": evidence_id, "action": request_data, "budget": requested})
    existing = store.read_one("SELECT 1 FROM operations WHERE operation_id=?", (operation_id,))
    if existing:
        old = store.get_operation(operation_id)
        if old["request_hash"] != request_hash:
            raise IdempotencyConflict("Check request ID was used for a different action")
        result = old["result"]
        if result is None:
            result = store.commit_operation_result(operation_id, OperationResultV1(
                operation_id=operation_id, request_hash=old["request_hash"], input_revision=old["input_revision"],
                status="outcome_unknown", classification="outcome_unknown", retryability="not_retryable",
            ))["result"]
            store.settle_reservation(old["reservation_id"], "unknown")
        elif store.get_reservation(old["reservation_id"])["state"] == "reserved":
            store.settle_reservation(old["reservation_id"])
        if result["evidence_ids"]:
            return {**receipt(store, run_id, result["evidence_ids"][0], domain), "operationId": operation_id}
        return {"operationId": operation_id, "evidenceId": None, "status": result["classification"]}

    if run["active_operation_id"] or store.pending_interaction(run_id) or run["status"] == "cancelled":
        raise PublicationBlocked("Finish the current decision or investigation before running this check.")
    grant = store.active_grant(run_id) or {}
    expires = parse_utc(grant.get("expires_at"))
    if (not operation_supported(operation_kind, grant.get("operation_kinds", []))
            or (expires and expires <= runtime.clock.now())):
        raise PolicyDenied("The current run has no authority for this check.", "check_denied")
    if store.active_delegation(run_id):
        raise PublicationBlocked("Finish the delegated stage before starting a separate check.")
    budget = store.get_budget(run_id)
    limits = {**requested, "cases": min(requested["cases"], budget["cases_limit"] - budget["cases_used"]),
              "wall_ms": min(requested["wall_ms"], budget["wall_ms_limit"] - budget["wall_ms_used"])}
    plan = prepare(limits)
    if limits["cases"] < 1 or limits["wall_ms"] < 1000:
        raise PublicationBlocked("This run has no remaining case or execution-time budget.")

    epoch = (run["observed_revision"], run["goal_generation"], run["steering_epoch"], run["controller_epoch"])
    reservation = store.reserve_action(run_id, action_id=operation_id, attempts_limit=0,
                                       cases=limits["cases"], wall_ms=limits["wall_ms"])
    try:
        operation, _ = store.admit_operation(
            run_id, operation_id=operation_id, kind=operation_kind, request_hash=request_hash,
            input_revision=epoch[0], goal_generation=epoch[1], steering_epoch=epoch[2], controller_epoch=epoch[3],
            reservation_id=reservation["id"], case_charge=limits["cases"], wall_charge=limits["wall_ms"], activate=False,
        )
    except LedgerError:
        store.settle_reservation(reservation["id"], "cancelled")
        raise
    end = time.monotonic() + limits["wall_ms"] / 1000

    def current() -> bool:
        allowed, _ = _publication_fence(runtime, operation, epoch[3], store.get_run(run_id))
        active = store.active_grant(run_id) or {}
        return (allowed and active.get("id") == grant["id"] and (not expires or expires > runtime.clock.now())
                and store.get_evidence(evidence_id)["freshness"] == "current")

    dispatched = 0

    def execute(source: str, cases: list[dict], batch_id: str) -> dict:
        nonlocal dispatched
        if not current():
            raise CampaignError("stale", "The conversation or check authority changed during execution.")
        remaining = int((end - time.monotonic()) * 1000)
        if remaining <= 0:
            raise CampaignError("wall_budget", "The execution-time budget has been used.")
        if dispatched + len(cases) > limits["cases"]:
            raise CampaignError("case_budget", "The case budget has been used.")
        dispatched += len(cases)
        try:
            raw = runtime.worker.submit({"job_id": f"job:{operation_id}:{batch_id}", "kind": "differential_search",
                "campaign": operation_id, "candidate": {"source": source, "language": "cpp"},
                "cases": [{"case_id": case["case_id"], "input": case["input"]} for case in cases],
                "budget": {"cases": len(cases), "wall_ms": remaining, "memory_mib": 256, "output_bytes": 4096}})
        except Exception as exc:
            raise CampaignError("worker_error", "The configured worker could not execute the case batch.") from exc
        if not isinstance(raw, dict):
            raise CampaignError("worker_protocol_error", "The worker did not return a structured receipt.")
        if time.monotonic() >= end and raw.get("status") == "completed":
            return {**raw, "status": "incomplete", "truncation": {"reason": "deadline"}}
        return raw

    report, usage, dependencies = evaluate(plan, limits, execute)
    allowed = current()
    report.update(parentEvidenceId=evidence_id, limits=limits, requestedBudget=requested, dispatched=dispatched)
    usage.setdefault("cases", dispatched)
    digest = store.put_blob(canonical_json(report).encode(), kind=domain)
    new_id = "ev-" + sha256_text({"run": run_id, "op": operation_id})[:14]
    evidence = EvidenceV1(id=new_id, operation_id=operation_id, producer_kind="deterministic",
                          producer_version=domain + "-v1", domain=domain, outcome=outcome or domain,
                          input_refs=[evidence_id], dependency_hashes=dependencies, budget_requested=requested,
                          usage_observed=usage, classification=report["status"], freshness="current" if allowed else "stale",
                          artifact_refs=[digest], environment_ref=report["worker"])
    store.commit_operation_result(operation_id, OperationResultV1(
        operation_id=operation_id, request_hash=request_hash, input_revision=epoch[0],
        status="completed" if allowed and report["status"] in completed_statuses else "incomplete",
        classification=report["status"] if allowed else "stale", actual_limits=limits,
        evidence_ids=[new_id], usage=usage, artifacts={"report": digest},
        worker_identity=report["worker"], retryability="not_retryable",
    ), evidence, evidence_epoch=epoch, evidence_grant_id=grant["id"])
    store.settle_reservation(reservation["id"])
    return {**receipt(store, run_id, new_id, domain), "operationId": operation_id}
