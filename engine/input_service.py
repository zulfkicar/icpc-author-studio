"""Author ingress service: one durable input/idempotency path.

HTTP handlers call this service; it appends records and returns a receipt.
Applying input to goal/semantics happens later, under the single owner, in
``reconcile``.  Received and applied are therefore distinguishable states
(03 Â§Â§2,8; CR03, CR04).
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from .clock import Clock
from .decisions import effect_instruction_allowed
from .interpretation import canonical_endpoint_option, interpret_authorization
from .policy import (
    LOCAL_ACTOR,
    PolicyDenied,
    classify_free_text,
    classify_input_barrier,
    validate_contribution,
    validate_referenced_artifacts,
    validate_text,
)
from .schemas import (
    AuthorInputV1,
    HumanInteractionV1,
    StageReturnContract,
    canonical_json,
    sha256_text,
    validate_response_payload,
)
from .store import ApplicationStore, IdempotencyConflict, LedgerError, StaleBinding

ALLOWED_RESPONSE_KINDS = {
    "semantics": {"semantic_choice", "request_explanation", "reject", "defer", "claim"},
    "approach_choice": {"approach_preference", "semantic_choice", "request_explanation", "reject",
                        "defer", "claim"},
    "proof_challenge": {"claim", "request_explanation", "reject", "defer", "semantic_choice"},
    "explanation": {"request_explanation", "reject", "defer"},
    "test_contribution": {"contribution", "claim", "request_explanation", "reject", "defer"},
    "repair_review": {"edit_proposal", "authorize_effect", "reject", "defer",
                      "request_explanation", "claim"},
    "delegation": {"authorize_effect", "reject", "defer", "request_explanation", "claim"},
    "export_approval": {"authorize_effect", "reject", "defer"},
}

EXPLANATION_ONLY_KINDS = {"request_explanation"}


def _deadline_passed(value: str, clock=None) -> bool:
    from .budget import parse_utc

    parsed = parse_utc(value)
    now = clock.now() if clock is not None else __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc)
    return bool(parsed and parsed < now)


class InputService:
    def __init__(self, store: ApplicationStore, clock: Clock | None = None):
        self.store = store
        self.clock = clock or store.clock

    # ------------------------------------------------------------- create
    def create_run(self, *, workspace_id: str, idea: str,
                   client_request_id: str | None = None, profile: str = "batch-exact-integer-v1",
                   seed: dict | None = None, run_id: str | None = None,
                   budget_limits: dict | None = None, model_provider: str = "custom",
                   title: str | None = None) -> dict:
        from .policy import require_profile

        require_profile(profile)
        validate_text(idea, field="idea")
        if not idea.strip():
            raise ValueError("An idea is required")
        run = self.store.create_run(workspace_id, idea, capability_id=profile, run_id=run_id,
                                    budget_limits=budget_limits, model_provider=model_provider, title=title)
        key = client_request_id or "initial-" + run["run_id"]
        receipt = self.store.append_input(
            run["run_id"], kind="new_goal", text=idea, client_request_id=key,
            expected_generation=0,
        )
        # A session grant permits bounded joint investigation but never editing.
        self.store.create_grant(
            run["run_id"], actor_id=LOCAL_ACTOR,
            source_input_id=receipt["inputId"],
            operation_kinds=["read_artifact", "differential_search", "replay_diagnostic"],
            scope=["author-visible"], goal_generation=0,
        )
        if seed:
            self._apply_seed(run["run_id"], seed)
        return {"run": self.store.projection(run["run_id"]), "input": receipt}

    def _apply_seed(self, run_id: str, seed: dict) -> None:
        """Test/demo fixture seeding through canonical records, not hidden state."""
        if seed.get("goalText"):
            self.store.update_run(run_id, goal_text=str(seed["goalText"])[:200000])
        for key, value in seed.get("engagement", {}).items():
            if key in ("engagement", "explanation_depth"):
                self.set_preference(run_id, **{key: value})
        for contribution in seed.get("contributions", []):
            self.add_contribution_from_input(run_id, contribution)

    # ------------------------------------------------------------- inputs
    def submit_input(self, run_id: str, body: dict, *, actor: str = LOCAL_ACTOR) -> dict:
        self._reject_trusted_fields(body)
        kind = str(body.get("kind") or "")
        if kind not in ("new_goal", "steer", "contribute", "respond", "set_engagement", "cancel", "chat_turn"):
            raise PolicyDenied(f"Unknown input kind {kind!r}", "bad_schema")
        key = str(body.get("clientRequestId") or "").strip()
        if not key:
            raise PolicyDenied("clientRequestId is required", "bad_schema")
        text = validate_text(str(body.get("text") or ""), field="text")
        payload = body.get("payload") if isinstance(body.get("payload"), dict) else None
        refs = validate_referenced_artifacts(body.get("referencedArtifacts") or [])
        self._check_input_bounds(text, payload)
        expected = body.get("expectedGeneration")
        if expected is not None and not isinstance(expected, int):
            raise PolicyDenied("expectedGeneration must be an integer", "bad_schema")
        if kind == "contribute":
            self._validate_contribution_payload(payload)
            replacement = (payload or {}).get("originalBlobRef")
            if replacement and not self.store.read_one(
                    "SELECT 1 AS x FROM blobs WHERE hash=?", (replacement,)):
                raise PolicyDenied(
                    f"Unknown blob {replacement} for this run", "cross_run_blob")
        if kind == "set_engagement":
            classify_input_barrier(kind, payload)
        if kind == "respond":
            self._validate_response_input(payload)
        if body.get("text") or payload:
            self._ensure_nonempty(kind, text, payload)
        receipt = self.store.append_input(
            run_id,
            kind=kind,
            text=text,
            payload=payload,
            client_request_id=key,
            expected_generation=expected,
            referenced_artifacts=refs,
            resolves_input_id=body.get("resolvesInputId"),
            supersedes_input_id=body.get("supersedesInputId"),
        )
        return receipt

    def _reject_trusted_fields(self, body: dict) -> None:
        for field in ("runId", "actorId", "actor", "seq", "receivedSeq", "controllerEpoch",
                      "grant", "serverOwned", "steeringEpoch"):
            if field in body:
                raise PolicyDenied(f"{field} is server-owned and may not be supplied", "bad_schema")

    def _check_input_bounds(self, text: str, payload: dict | None) -> None:
        size = len(text.encode("utf-8"))
        if payload is not None:
            size += len(canonical_json(payload).encode("utf-8"))
        if size > 10 * 1024 * 1024:
            raise PolicyDenied("Input exceeds the 10 MiB input bound", "oversized")

    def _ensure_nonempty(self, kind: str, text: str, payload: dict | None) -> None:
        if kind == "set_engagement":
            if not payload:
                raise PolicyDenied("set_engagement requires engagement or explanation_depth", "bad_schema")
            return
        if not text.strip() and not payload:
            raise PolicyDenied("An input needs text or a typed payload", "bad_schema")

    def _validate_contribution_payload(self, payload: dict | None) -> None:
        if not isinstance(payload, dict):
            raise PolicyDenied("contribute requires a payload", "bad_schema")
        for forbidden in ("path", "filePath", "targetPath"):
            if forbidden in payload:
                raise PolicyDenied(f"{forbidden} is not accepted for contributions", "bad_path")
        for forbidden in ("runId", "actorId"):
            if forbidden in payload:
                raise PolicyDenied(f"{forbidden} is server-owned and may not be supplied", "bad_schema")
        kind = payload.get("contributionKind")
        if kind not in ("code", "lemma", "test", "idea"):
            raise PolicyDenied("contributionKind must be code|lemma|test|idea", "bad_schema")
        content = payload.get("content")
        if not isinstance(content, str):
            raise PolicyDenied("contribution content must be a string", "bad_schema")
        validate_contribution(content.encode("utf-8"))
        if payload.get("targetClaimIds") and not isinstance(payload["targetClaimIds"], list):
            raise PolicyDenied("targetClaimIds must be a list", "bad_schema")

    def _validate_response_input(self, payload: dict | None) -> None:
        if not isinstance(payload, dict):
            raise PolicyDenied("respond requires a tagged payload", "bad_schema")
        kind = payload.get("kind")
        if not kind:
            raise PolicyDenied("respond payload needs a kind", "bad_schema")
        validate_response_payload(kind, payload.get("payload") or {})

    def add_contribution_from_input(self, run_id: str, payload: dict,
                                    source_input_id: str | None = None,
                                    actor_kind: str = "human",
                                    actor_id: str = LOCAL_ACTOR) -> dict:
        content = str(payload.get("content") or "")
        blob_hash = self.store.put_blob(content.encode("utf-8"), kind="contribution")
        validate_contribution(content.encode("utf-8"))
        revision = self.store.get_run(run_id)["observed_revision"]
        replacement = payload.get("originalBlobRef")
        if replacement and not self.store.read_one("SELECT 1 AS x FROM blobs WHERE hash=?", (replacement,)):
            raise PolicyDenied(f"Unknown blob {replacement} for this run", "cross_run_blob")
        return self.store.add_contribution(
            run_id,
            source_input_id=source_input_id,
            actor_kind=actor_kind,
            actor_id=actor_id,
            kind=str(payload["contributionKind"]),
            blob_hash=blob_hash,
            revision=revision,
            claim_ids=list(payload.get("targetClaimIds") or []),
            attribution=str(payload.get("attribution") or ""),
            supersedes=payload.get("supersedes"),
        )

    # ------------------------------------------------------------- responses
    def submit_response(self, run_id: str, interaction_id: str, body: dict,
                        *, actor: str = LOCAL_ACTOR) -> dict:
        self._reject_trusted_fields(body)
        key = str(body.get("clientRequestId") or "").strip()
        if not key:
            raise PolicyDenied("clientRequestId is required", "bad_schema")
        kind = str(body.get("kind") or "")
        payload = body.get("payload")
        if not isinstance(payload, dict):
            raise PolicyDenied("payload must be an object", "bad_schema")
        if kind == "edit_proposal" and "replacement_text" in payload:
            text = payload.get("replacement_text")
            if not isinstance(text, str):
                raise PolicyDenied("replacement_text must be a string", "bad_schema")
            blob_body = text.encode("utf-8")
            validate_contribution(blob_body)
            payload = {
                "base_proposal_hash": payload.get("base_proposal_hash"),
                "replacement_blob_ref": self.store.put_blob(blob_body, kind="patch-content"),
                "rationale": payload.get("rationale"),
            }
        interaction = self.store.get_interaction(interaction_id)
        if interaction["run_id"] != run_id:
            raise PolicyDenied("Interaction belongs to a different run", "cross_run_artifact")
        allowed = ALLOWED_RESPONSE_KINDS.get(interaction["kind"], set())
        if kind not in allowed:
            raise PolicyDenied(
                f"Response kind {kind!r} is not valid for a {interaction['kind']} interaction",
                "bad_schema",
            )
        validate_response_payload(kind, payload)
        run = self.store.get_run(run_id)
        # Validate current binding before recording; stale is a typed conflict but
        # the original content is retained and the card stays visible.
        stale: list[str] = []
        expected_revision = body.get("expectedRevision")
        expected_generation = body.get("expectedGoalGeneration")
        expected_hash = body.get("expectedProposalHash")
        if expected_revision is not None and expected_revision != interaction["revision"]:
            stale.append("revision")
        if expected_generation is not None and int(expected_generation) != int(interaction["goal_generation"]):
            stale.append("goal_generation")
        if expected_hash is not None and expected_hash != interaction["proposal_hash"]:
            stale.append("proposal_hash")
        if interaction["status"] != "pending":
            stale.append("interaction_" + interaction["status"])
        receipt = self.store.append_response(
            run_id, interaction_id, actor_id=actor, kind=kind, payload=payload,
            client_request_id=key, expected_revision=expected_revision,
            expected_goal_generation=expected_generation,
            expected_proposal_hash=expected_hash,
        )
        receipt["currentBinding"] = self.store.stale_conflict_context(run_id, interaction_id)
        if stale:
            receipt["status"] = "conflict"
            receipt["stale"] = stale
            self.store.append_event(run_id, "response_stale", role="author",
                                    payload={"interactionId": interaction_id, "stale": stale})
        return receipt

    # ------------------------------------------------------------- preferences
    def set_preference(self, run_id: str, *, engagement: str | None = None,
                       explanation_depth: str | None = None,
                       preference_source: str = "author") -> dict:
        run = self.store.get_run(run_id)
        collab = json.loads(run["collaboration_json"] or "{}")
        if engagement is not None:
            if engagement not in ("together", "explain_as_we_go", "delegated"):
                raise PolicyDenied("Unknown engagement", "bad_schema")
            collab["engagement"] = engagement
        if explanation_depth is not None:
            if explanation_depth not in ("brief", "standard", "detailed"):
                raise PolicyDenied("Unknown explanation depth", "bad_schema")
            collab["explanation_depth"] = explanation_depth
            collab["preference_source"] = preference_source
        self.store.update_run(run_id, collaboration_json=canonical_json(collab))
        self.store.append_event(run_id, "preference_updated", role="author",
                                payload={"engagement": engagement, "depth": explanation_depth})
        return self.store.projection(run_id)["collaboration"]

    def collaboration(self, run_id: str) -> dict:
        run = self.store.get_run(run_id)
        collab = json.loads(run["collaboration_json"] or "{}")
        collab.setdefault("engagement", "together")
        collab.setdefault("explanation_depth", "standard")
        collab.setdefault("decisions", [])
        return collab

    # ------------------------------------------------------------- apply
    def apply_inbox(self, run_id: str) -> dict:
        """Interpret and disposition received inputs in arrival order.

        Cancellation/revocation always takes precedence.  ``resolvesInputId``
        and ``supersedesInputId`` let a later input unblock an earlier
        ambiguity; the earlier entry always receives a terminal disposition.
        """
        run = self.store.get_run(run_id)
        collab = self.collaboration(run_id)
        summary = {
            "applied": [], "needs_disambiguation": [], "semantic_change": False,
            "cancelled": False, "explanation_requests": [], "contributions": [],
            "deferred_handoff": False, "notes": [], "deferred": [],
        }
        inputs = self.store.received_inputs(run_id)
        # Cancellation of this run wins over everything, including a stale
        # expected generation.  It grants no new effect scope.
        for item in inputs:
            if item["kind"] != "cancel":
                continue
            self._apply_cancel(run_id, item, collab)
            summary["cancelled"] = True
            summary["applied"].append(item["id"])
        if summary["cancelled"]:
            for item in self.store.list_inputs(run_id):
                if item["kind"] != "cancel" and item["status"] in ("received", "interpreting"):
                    self.store.disposition_input(item["id"], "superseded", reason="cancelled")
            return summary

        for item in inputs:
            if item["kind"] == "cancel" or item["status"] != "received":
                continue
            if item["kind"] == "chat_turn":
                # The barrier exists before the decision call.  Mark it
                # interpreting under the owner so it no longer looks like a new
                # wake, while publication still fences on the barrier.
                self.store.disposition_input(
                    item["id"], "interpreting", reason="awaiting decision interpretation")
                summary["deferred"].append(item["id"])
                continue
            try:
                applied, semantic = self._apply_one(run_id, item, collab, summary)
            except LedgerError as exc:
                self.store.disposition_input(item["id"], "conflict", reason=str(exc))
                continue
            if applied == "needs_disambiguation":
                summary["needs_disambiguation"].append(item["id"])
                self.store.disposition_input(item["id"], "needs_disambiguation",
                                             reason="consequential ambiguity")
                continue
            if semantic:
                summary["semantic_change"] = True
            summary["applied"].append(item["id"])
            self.store.disposition_input(item["id"], "applied")
        # Settle resolutions/supersessions explicitly, even if the earlier item
        # never became executable.
        for item in self.store.list_inputs(run_id):
            earlier = item.get("resolves_input_id")
            supersede = item.get("supersedes_input_id")
            if earlier:
                self._terminal_earlier(run_id, earlier, "applied", "resolved by a later input")
            if supersede:
                self._terminal_earlier(run_id, supersede, "superseded", "superseded by a later input")
        return summary

    def _terminal_earlier(self, run_id: str, input_id: str, status: str, reason: str) -> None:
        try:
            earlier = self.store.get_input(input_id)
        except LedgerError:
            return
        if earlier["status"] in ("applied", "conflict", "superseded", "cancelled"):
            return
        self.store.disposition_input(input_id, status, reason=reason)

    def _apply_cancel(self, run_id: str, item: dict, collab: dict) -> None:
        self.store.disposition_input(item["id"], "cancelled", reason="author cancellation")
        self.store.withdraw_pending_interactions(run_id, "withdrawn")
        self.store.revoke_grants(run_id)
        self.store.invalidate_current_results(run_id, reason="cancelled")
        self.store.update_run(run_id, status="cancelled", stop_reason="cancelled",
                              continuation_json=None, pending_interaction_id=None)
        delegation = self.store.active_delegation(run_id)
        if delegation:
            self.store.set_delegation_status(delegation["id"], "revoked")
        self.store.append_event(run_id, "cancelled", role="author",
                                payload={"inputId": item["id"]})

    def _apply_one(self, run_id: str, item: dict, collab: dict, summary: dict) -> tuple[str, bool]:
        kind = item["kind"]
        if kind == "set_engagement":
            payload = item["payload"] or {}
            self.set_preference(
                run_id,
                engagement=payload.get("engagement"),
                explanation_depth=payload.get("explanation_depth"),
                preference_source=str(payload.get("preference_source") or "author"),
            )
            return "applied", False
        if kind == "new_goal":
            if int(item["generation_at_receipt"]) == int(self.store.get_run(run_id)["goal_generation"]) and \
                    self.store.get_run(run_id)["goal_generation"] == 0:
                interpretation = classify_free_text(item["text"], initial=True)
                authorization = interpret_authorization(item["text"])
                if interpretation["semanticAmbiguous"]:
                    summary["disambiguation_kind"] = "semantic"
                    summary["disambiguation_reason"] = interpretation["semanticReason"]
                    summary["disambiguation_input_id"] = item["id"]
                    return "needs_disambiguation", False
                if authorization.action == "ambiguous":
                    summary["authorization_ambiguity"] = {
                        "text": item["text"][:1500], "inputId": item["id"],
                        "paths": list(authorization.scope_paths),
                        "reason": authorization.reason,
                    }
                    return "needs_disambiguation", False
                self.store.update_run(run_id, goal_text=item["text"])
                if interpretation["endpointSemantics"]:
                    decisions = collab.setdefault("decisions", [])
                    if not any(d.get("requirementId") == "endpoint_semantics" for d in decisions):
                        decisions.append({
                            "id": "decision-" + sha256_text({"run": run_id, "input": item["id"]})[:10],
                            "requirementId": "endpoint_semantics",
                            "optionId": interpretation["endpointSemantics"],
                            "sourceId": item["id"],
                            "generation": 0,
                            "createdAt": self.clock.now_iso(),
                            "explicit": True,
                        })
                if interpretation["depth"]:
                    collab["explanation_depth"] = interpretation["depth"]
                    collab["preference_source"] = "explicit-initial-text"
                if interpretation["engagement"]:
                    collab["engagement"] = interpretation["engagement"]
                self.store.update_run(run_id, collaboration_json=canonical_json(collab))
                decision, grant = self.apply_instruction_authority(run_id, item, collab)
                self._maybe_delegate(run_id, item, collab, authorization=decision, grant=grant)
                return "applied", False
            self._semantic_change(run_id, reason="new goal", collab=collab,
                                  goal_text=item["text"], input_id=item["id"])
            return "applied", True
        if kind == "contribute":
            contribution = self.add_contribution_from_input(
                run_id, item["payload"] or {}, source_input_id=item["id"],
            )
            summary["contributions"].append(contribution["id"])
            self.store.append_event(run_id, "contribution_applied", role="human",
                                    payload={"contributionId": contribution["id"]})
            self._rebase_continuation(run_id, item["id"])
            return "applied", False
        if kind == "respond":
            payload = item["payload"] or {}
            rkind = payload.get("kind")
            if rkind == "request_explanation":
                summary["explanation_requests"].append(item)
                self._rebase_continuation(run_id, item["id"])
                return "applied", False
            return "applied", self._apply_input_response(run_id, item, collab, summary)
        if kind == "steer":
            record = self.store.decision_for_input(item["id"])
            if record is not None:
                acts = record["disposition"].get("acts") or []
                semantic_change = False
                semantic = next((a for a in acts if a["kind"] == "semantic_assertion"
                                 and a.get("admission") == "commit"), None)
                if semantic is not None:
                    semantic_change = self._decide_endpoint(
                        run_id, semantic["semantic_option"], item, collab)
                preference = next((a for a in acts if a["kind"] == "preference"), None)
                if preference is not None:
                    try:
                        payload = json.loads(preference.get("requested_work") or "{}")
                    except json.JSONDecodeError:
                        payload = {}
                    if payload:
                        self.set_preference(
                            run_id, engagement=payload.get("engagement"),
                            explanation_depth=payload.get("explanation_depth"),
                            preference_source="decision-admitted",
                        )
                decision, grant = self.apply_instruction_authority(run_id, item, collab)
                self._maybe_delegate(run_id, item, collab, authorization=decision, grant=grant)
                self._rebase_continuation(run_id, item["id"])
                summary["notes"].append(item["text"][:200])
                return "applied", semantic_change
            interpretation = classify_free_text(item["text"])
            authorization = interpret_authorization(item["text"])
            if interpretation["cancel"]:
                self._apply_cancel(run_id, item, collab)
                return "applied", False
            if interpretation["semanticAmbiguous"]:
                summary["disambiguation_kind"] = "semantic"
                summary["disambiguation_reason"] = interpretation["semanticReason"]
                summary["disambiguation_input_id"] = item["id"]
                return "needs_disambiguation", False
            if authorization.action == "ambiguous":
                summary["authorization_ambiguity"] = {
                    "text": item["text"][:1500], "inputId": item["id"],
                    "paths": list(authorization.scope_paths),
                    "reason": authorization.reason,
                }
                return "needs_disambiguation", False
            semantic_change = False
            if interpretation["endpointSemantics"]:
                semantic_change = self._decide_endpoint(
                    run_id, interpretation["endpointSemantics"], item, collab
                )
            if interpretation["depth"] or interpretation["engagement"]:
                self.set_preference(
                    run_id,
                    engagement=interpretation["engagement"],
                    explanation_depth=interpretation["depth"],
                    preference_source="interpreted-free-text",
                )
            if self._ambiguous_consequential(item):
                summary["disambiguation_kind"] = "semantic"
                summary["disambiguation_reason"] = "vague consequential instruction"
                summary["disambiguation_input_id"] = item["id"]
                return "needs_disambiguation", False
            decision, grant = self.apply_instruction_authority(run_id, item, collab)
            self._maybe_delegate(run_id, item, collab, authorization=decision, grant=grant)
            self._rebase_continuation(run_id, item["id"])
            summary["notes"].append(item["text"][:200])
            return "applied", semantic_change
        raise LedgerError(f"unsupported input kind {kind}")

    def _ambiguous_consequential(self, item: dict) -> bool:
        text = " ".join(item["text"].lower().split())
        return any(token in text for token in (
            "touch differently", "make them touch", "not sure", "maybe", "ambiguous",
            "either way", "you decide",
        ))

    def interpret_delegation(self, instruction: str, authorization=None) -> dict:
        """Interpret an explicit instruction into one typed return contract.

        No arbitrary executable predicate is accepted.  Only consequential
        ambiguity is asked; an explicit instruction is recorded directly.
        Edit authority is derived only from the host authorization decision,
        never from model text or a keyword hit.
        """
        import re

        auth = authorization or interpret_authorization(instruction)
        lowered = " ".join(instruction.lower().split())
        if any(token in lowered for token in ("counterexample", "witness", "find a case")):
            return_kind = "first_valid_witness"
        elif any(token in lowered for token in ("explain", "explanation", "why")):
            return_kind = "explanation_delivered"
        elif any(token in lowered for token in ("review the patch", "patch review", "review a patch")):
            return_kind = "patch_reviewed"
        else:
            return_kind = "campaign_complete"
        cap = None
        match = re.search(r"(?:at most|up to|within|max(?:imum)? of?)\s+(\d{1,6})\s+(?:tiny |small |)cases", lowered)
        if match:
            cap = int(match.group(1))
        edit_granted = auth.action == "grant" and auth.edit
        permitted = ["read_artifact", "differential_search", "replay_diagnostic"]
        if edit_granted:
            permitted.append("edit")
        scope: list[str] = []
        if cap is not None:
            scope.append(f"cases<={cap}")
        if edit_granted:
            scope.extend([f"path:{p}" for p in auth.scope_paths] or ["path:*"])
        excluded = ["export", "delivery", "restore", "mutation_campaign"]
        if not edit_granted:
            excluded.append("edit")
        return {
            "objective": instruction[:4000],
            "returnKind": return_kind,
            "returnPredicate": {
                "kind": return_kind,
                "caseCap": cap,
                "description": instruction[:1000],
            },
            "permittedOperations": permitted,
            "exclusions": excluded,
            "claimScope": ["H1"] if "greedy" in lowered else [],
            "budgetCeiling": {"modelAttemptsTotal": 3, "cases": cap or 100,
                              "wallSeconds": 120},
            "scope": scope or ["author-visible"],
            "authorization": auth.as_dict(),
        }

    _BASE_OPERATIONS = ("read_artifact", "differential_search", "replay_diagnostic")

    def _current_operations(self, run_id: str) -> set[str]:
        grant = self.store.active_grant(run_id)
        ops = set(grant["operation_kinds"]) if grant else set()
        ops.update(self._BASE_OPERATIONS)
        return ops

    def _contextual_binding_valid(self, run_id: str, collab: dict) -> tuple[bool, str]:
        target = collab.get("contextual_effect_target") or {}
        artifact_id = target.get("artifactId")
        if not artifact_id:
            return False, "no concrete artifact was bound to this effect"
        try:
            artifact = self.store.get_artifact(artifact_id)
        except LedgerError:
            return False, "the bound artifact no longer exists"
        if not artifact["current"] or artifact["validity"] not in ("current", "revalidated"):
            return False, "the bound artifact is no longer current"
        if target.get("artifactHash") and artifact["blob_hash"] != target["artifactHash"]:
            return False, "the bound artifact content changed"
        if target.get("revision") not in (None, artifact["revision"]):
            return False, "the bound artifact revision changed"
        if target.get("path") and target["path"] != artifact["path"]:
            return False, "the bound artifact path changed"
        return True, ""

    def authorize_contextual_edit(self, run_id: str, *, source_id: str, path: str,
                                  reason: str = "contextual chat repair authorization",
                                  proposal_hash: str | None = None,
                                  generation: int | None = None,
                                  artifact_id: str | None = None,
                                  revision: str | None = None,
                                  blob_hash: str | None = None) -> dict:
        """Authorize one exact, host-resolved artifact path for a repair.

        Used when the author asks to apply the discussion's proposed fix.  The
        path is resolved by the host from the current artifact/proposal, never
        supplied by the author in the message; this method owns the grant and
        ``author_edit_intent`` mutation so no second authority path appears.
        """
        clean = str(path or "").strip()
        parts = clean.replace("\\", "/").split("/")
        if not clean or clean.startswith(("/", "\\")) or ":" in parts[0] or ".." in parts:
            raise PolicyDenied("A contextual edit needs a repo-relative path", "bad_path")
        existing = self.store.read_all(
            "SELECT * FROM grants WHERE run_id=? AND source_input_id=? AND revoked_at IS NULL",
            (run_id, source_id))
        for grant in existing:
            kinds = json.loads(grant.get("operation_kinds_json") or "[]")
            scope = json.loads(grant.get("scope_json") or "[]")
            if "edit" in kinds and f"path:{clean}" in scope:
                return {"grantId": grant["id"], "scope": [f"path:{clean}"]}
        ops = self._current_operations(run_id)
        ops.update({"read_artifact", "differential_search", "replay_diagnostic", "edit"})
        grant = self.store.create_grant(
            run_id, actor_id=LOCAL_ACTOR, source_input_id=source_id,
            operation_kinds=sorted(ops), scope=[f"path:{clean}"],
            goal_generation=int(self.store.get_run(run_id)["goal_generation"]),
        )
        collab = self.collaboration(run_id)
        collab.pop("edit_denied", None)
        collab["author_edit_intent"] = {"value": "edit", "inputId": source_id,
                                        "reason": reason}
        collab["contextual_effect_target"] = {
            "path": clean, "chatMessageId": source_id, "grantId": grant["id"],
            "proposalHash": proposal_hash,
            "generation": int(generation if generation is not None
                              else self.store.get_run(run_id)["goal_generation"]),
            "artifactId": artifact_id,
            "revision": revision,
            "artifactHash": blob_hash,
        }
        self.store.update_run(run_id, collaboration_json=canonical_json(collab))
        self.store.append_event(run_id, "contextual_effect_authorized", role="host",
                                payload={"path": clean, "grantId": grant["id"],
                                         "chatMessageId": source_id})
        return {"grantId": grant["id"], "scope": [f"path:{clean}"]}

    def apply_instruction_authority(self, run_id: str, item: dict,
                                    collab: dict) -> tuple[Any, dict | None]:
        """Apply the host authorization decision for one author input.

        A revocation or exclusion fences edit publication and preserves grant
        history.  An affirmative instruction creates a narrower-or-equal grant.
        Ambiguity changes nothing and is surfaced to the caller for a
        clarification card.
        """
        decision = interpret_authorization(item["text"])
        record = self.store.decision_for_input(item["id"])
        if record is not None:
            acts = record["disposition"].get("acts") or []
            restrictions = [a for a in acts if a["kind"] in ("restriction", "cancel")]
            effects = [a for a in acts if a["kind"] == "effect_request"]
            if record["disposition"].get("status") != "admitted" and not restrictions:
                collab["author_edit_intent"] = {
                    "value": "information", "inputId": item["id"],
                    "reason": "decision record is unresolved; no effect admitted",
                    "at": self.clock.now_iso(),
                }
                self.store.update_run(run_id, collaboration_json=canonical_json(collab))
                self.store.append_event(run_id, "author_edit_intent", role="author",
                                        payload={"inputId": item["id"],
                                                 "intent": "information",
                                                 "decisionId": record["id"],
                                                 "reason": "unresolved decision record"})
                return decision, None
            if restrictions:
                revoked = self.store.revoke_grants(run_id, operation_kind="edit")
                collab["edit_denied"] = {
                    "inputId": item["id"],
                    "reason": "the author restricted the effect",
                    "action": "deny", "at": self.clock.now_iso(),
                    "decisionId": record["id"],
                }
                collab.pop("pending_patch_review", None)
                collab.pop("patch_edits", None)
                run = self.store.get_run(run_id)
                continuation = json.loads(run["continuation_json"] or "null") or {}
                if continuation.get("child") == "editing":
                    self.store.update_run(run_id, continuation_json=None,
                                          active_operation_id=None)
                self.store.update_run(run_id, collaboration_json=canonical_json(collab))
                self.store.append_event(run_id, "edit_authority_denied", role="author",
                                        payload={"inputId": item["id"],
                                                 "reason": "admitted restriction",
                                                 "decisionId": record["id"],
                                                 "revokedGrantIds": revoked,
                                                 "historyPreserved": True})
                return decision, None
            if effects:
                run = self.store.get_run(run_id)
                allowed, why = effect_instruction_allowed(item["text"])
                stale = (int(record["context_generation"] or 0) != int(run["goal_generation"])
                         or (record["context_revision"] not in (None, run["observed_revision"])))
                binding_ok, binding_why = self._contextual_binding_valid(run_id, collab)
                if not allowed or stale or not binding_ok:
                    revoked = self.store.revoke_grants(run_id, operation_kind="edit")
                    collab["edit_denied"] = {
                        "inputId": item["id"],
                        "reason": why if not allowed else (
                            "stale decision context" if stale else binding_why),
                        "action": "deny", "at": self.clock.now_iso(),
                        "decisionId": record["id"],
                    }
                    collab.pop("pending_patch_review", None)
                    collab.pop("patch_edits", None)
                    continuation = json.loads(run["continuation_json"] or "null") or {}
                    if continuation.get("child") == "editing":
                        self.store.update_run(run_id, continuation_json=None,
                                              active_operation_id=None)
                    self.store.update_run(run_id, collaboration_json=canonical_json(collab))
                    self.store.append_event(run_id, "edit_authority_denied", role="host",
                                            payload={"inputId": item["id"],
                                                     "reason": "effect admission rejected",
                                                     "detail": (why if not allowed else
                                                                ("stale context" if stale
                                                                 else binding_why)),
                                                     "decisionId": record["id"],
                                                     "revokedGrantIds": revoked,
                                                     "historyPreserved": True})
                    return decision, None
                collab["author_edit_intent"] = {
                    "value": "edit", "inputId": item["id"],
                    "reason": "admitted contextual effect request",
                    "decisionId": record["id"], "at": self.clock.now_iso(),
                }
                collab.pop("edit_denied", None)
                self.store.update_run(run_id, collaboration_json=canonical_json(collab))
                self.store.append_event(run_id, "author_edit_intent", role="author",
                                        payload={"inputId": item["id"], "intent": "edit",
                                                 "decisionId": record["id"],
                                                 "reason": "admitted contextual effect request"})
                return decision, None
            collab["author_edit_intent"] = {
                "value": "information", "inputId": item["id"],
                "reason": "decision record admits no effect",
                "decisionId": record["id"], "at": self.clock.now_iso(),
            }
            self.store.update_run(run_id, collaboration_json=canonical_json(collab))
            self.store.append_event(run_id, "author_edit_intent", role="author",
                                    payload={"inputId": item["id"], "intent": "information",
                                             "decisionId": record["id"]})
            return decision, None
        if decision.intent in ("edit", "information", "review", "restricted", "ambiguous"):
            collab["author_edit_intent"] = {
                "value": decision.intent, "inputId": item["id"],
                "reason": decision.reason, "at": self.clock.now_iso(),
            }
        if decision.action in ("revoke", "deny"):
            revoked = self.store.revoke_grants(run_id, operation_kind="edit")
            collab["edit_denied"] = {
                "inputId": item["id"], "reason": decision.reason,
                "action": decision.action, "at": self.clock.now_iso(),
            }
            collab.pop("pending_patch_review", None)
            collab.pop("patch_edits", None)
            run = self.store.get_run(run_id)
            continuation = json.loads(run["continuation_json"] or "null") or {}
            if continuation.get("child") == "editing":
                self.store.update_run(run_id, continuation_json=None, active_operation_id=None)
            self.store.update_run(run_id, collaboration_json=canonical_json(collab))
            self.store.append_event(
                run_id,
                "edit_authority_revoked" if decision.action == "revoke"
                else "edit_authority_denied",
                role="author",
                payload={"inputId": item["id"], "reason": decision.reason,
                         "revokedGrantIds": revoked,
                         "historyPreserved": True},
            )
            return decision, None
        if decision.action == "grant":
            collab.pop("edit_denied", None)
            scope = [f"path:{p}" for p in decision.scope_paths] or ["path:*"]
            ops = self._current_operations(run_id)
            ops.add("edit")
            grant = self.store.create_grant(
                run_id, actor_id=LOCAL_ACTOR, source_input_id=item["id"],
                operation_kinds=sorted(ops), scope=scope,
                goal_generation=int(self.store.get_run(run_id)["goal_generation"]),
            )
            self.store.update_run(run_id, collaboration_json=canonical_json(collab))
            self.store.append_event(run_id, "edit_authority_granted", role="author",
                                    payload={"inputId": item["id"], "grantId": grant["id"],
                                             "scope": scope, "reason": decision.reason})
            return decision, grant
        # A recognized information-only or neutral request must not silently
        # renew an old grant, but its intent is recorded so an adversarial edit
        # proposal is refused without a compulsory repair ceremony.
        self.store.update_run(run_id, collaboration_json=canonical_json(collab))
        self.store.append_event(run_id, "author_edit_intent", role="author",
                                payload={"inputId": item["id"], "intent": decision.intent,
                                         "action": decision.action, "reason": decision.reason})
        return decision, None

    def _maybe_delegate(self, run_id: str, item: dict, collab: dict | None = None,
                        authorization=None, grant: dict | None = None) -> dict | None:
        import re

        text = item["text"]
        lowered = text.lower()
        delegation_cue = bool(re.search(
            r"\b(investigate|delegate|compare|test|check|find a counterexample|return a|verify|"
            r"review a patch|run .*cases)\b", lowered))
        if not delegation_cue:
            return None
        auth = authorization or interpret_authorization(text)
        interpretation = self.interpret_delegation(text, authorization=auth)
        if grant is None:
            ops = self._current_operations(run_id)
            if auth.action == "grant" and auth.edit:
                ops.add("edit")
            existing = self.store.active_grant(run_id)
            if auth.action == "grant" and auth.edit:
                paths = [f"path:{p}" for p in auth.scope_paths] or ["path:*"]
            elif existing and "edit" in set(existing.get("operation_kinds") or []):
                # A non-edit follow-up must not broaden an existing path scope.
                paths = [s for s in (existing.get("scope") or [])
                         if isinstance(s, str) and s.startswith("path:")] or ["author-visible"]
            else:
                paths = ["author-visible"]
            scope = paths
            scope.extend(s for s in interpretation["scope"] if s.startswith("cases<="))
            grant = self.store.create_grant(
                run_id, actor_id=LOCAL_ACTOR, source_input_id=item["id"],
                operation_kinds=sorted(ops), scope=scope,
                goal_generation=int(self.store.get_run(run_id)["goal_generation"]),
            )
        delegation = self.store.create_delegation(
            run_id,
            objective=interpretation["objective"],
            permitted_operations=interpretation["permittedOperations"],
            exclusions=interpretation["exclusions"],
            claim_scope=interpretation["claimScope"],
            budget_ceiling=interpretation["budgetCeiling"],
            deadline=item.get("deadline"),
            return_predicate=interpretation["returnPredicate"],
            grant_ref=grant["id"],
            return_kind=interpretation["returnKind"],
            return_target_refs=["H1"] if "greedy" in lowered else [],
            required_evidence_kinds=["diagnostic_witness"] if interpretation["returnKind"] == "first_valid_witness" else ["explanation"],
        )
        self.store.append_event(run_id, "delegation_recorded", role="author", payload={
            "delegationId": delegation["id"], "returnKind": interpretation["returnKind"],
            "grantId": grant["id"],
        })
        return delegation

    def _apply_input_response(self, run_id: str, item: dict, collab: dict, summary: dict) -> bool:
        """A response submitted through the input endpoint delegates to the
        response service by creating a typed response record; the interaction
        binding is checked there."""
        payload = item["payload"] or {}
        interaction_id = payload.get("interactionId")
        if not interaction_id:
            raise LedgerError("respond payload needs interactionId")
        interaction = self.store.get_interaction(interaction_id)
        if interaction["status"] != "pending":
            raise LedgerError("interaction is not pending")
        receipt = self.store.append_response(
            run_id, interaction_id,
            actor_id=LOCAL_ACTOR,
            kind=payload.get("kind"),
            payload=payload.get("payload") or {},
            client_request_id="input:" + item["id"],
            expected_revision=interaction["revision"],
            expected_goal_generation=interaction["goal_generation"],
            expected_proposal_hash=interaction["proposal_hash"],
        )
        return self.apply_responses(run_id, collab)[0]

    # ------------------------------------------------------------- responses apply
    def apply_responses(self, run_id: str, collab: dict | None = None) -> tuple[bool, dict]:
        collab = collab or self.collaboration(run_id)
        summary = {"applied": [], "semantic_change": False, "deferred": False,
                   "explanation_requests": [], "rejected": []}
        run = self.store.get_run(run_id)
        if run["status"] == "cancelled":
            rows = self.store.read_all(
                "SELECT id FROM responses WHERE run_id=? AND applied=0 AND status='receipt'",
                (run_id,),
            )
            for row in rows:
                self.store.apply_response(row["id"], status="conflict", close=False)
            return False, summary
        rows = self.store.read_all(
            "SELECT id FROM responses WHERE run_id=? AND applied=0 AND status='receipt' ORDER BY received_seq",
            (run_id,),
        )
        for row in rows:
            response = self.store.get_response(row["id"])
            interaction = self.store.get_interaction(response["interaction_id"])
            run = self.store.get_run(run_id)
            if interaction["status"] != "pending":
                self.store.apply_response(response["id"], status="conflict", close=False)
                continue
            if response["expected_revision"] not in (None, interaction["revision"]) or \
                    response["expected_goal_generation"] not in (None, interaction["goal_generation"]) or \
                    response["expected_proposal_hash"] not in (None, interaction["proposal_hash"]):
                self.store.apply_response(response["id"], status="conflict", close=False)
                continue
            if int(interaction["goal_generation"]) != int(run["goal_generation"]) and \
                    response["kind"] != "request_explanation":
                # The context changed after the card was issued: retain response,
                # keep the card, do not apply stale semantics/effects.
                self.store.apply_response(response["id"], status="conflict", close=False)
                self.store.append_event(run_id, "response_stale", role="host",
                                        payload={"responseId": response["id"],
                                                 "reason": "goal generation changed"})
                continue
            semantic = False
            try:
                semantic = self._apply_response(run_id, response, interaction, collab, summary)
            except (LedgerError, PolicyDenied) as exc:
                self.store.apply_response(response["id"], status="conflict", close=False)
                self.store.append_event(run_id, "response_conflict", role="host",
                                        payload={"responseId": response["id"],
                                                 "reason": str(exc)[:500]})
                summary.setdefault("conflicts", []).append(response["id"])
                continue
            if semantic:
                summary["semantic_change"] = True
            summary["applied"].append(response["id"])
        return summary["semantic_change"], summary

    def _apply_response(self, run_id: str, response: dict, interaction: dict,
                        collab: dict, summary: dict) -> bool:
        kind = response["kind"]
        payload = response["payload"]
        if kind == "request_explanation":
            self.store.apply_response(response["id"], close=False)
            summary["explanation_requests"].append({
                "responseId": response["id"],
                "question": payload.get("question") or interaction["why"],
                "targetRef": payload.get("target_ref"),
                "depth": payload.get("depth"),
            })
            self.store.append_event(run_id, "explanation_requested", role="author",
                                    payload={"interactionId": interaction["id"],
                                             "question": payload.get("question") or ""})
            return False
        if kind == "semantic_choice":
            requirement = payload.get("requirement_id")
            if requirement not in (None, "", "endpoint_semantics", interaction["kind"]):
                raise LedgerError(f"unknown requirement {requirement!r} for this interaction")
            option = payload.get("option_id")
            options = {str(o.get("id")) for o in interaction["options"]}
            if option is not None and option not in options:
                raise LedgerError(f"option {option!r} is not on the current decision card")
            definition = payload.get("definition_text")
            if option is None and not definition:
                raise LedgerError("semantic_choice needs option_id or definition_text")
            canonical = canonical_endpoint_option(option)
            if interaction["kind"] == "semantics" and canonical:
                payload = {**payload, "option_id": canonical}
            self._record_decision(run_id, interaction, payload, response["id"], collab)
            self.store.apply_response(response["id"], close=True)
            self._semantic_change(run_id, reason="author semantic choice",
                                  collab=collab, input_id=response["id"], response_id=response["id"],
                                  interaction_id=interaction["id"])
            return True
        if kind == "approach_preference":
            collab.setdefault("approach_preferences", []).append({
                "approachId": payload.get("approach_id"),
                "rationale": payload.get("rationale"),
                "responseId": response["id"],
                "generation": self.store.get_run(run_id)["goal_generation"],
            })
            self.store.update_run(run_id, collaboration_json=canonical_json(collab))
            self.store.apply_response(response["id"], close=True)
            self.store.append_event(run_id, "approach_preference", role="author",
                                    payload={"approachId": payload.get("approach_id")})
            return False
        if kind == "claim":
            text = str(payload.get("text") or "")
            if not text.strip():
                raise LedgerError("claim text is empty")
            blob_hash = self.store.put_blob(text.encode("utf-8"), kind="claim")
            contribution = self.store.add_contribution(
                run_id, source_input_id=None, actor_kind="human", actor_id=LOCAL_ACTOR,
                kind="lemma", blob_hash=blob_hash,
                revision=self.store.get_run(run_id)["observed_revision"],
                claim_ids=list(payload.get("assumption_ids") or []),
                attribution="author claim (unvalidated)",
            )
            summary.setdefault("claims", []).append(contribution["id"])
            self.store.apply_response(response["id"], close=False)
            self.store.append_event(run_id, "claim_recorded", role="human",
                                    payload={"contributionId": contribution["id"],
                                             "interactionId": interaction["id"]})
            return False
        if kind == "contribution":
            contribution = self.add_contribution_from_input(run_id, {
                "contributionKind": payload.get("kind"),
                "content": self.store.get_blob(payload.get("original_blob_ref")).decode("utf-8"),
                "targetClaimIds": payload.get("target_claim_ids") or [],
                "attribution": payload.get("attribution") or "author",
            }, source_input_id=None)
            summary.setdefault("contributions", []).append(contribution["id"])
            self.store.apply_response(response["id"], close=True)
            return False
        if kind == "edit_proposal":
            if interaction["kind"] != "repair_review":
                raise LedgerError("edit_proposal is only valid for repair review")
            base = payload.get("base_proposal_hash")
            if base != interaction["proposal_hash"]:
                raise LedgerError("edited proposal is based on a different diff")
            replacement = payload.get("replacement_blob_ref")
            if replacement and not self.store.read_one("SELECT 1 AS x FROM blobs WHERE hash=?", (replacement,)):
                raise LedgerError(f"unknown replacement blob {replacement!r}")
            collab.setdefault("patch_edits", []).append({
                "interactionId": interaction["id"],
                "baseProposalHash": base,
                "replacementBlobRef": replacement,
                "responseId": response["id"],
            })
            collab.setdefault("pending_patch_review", {})[interaction["id"]] = {
                "baseProposalHash": base,
                "replacementBlobRef": replacement,
                "responseId": response["id"],
            }
            import re as _re

            path = None
            for ref in interaction.get("evidence_refs") or []:
                try:
                    body = self.store.get_blob(ref).decode("utf-8", "replace")
                except LedgerError:
                    continue
                match = _re.search(
                    r"(?:\+\+\+|\bpath\b\s*[:=])\s*([A-Za-z0-9_./-]+)", body)
                if match:
                    path = match.group(1)
                    break
            if path:
                ops = self._current_operations(run_id)
                ops.add("edit")
                grant = self.store.create_grant(
                    run_id, actor_id=LOCAL_ACTOR, source_input_id=response["id"],
                    operation_kinds=sorted(ops), scope=[f"path:{path}"],
                    goal_generation=int(self.store.get_run(run_id)["goal_generation"]),
                )
                collab.pop("edit_denied", None)
                collab["author_edit_intent"] = {
                    "value": "edit", "inputId": response["id"],
                    "reason": "author edited and submitted the exact reviewed diff",
                }
                collab["contextual_effect_target"] = {
                    "path": path, "artifactId": None,
                    "grantId": grant["id"],
                    "generation": int(self.store.get_run(run_id)["goal_generation"]),
                }
                self.store.append_event(
                    run_id, "edit_authority_granted", role="author",
                    payload={"responseId": response["id"], "grantId": grant["id"],
                             "scope": [f"path:{path}"], "reason": "reviewed edit"})
            self.store.update_run(run_id, collaboration_json=canonical_json(collab))
            self.store.apply_response(response["id"], close=True)
            self.store.append_event(run_id, "patch_edited", role="human",
                                    payload={"interactionId": interaction["id"],
                                             "replacementBlobRef": replacement})
            return False
        if kind == "authorize_effect":
            if interaction["kind"] == "export_approval":
                from .policy import UnsupportedProfile as _Unsupported

                self.store.apply_response(response["id"], close=True)
                raise LedgerError("delivery/export is unsupported in V0-V3")
            collab.setdefault("effect_authorizations", []).append({
                "interactionId": interaction["id"],
                "effectManifestHash": payload.get("effect_manifest_hash"),
                "grantScopeRef": payload.get("grant_scope_ref"),
                "responseId": response["id"],
            })
            if interaction["kind"] == "delegation":
                scope_ref = str(payload.get("grant_scope_ref") or "path:*")
                scope = [scope_ref] if scope_ref.startswith("path:") else [f"path:{scope_ref}"]
                ops = self._current_operations(run_id)
                ops.add("edit")
                grant = self.store.create_grant(
                    run_id, actor_id=LOCAL_ACTOR, source_input_id=response["id"],
                    operation_kinds=sorted(ops), scope=scope,
                    goal_generation=int(self.store.get_run(run_id)["goal_generation"]),
                )
                collab.pop("edit_denied", None)
                self.store.append_event(run_id, "edit_authority_granted", role="author",
                                        payload={"responseId": response["id"],
                                                 "grantId": grant["id"], "scope": scope})
            elif interaction["kind"] == "repair_review":
                scope_ref = str(payload.get("grant_scope_ref") or "")
                if scope_ref:
                    scope = [scope_ref] if scope_ref.startswith("path:") else [f"path:{scope_ref}"]
                    ops = self._current_operations(run_id)
                    ops.add("edit")
                    grant = self.store.create_grant(
                        run_id, actor_id=LOCAL_ACTOR, source_input_id=response["id"],
                        operation_kinds=sorted(ops), scope=scope,
                        goal_generation=int(self.store.get_run(run_id)["goal_generation"]),
                    )
                    collab.pop("edit_denied", None)
                    collab["author_edit_intent"] = {
                        "value": "edit", "inputId": response["id"],
                        "reason": "author approved the concrete repair card",
                    }
                    self.store.append_event(run_id, "edit_authority_granted", role="author",
                                            payload={"responseId": response["id"],
                                                     "grantId": grant["id"], "scope": scope})
            self.store.update_run(run_id, collaboration_json=canonical_json(collab))
            self.store.apply_response(response["id"], close=True)
            return False
        if kind == "reject":
            self.store.apply_response(response["id"], close=True)
            summary["rejected"].append({"interactionId": interaction["id"],
                                        "reason": payload.get("reason")})
            if interaction["kind"] == "repair_review":
                # Rejection leaves the source intact and ends this patch attempt.
                run = self.store.get_run(run_id)
                continuation = json.loads(run["continuation_json"] or "null") or {}
                if continuation.get("child") == "editing":
                    self.store.update_run(run_id, continuation_json=None,
                                          active_operation_id=None)
                collab.pop("pending_patch_review", None)
                self.store.update_run(run_id, collaboration_json=canonical_json(collab))
            self.store.append_event(run_id, "proposal_rejected", role="author",
                                    payload={"interactionId": interaction["id"],
                                             "reason": payload.get("reason") or ""})
            # Rejection never approves an alternative and never edits source.
            return False
        if kind == "defer":
            self.store.apply_response(response["id"], close=True)
            summary["deferred"] = True
            self.store.append_event(run_id, "deferred", role="author",
                                    payload={"interactionId": interaction["id"],
                                             "next": payload.get("requested_next_step")})
            return False
        raise LedgerError(f"unsupported response kind {kind}")

    # ------------------------------------------------------------- semantics
    def _record_decision(self, run_id: str, interaction: dict, payload: dict,
                         source_id: str, collab: dict) -> None:
        decisions = collab.setdefault("decisions", [])
        decisions.append({
            "id": "decision-" + sha256_text({"run": run_id, "src": source_id})[:10],
            "interactionId": interaction["id"],
            "requirementId": payload.get("requirement_id"),
            "optionId": payload.get("option_id"),
            "definitionText": payload.get("definition_text"),
            "sourceId": source_id,
            "generation": int(self.store.get_run(run_id)["goal_generation"]) + 1,
            "createdAt": self.clock.now_iso(),
        })
        self.store.update_run(run_id, collaboration_json=canonical_json(collab))

    def _decide_endpoint(self, run_id: str, semantics: str, item: dict, collab: dict) -> bool:
        decisions = collab.setdefault("decisions", [])
        current = next((d for d in reversed(decisions) if d.get("requirementId") == "endpoint_semantics"), {})
        if current.get("optionId") == semantics:
            return False
        decisions.append({
            "id": "decision-" + sha256_text({"run": run_id, "input": item["id"]})[:10],
            "requirementId": "endpoint_semantics",
            "optionId": semantics,
            "sourceId": item["id"],
            "generation": int(self.store.get_run(run_id)["goal_generation"]) + 1,
            "createdAt": self.clock.now_iso(),
        })
        self.store.update_run(run_id, collaboration_json=canonical_json(collab))
        self._semantic_change(run_id, reason="author endpoint correction", collab=collab,
                              input_id=item["id"])
        return True

    def _semantic_change(self, run_id: str, *, reason: str, collab: dict,
                         goal_text: str | None = None, input_id: str | None = None,
                         response_id: str | None = None, interaction_id: str | None = None) -> None:
        run = self.store.get_run(run_id)
        generation = int(run["goal_generation"]) + 1
        spec_hash = sha256_text({"goal": goal_text or run["goal_text"],
                                 "decisions": collab.get("decisions", []),
                                 "profile": run["scope_profile_id"]})
        carried_files = list(self.store.get_revision(run["observed_revision"])["files"])
        updates: dict[str, Any] = {
            "goal_generation": generation,
            "spec_hash": spec_hash,
            "continuation_json": None,
            "status": "running",
            "stop_reason": None,
        }
        if goal_text is not None:
            updates["goal_text"] = goal_text[:200000]
        self.store.update_run(run_id, **updates)
        self.store.create_revision(
            run_id, run["observed_revision"], carried_files, created_by="author-semantic-change",
            spec_hash=spec_hash,
        )
        invalidated = self.store.invalidate_current_results(run_id, reason=reason)
        # A semantic choice supersedes pending cards that depended on old semantics,
        # except the card currently being answered.
        if interaction_id:
            self.store.withdraw_pending_interactions(run_id, "superseded")
            with self.store.tx() as conn:
                conn.execute("UPDATE interactions SET status='answered' WHERE id=?", (interaction_id,))
        else:
            self.store.withdraw_pending_interactions(run_id, "superseded")
        self.store.append_event(run_id, "semantic_change", role="author", payload={
            "generation": generation, "reason": reason, "inputId": input_id,
            "responseId": response_id, "invalidated": invalidated,
        })

    def _rebase_continuation(self, run_id: str, input_id: str) -> None:
        run = self.store.get_run(run_id)
        if not run["continuation_json"]:
            return
        continuation = json.loads(run["continuation_json"])
        if continuation.get("steering_epoch") == int(run["steering_epoch"]):
            return
        continuation["rebased_from"] = continuation.get("steering_epoch")
        continuation["steering_epoch"] = int(run["steering_epoch"])
        self.store.update_run(run_id, continuation_json=canonical_json(continuation))
        self.store.append_event(run_id, "continuation_rebased", role="host",
                                payload={"inputId": input_id, "reservation": continuation.get("reservation_id")})

    # ------------------------------------------------------------- grant
    def project_grant(self, run_id: str, instruction: str, payload: dict | None = None) -> dict:
        """Derive a grant only from an explicit author instruction.

        Model-proposed scope can narrow it, never expand it.  An already
        explicit authorized instruction does not need a redundant ceremony.
        """
        ops = ["read_artifact"]
        lowered = instruction.lower()
        if any(token in lowered for token in ("test", "investigate", "check", "search", "witness",
                                              "campaign", "compare", "replay")):
            ops.append("differential_search")
            ops.append("replay_diagnostic")
        if any(token in lowered for token in ("edit", "patch", "repair", "fix", "change the code")):
            ops.append("edit")
        return self.store.create_grant(
            run_id, actor_id=LOCAL_ACTOR,
            source_input_id=str(payload.get("sourceInputId") if payload else "instruction"),
            operation_kinds=sorted(set(ops)),
            scope=list(payload.get("scope") if payload else []) or ["author-visible"],
            goal_generation=int(self.store.get_run(run_id)["goal_generation"]),
        )

    # ------------------------------------------------------------- view
    def view(self, run_id: str) -> dict:
        run = self.store.get_run(run_id)
        collab = self.collaboration(run_id)
        pending = self.store.pending_interaction(run_id)
        contributions = self.store.list_contributions(run_id)
        return {
            "runId": run_id,
            "workspaceId": run["workspace_id"],
            "schemaVersion": run["schema_version"],
            "status": run["status"],
            "stopReason": run["stop_reason"],
            "title": run["title"],
            "revision": run["observed_revision"],
            "goalGeneration": run["goal_generation"],
            "steeringEpoch": run["steering_epoch"],
            "controllerEpoch": run["controller_epoch"],
            "appliedAuthorSeq": run["applied_author_seq"],
            "capability": run["capability_id"],
            "profile": run["scope_profile_id"],
            "collaboration": collab,
            "editDenied": collab.get("edit_denied"),
            "pendingDecision": self._decision_card(pending) if pending else None,
            "contributions": [
                {
                    "id": c["id"], "kind": c["kind"], "actorKind": c["actor_kind"],
                    "actorId": c["actor_id"], "validationStatus": c["validation_status"],
                    "blobHash": c["original_blob_hash"], "attribution": c["attribution"],
                    "revision": c["revision"], "supersedes": c["supersedes"],
                }
                for c in contributions
            ],
            "budget": self.store.budget_view(run_id),
            "inputs": [
                {"id": i["id"], "seq": i["seq"], "kind": i["kind"],
                 "status": i["status"], "barrier": bool(i["barrier"]),
                 "text": i["text"][:400], "receivedAt": i["received_at"]}
                for i in self.store.list_inputs(run_id)
            ],
            "currentExplanation": self.store.current_explanation(run_id),
            "handoff": self.store.latest_handoff(run_id),
            "explanations": len([e for e in self.store.list_evidence(run_id) if "explanation" in e.get("outcome", "")]),
            "delegations": [
                {"id": d["id"], "objective": d["objective"],
                 "permittedOperations": d["permitted_operations"],
                 "currentPermittedOperations": [
                     op for op in d["permitted_operations"]
                     if not (op == "edit" and collab.get("edit_denied"))
                 ],
                 "exclusions": d["exclusions"], "claimScope": d["claim_scope"],
                 "returnKind": d["return_kind"],
                 "returnPredicate": d["return_predicate"],
                 "returnTargetRefs": d["return_target_refs"],
                 "requiredEvidenceKinds": d["required_evidence_kinds"],
                 "budgetCeiling": d["budget_ceiling"], "deadline": d["deadline"],
                 "grantRef": d["grant_ref"], "goalGeneration": d["goal_generation"],
                 "status": d["status"],
                 "expired": bool(d.get("deadline") and _deadline_passed(d["deadline"],
                                                                       self.store.clock))}
                for d in self.store.list_delegations(run_id)
            ],
            "delivery": {"supported": False, "reason": "V0-V3 ends at a reviewable stage; V5 owns delivery"},
            "restoreMutations": {"supported": False, "reason": "V3 exposes current-session resume only"},
            "wakeOutbox": self.store.wake_view(run_id),
        }

    def _decision_card(self, interaction: dict) -> dict:
        evidence_blocks = []
        for ref in interaction.get("evidence_refs") or []:
            try:
                body = self.store.get_blob(ref)
            except Exception:  # noqa: BLE001
                continue
            text = body.decode("utf-8", "replace")
            evidence_blocks.append({"id": ref, "text": text[:6000],
                                    "truncated": len(text) > 6000})
        return {
            "id": interaction["id"],
            "kind": interaction["kind"],
            "revision": interaction["revision"],
            "goalGeneration": interaction["goal_generation"],
            "proposalHash": interaction["proposal_hash"],
            "prompt": interaction["prompt_ref"],
            "why": interaction["why"],
            "options": interaction["options"],
            "recommendation": interaction["recommendation"],
            "evidenceRefs": interaction["evidence_refs"],
            "evidenceBlocks": evidence_blocks,
            "blocking": bool(interaction["blocking"]),
            "expectedResponseSchema": interaction["expected_response_schema"],
            "dependentOperations": interaction["dependent_operations"],
        }
