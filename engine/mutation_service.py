"""Author-invoked weighted scheduling mutation matrices from saved inputs."""
from __future__ import annotations

from typing import Annotated

from pydantic import Field, StringConstraints

from .author_check import CheckRequest, current_campaign, run_check
from .domain.mutation import evaluate_matrix, registered_candidates
from .graph import Runtime
from .schemas import sha256_text
from .store import LedgerError, PublicationBlocked

DOMAIN = "weighted_mutation_matrix"
DEFAULT_BUDGET = {"cases": 32, "wall_ms": 20000, "oracle_subsets": 16384}


class MutationAction(CheckRequest):
    mutantRefs: list[Annotated[str, StringConstraints(pattern=r"^(art|contrib)-[a-f0-9]+$")]] = Field(
        default_factory=list, max_length=2,
    )


def run_action(runtime: Runtime, run_id: str, evidence_id: str, action: MutationAction) -> dict:
    def prepare(limits):
        basis, manifest = current_campaign(runtime, run_id, evidence_id)
        cases = manifest["cases"]
        if not cases or len({case["case_id"] for case in cases}) != len(cases):
            raise LedgerError("Campaign has no unique input set to test")
        semantics = manifest["semantics"]
        candidates = registered_candidates(semantics)
        if len(set(action.mutantRefs)) != len(action.mutantRefs):
            raise ValueError("Choose each authored mutant once.")
        for index, selected in enumerate(action.mutantRefs, start=1):
            ref, source, label = runtime.candidate_source(run_id, selected)
            candidates.append({"id": f"author-{index}", "label": label, "role": "mutant", "source": source,
                               "sourceRef": ref})
        width = len(candidates)
        batches = min(len(cases), limits["cases"] // width, getattr(runtime.worker, "batch_limit", 50))
        if batches < 1:
            raise PublicationBlocked("The remaining case budget cannot run one test against every selected candidate.")
        limits["cases"] = width * batches
        return cases, candidates, semantics, basis["manifest"]

    def evaluate(plan, limits, execute):
        cases, candidates, semantics, manifest_hash = plan
        report = evaluate_matrix(cases, candidates, semantics, limits, execute)
        report["manifest"] = manifest_hash
        usage = {"oracleSubsets": report["oracleSubsets"]}
        dependencies = {"manifest": manifest_hash, **{column["id"]: sha256_text(column["source"]) for column in candidates}}
        return report, usage, dependencies

    return run_check(runtime, run_id, evidence_id, action, domain=DOMAIN, prefix="mutation",
                     operation_kind="differential_search", defaults=DEFAULT_BUDGET,
                     request_data={"mutantRefs": action.mutantRefs}, prepare=prepare, evaluate=evaluate,
                     completed_statuses=("complete",))
