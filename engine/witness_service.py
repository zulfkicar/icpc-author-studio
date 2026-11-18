"""Owner-locked replay of an author-selected, recorded campaign witness."""
from __future__ import annotations

from typing import Literal

from .author_check import CheckRequest, current_campaign, receipt as check_receipt, run_check
from .domain.reduce import check_witness
from .graph import Runtime
from .schemas import sha256_text
from .store import ApplicationStore, LedgerError, PublicationBlocked

DOMAIN = "weighted_witness_followup"
DEFAULT_BUDGETS = {
    "replay": {"cases": 1, "wall_ms": 5000, "oracle_subsets": 4096},
    "reduce": {"cases": 16, "wall_ms": 15000, "oracle_subsets": 4096},
}


class WitnessAction(CheckRequest):
    action: Literal["replay", "reduce"]


def receipt(store: ApplicationStore, run_id: str, evidence_id: str) -> dict:
    return check_receipt(store, run_id, evidence_id, DOMAIN)


def run_action(runtime: Runtime, run_id: str, evidence_id: str, action: WitnessAction) -> dict:
    def prepare(limits):
        if action.action == "replay":
            limits["cases"] = min(limits["cases"], 1)
        report, manifest = current_campaign(runtime, run_id, evidence_id)
        witness = report.get("firstMismatch")
        if not witness or report["classification"] != "counterexample":
            raise LedgerError("Unknown replayable counterexample for this conversation")
        bound = next((case for case in manifest["cases"] if case["case_id"] == witness["case_id"]), None)
        if (not bound or not witness.get("legal") or witness["expected"] == witness["actual"]
                or any(bound[key] != witness[key] for key in ("input", "inputHash", "expected"))
                or sha256_text(witness["input"]) != bound["inputHash"]):
            raise LedgerError("The witness does not match its recorded input")
        try:
            _, source, _ = runtime.candidate_source(run_id, report["candidateRef"])
        except LedgerError as exc:
            raise PublicationBlocked("The recorded candidate is no longer current. Run a new campaign on the current source.") from exc
        if sha256_text(source) != report["candidateHash"]:
            raise PublicationBlocked("The recorded candidate hash changed. Run a new campaign on the current source.")
        return report, manifest["semantics"], witness, source

    def evaluate(plan, limits, execute):
        basis, semantics, original, source = plan
        def run_one(case_id, text):
            return execute(source, [{"case_id": case_id, "input": text}], case_id)

        report = check_witness(original, semantics, reduce=action.action == "reduce", limits=limits, execute=run_one)
        report.update(action=action.action, candidateRef=basis["candidateRef"], candidateHash=basis["candidateHash"],
                      semantics=semantics, claimId=basis["claimId"])
        usage = {"cases": len(report["trials"]), "oracleSubsets": report["oracleSubsets"]}
        return report, usage, {"candidate": basis["candidateHash"], "input": original["inputHash"]}

    return run_check(runtime, run_id, evidence_id, action, domain=DOMAIN, prefix="witness",
                     operation_kind="replay_diagnostic", defaults=DEFAULT_BUDGETS[action.action],
                     request_data=action.action, prepare=prepare, evaluate=evaluate,
                     completed_statuses=("reproduced", "reduced", "no_reduction", "not_reproduced"),
                     outcome="counterexample_followup")
