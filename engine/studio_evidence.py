"""Read-only projections from durable investigation receipts for Author Studio."""
import json

from .store import LedgerError
from .mutation_service import DOMAIN as MATRIX_DOMAIN
from .witness_service import DOMAIN


def _card(body, *, evidence_id, worker, historical, candidate_hash=None):
    case = body.get("input")
    complete = isinstance(case, str) and 0 < len(case.encode()) <= 12 * 1024
    return {
        "id": evidence_id, "claim": body.get("claimId"), "input": case if complete else None,
        "legal": body.get("legal") is True, "expected": body.get("expected"), "actual": body.get("actual"),
        "effect": body.get("invariant"), "candidate": body.get("candidateRef"),
        "sourceHash": candidate_hash, "comparison": body.get("comparison"), "worker": worker,
        "assumption": body.get("assumption"),
        "historical": historical, "classification": body.get("classification"),
        "diagnostics": body.get("code_spans") or [],
    }


def project_cards(store, run_id, messages):
    visible = {message["dedupe_key"] for message in messages}
    cards = {}
    for finding in store.list_findings(run_id):
        key = f"finding:{finding['id']}"
        if key not in visible:
            continue
        for evidence_id in finding.get("evidence_refs", [])[:4]:
            evidence = store.get_evidence(evidence_id)
            for digest in evidence.get("artifact_refs", [])[:4]:
                try:
                    payload = json.loads(store.get_blob(digest))
                except (LedgerError, ValueError):
                    continue
                if not isinstance(payload, dict) or payload.get("kind") != "diagnostic_witness":
                    continue
                cards[key] = _card(payload, evidence_id=evidence_id, worker=evidence.get("environment_ref"),
                                   historical=evidence.get("freshness") != "current",
                                   candidate_hash=payload.get("candidateHash"))
                cards[key]["replayable"] = (evidence["domain"] == "weighted_campaign" and
                                          evidence["classification"] == "counterexample" and
                                          evidence["freshness"] == "current")
                break
            if key in cards:
                break
    for message in messages:
        key = message["dedupe_key"] or ""
        if key.startswith("mutation-matrix:ev-"):
            evidence = store.get_evidence(key.split(":", 1)[1])
            if evidence["run_id"] == run_id and evidence["domain"] == MATRIX_DOMAIN and evidence["visibility"] == "author":
                report = json.loads(store.get_blob(evidence["artifact_refs"][0]))
                cards[key] = {"matrix": report, "historical": evidence["freshness"] != "current", "reportId": evidence["id"]}
            continue
        if not key.startswith("counterexample:ev-"):
            continue
        evidence = store.get_evidence(key.split(":", 1)[1])
        if evidence["run_id"] != run_id or evidence["domain"] != DOMAIN:
            continue
        report = json.loads(store.get_blob(evidence["artifact_refs"][0]))
        basis = store.get_evidence(report["parentEvidenceId"])
        original = {**report["original"], "candidateRef": report["candidateRef"], "claimId": report["claimId"]}
        versions = [_card(original, evidence_id=basis["id"], worker=basis["environment_ref"],
                          historical=basis["freshness"] != "current", candidate_hash=report["candidateHash"])]
        versions[0]["title"] = "Original input"
        checked = report["reduced"] or report["replay"]
        if checked:
            versions.append(_card({**checked, "candidateRef": report["candidateRef"]}, evidence_id=evidence["id"],
                                  worker=report["worker"], historical=evidence["freshness"] != "current",
                                  candidate_hash=report["candidateHash"]))
            versions[-1]["title"] = "Reduced input" if report["reduced"] else "Replay result"
        cards[key] = {"versions": versions, "reportId": evidence["id"]}
    for row in store.read_all(
        "SELECT receipt_json FROM package_checks WHERE run_id=? AND receipt_json IS NOT NULL", (run_id,)
    ):
        receipt = json.loads(row["receipt_json"])
        key = f"package-check:{receipt['id']}"
        failure = receipt.get("failure") or {}
        if key not in visible or failure.get("status") != "wrong_answer":
            continue
        body = {**failure, "claimId": "Reference agrees with the independent oracle",
                "candidateRef": failure.get("case_id"), "legal": True, "classification": "wrong_answer",
                "assumption": f"Endpoint rule: {receipt['semantics']}" if receipt.get("semantics") else None,
                "invariant": "The checked reference revision disagreed on this legal case."}
        cards[key] = _card(body, evidence_id=receipt["id"], worker=receipt.get("worker"), historical=True,
                           candidate_hash=receipt.get("sourceHash"))
    return cards
