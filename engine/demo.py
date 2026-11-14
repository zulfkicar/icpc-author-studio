"""Deterministic demonstration script (FAKE model / FAKE worker).

Every run using this script is labelled fake in the UI/API capabilities.  It
orders a collaboration flow; it does not establish autonomous judgment or
real-model quality.
"""
from __future__ import annotations

import hashlib
import re

from .model import FakeModelAdapter

FRAME_QUESTION = {
    "kind": "ok",
    "data": {
        "ready": False,
        "objective": "Maximise total reward over compatible half-open booking intervals.",
        "requirements": [
            {"id": "S1", "text": "labelled jobs"},
            {"id": "S2", "text": "endpoint semantics unresolved"},
            {"id": "S3", "text": "each job at most once"},
            {"id": "S4", "text": "maximise total reward"},
            {"id": "S5", "text": "output the maximum value including the empty set"},
        ],
        "open_questions": [{
            "requirement_id": "endpoint_semantics",
            "question": "May [0,1) and [1,2) both run, i.e. is the room free exactly at the finish time?",
            "why": "It changes feasible subsets, the predecessor comparison and every dependent receipt.",
            "options": [
                {"id": "half_open", "label": "Half-open: touching jobs are compatible",
                 "consequence": "predecessor test uses finish <= start"},
                {"id": "closed", "label": "Closed: touching jobs conflict",
                 "consequence": "predecessor test uses finish < start"},
            ],
            "recommendation": None,
        }],
        "spec_diff": [{"field": "endpoint_semantics", "state": "open"}],
    },
}

DEMO_SCRIPT = [
    FRAME_QUESTION,
    {
        "kind": "ok",
        "data": {
            "action": "investigate",
            "intent": "Fairly test the author's earliest-finish claim with a weighted discriminator.",
            "target_claim_ids": ["H1"],
            "expected_observation": "a weighted case where earliest finish is not optimal",
            "args": {
                "candidate_ref": "fixture:earliest_finish_greedy",
                "claim_id": "H1",
                "claim_text": "earliest finish maximises total reward",
                "domain": {"kind": "witness", "name": "weighted_greedy"},
                "failure_diagnostic": "count-preserving exchange loses weight",
            },
            "requested_budget": {"cases": 1},
            "on_failure": "advisory",
        },
    },
    {
        "kind": "ok",
        "data": {
            "action": "collaborate",
            "intent": "Explain the refutation at the author's requested depth.",
            "target_claim_ids": ["H1"],
            "expected_observation": "current explanation artifact",
            "args": {"procedure": "COL-EXPLAIN", "question":
                     "Why does earliest finish fail for weighted intervals?",
                     "depth": "brief"},
            "requested_budget": {},
            "on_failure": "advisory",
        },
    },
    {
        "kind": "ok",
        "data": {
            "action": "finish",
            "intent": "The current conversational turn is answered; the author decides the next step.",
            "requested_budget": {},
        },
    },
]

COMPOSE_DRAFT = {
    "kind": "ok",
    "data": {
        "short_answer": ("Earliest finish preserves the number of jobs, not the reward: the exchange rule "
                         "loses the weight of a long interval that covers several short ones."),
        "worked_example": "",
        "alternatives": ["sort by finish and use the compatible-prefix DP"],
        "uncertainty": ["the DP optimality argument is a proof obligation, not established by one witness"],
        "next_author_actions": ["inspect the receipt", "request a repair review only if desired"],
        "assumption_to_code_links": [],
    },
}

INTERPRET_DRAFT = {
    "kind": "ok",
    "data": {
        "summary": "Earliest finish is refuted on a legal weighted input.",
        "cause": "The greedy exchange argument preserves cardinality only.",
        "first_violated_invariant": "finish <= start compatibility is not the issue here; weight is ignored.",
        "uncertainty": ["other greedy rules are not refuted by this witness"],
        "next_author_actions": ["compare a DP formulation", "review the endpoint comparison separately"],
        "proposed_next_action": "collaborate",
    },
}


def demo_script() -> dict:
    finish = DEMO_SCRIPT[-1]
    return {
        "frame_goal": [FRAME_QUESTION] * 4,
        "plan": list(DEMO_SCRIPT[1:]) + [finish] * 8,
        "collaboration.compose": [COMPOSE_DRAFT] * 4,
        "investigation.interpret": [INTERPRET_DRAFT] * 4,
        "investigation.design": [],
        "editing.draft": [],
        "review.challenge": [],
    }


def _first_line(text: str) -> str:
    for line in str(text or "").splitlines():
        if line.strip():
            return line.strip()[:200]
    return ""


class ConversationDemoModel:
    """Demo chat model: request-aware collaborate plans and bounded drafts.

    This is a scripted demo, not a real model.  It exercises the graph routes
    (COL-EXPLAIN / COL-PROOF / COL-TEST) with distinct, request-tied text so the
    product path, prompts and context plumbing can be tested offline.
    """

    name = "conversation-demo-v1"
    version = "1.0"
    configured = False
    demo = True

    def __init__(self):
        self._default_base = FakeModelAdapter(script=demo_script())
        self._script = self._default_base._script
        self._bases: dict[str, FakeModelAdapter] = {}
        self._handled: set[str] = set()
        self.calls: list[dict] = []

    def _base_for(self, context: dict) -> FakeModelAdapter:
        run_id = str((context or {}).get("runId") or "default")
        if run_id not in self._bases:
            self._bases[run_id] = (self._default_base if not self._bases
                                   else FakeModelAdapter(script=demo_script()))
        return self._bases[run_id]

    def describe_capabilities(self) -> dict:
        return {
            "model": self.name, "tools": False, "structured_output": True,
            "streaming": False, "usage": False, "cancellation": True,
            "demo": True, "configured": False,
            "contextWindow": 32768, "contextWindowSource": "Sample reference scale",
        }

    def clone(self):
        return ConversationDemoModel()

    def close(self):
        return None

    @staticmethod
    def _last_author(context: dict) -> dict | None:
        messages = ((context or {}).get("conversation") or {}).get("messages") or []
        for message in reversed(messages):
            if message.get("role") == "author":
                return message
        return None

    @staticmethod
    def _procedure_for(text: str) -> str | None:
        lowered = text.lower()
        if re.search(r"\b(?:generate|create|suggest|design|give\s+me|add|broaden)\b", lowered) \
                and re.search(r"\b(?:tests?|edge\s+cases?|cases?)\b", lowered):
            return "COL-TEST"
        if re.search(r"\b(?:check|critique|review|verify)\b", lowered) \
                and re.search(r"\b(?:proof|argument|step|exchange)\b", lowered):
            return "COL-PROOF"
        if re.search(r"\b(?:help\s+me|build|construct|develop|write|prove)\b", lowered) \
                and re.search(r"\b(?:proof|argument|correctness)\b", lowered):
            return "COL-PROOF"
        if re.search(r"\b(?:explain|why|clarify)\b", lowered) \
                and re.search(r"\b(?:proof|argument|step|claim)\b", lowered):
            return "COL-EXPLAIN"
        if re.search(r"\bcompare\b", lowered) and "approach" in lowered:
            return "COL-COMPARE"
        return None

    def call(self, request: dict, *, timeout_seconds: float = 90.0) -> dict:
        self.calls.append({"node": request.get("node"), "context": request.get("context")})
        node = str(request.get("node") or "")
        context = request.get("context") or {}
        base = self._base_for(context)
        if node == "plan":
            author = self._last_author(context)
            text = str((author or {}).get("text") or "")
            procedure = self._procedure_for(text)
            queue = base._script.get("plan") or []
            injected_edit = any(str((item.get("data") or {}).get("action")) == "edit"
                                for item in queue)
            if injected_edit:
                return base.call(request, timeout_seconds=timeout_seconds)
            if author and procedure:
                key = f"{context.get('runId')}:{author.get('seq')}:{procedure}"
                if key not in self._handled:
                    self._handled.add(key)
                    return {"kind": "ok", "data": {
                        "action": "collaborate",
                        "intent": f"Answer the author's {procedure} request with bounded work.",
                        "target_claim_ids": [],
                        "expected_observation": "a new bounded explanation artifact",
                        "args": {"procedure": procedure,
                                 "question": author.get("text"),
                                 "depth": "standard"},
                        "requested_budget": {},
                        "on_failure": "advisory",
                    }}
                return {"kind": "ok", "data": {
                    "action": "finish",
                    "intent": "The requested bounded work has returned a draft.",
                    "requested_budget": {},
                }}
            effect = re.search(r"\bapply\b[^.!?]{0,60}\b(?:fix|patch|proposal)\b",
                               text, re.I)
            unsafe = bool(re.search(r"\b(?:not|don't|do\s+not|never|avoid|maybe|perhaps|"
                                    r"if|whether|would|should)\b", text, re.I)) or "?" in text
            if author and effect and not unsafe:
                key = f"{context.get('runId')}:{author.get('seq')}:apply"
                if key not in self._handled:
                    self._handled.add(key)
                    current = [a for a in ((context.get("authorArtifacts") or {}).get("artifacts")
                                           or []) if a.get("current")]
                    solution = next((a for a in reversed(current)
                                     if a.get("kind") == "solution"), None)
                    if solution:
                        body = str(solution.get("text") or "")
                        return {"kind": "ok", "data": {
                            "action": "edit",
                            "intent": "Apply a bounded demo repair to the current solution.",
                            "target_claim_ids": [],
                            "expected_observation": "a reviewed patch revision",
                            "args": {"path": solution.get("path"),
                                     "after": body.rstrip("\n") + "\n// demo repair applied\n"},
                            "requested_budget": {},
                            "on_failure": "advisory",
                        }}
                return {"kind": "ok", "data": {
                    "action": "finish",
                    "intent": "The demo repair has been proposed.",
                    "requested_budget": {},
                }}
        if node == "collaboration.compose":
            question = str(context.get("question") or "")
            procedure = str(context.get("procedure") or "COL-EXPLAIN")
            digest = hashlib.sha256(question.encode("utf-8")).hexdigest()[:8].upper()
            return {"kind": "ok", "data": self._draft(procedure, question, digest, context)}
        return base.call(request, timeout_seconds=timeout_seconds)

    @staticmethod
    def _draft(procedure: str, question: str, digest: str, context: dict) -> dict:
        artifacts = ((context.get("authorArtifacts") or {}).get("artifacts") or [])
        current = [a for a in artifacts if a.get("current")]
        proof = next((a for a in current if a.get("kind") == "proof"), None)
        semantics = "unresolved"
        for decision in reversed((context.get("decisions") or [])):
            if decision.get("requirementId") == "endpoint_semantics":
                semantics = str(decision.get("optionId"))
                break
        if procedure == "COL-TEST":
            answer = (
                f"TEST_DESIGN {digest}: for `{question[:160]}` under {semantics} endpoints, "
                "planned coverage is the touching boundary, nested intervals, duplicate labels, "
                "and 64-bit reward totals. The independent subset oracle supplies expected values; "
                "no generated code was executed and these are planned/simulated cases."
            )
            next_actions = ["confirm the expected total for the touching boundary",
                            "run the finite oracle campaign when execution is available"]
        elif procedure == "COL-PROOF":
            claim = _first_line((proof or {}).get("text", ""))
            answer = (
                f"PROOF_WORK {digest}: for `{question[:160]}`, the current proof material "
                f"is {'`' + claim + '`' if claim else 'not yet supplied'}. The exchange step "
                f"must be re-derived under {semantics} endpoints; the claim is not established "
                "by the scripted draft. Open obligation: prove the compatible-prefix recurrence."
            )
            next_actions = ["supply the precise exchange inequality",
                            "mark which steps are assumptions versus proved"]
        elif procedure == "COL-COMPARE":
            answer = (
                f"APPROACH_COMPARE {digest}: the greedy earliest-finish rule maximizes count, "
                "while the compatible-prefix DP maximizes reward. The DP is the current candidate; "
                f"the comparison is evaluated under {semantics} endpoints."
            )
            next_actions = ["inspect the refutation receipt", "keep the DP as the candidate"]
        else:
            claim = _first_line((proof or {}).get("text", ""))
            answer = (
                f"PROOF_EXPLAIN {digest}: answering `{question[:160]}`. The current material says "
                f"{'`' + claim + '`' if claim else 'no proof artifact is current'}. Under {semantics} "
                "endpoints the recurrence compares skipping a job with taking it plus the best "
                "compatible prefix. This is a bounded scripted explanation, not a proof."
            )
            next_actions = ["check the proof obligation", "ask for critique of a specific step"]
        return {"short_answer": answer, "worked_example": "",
                "alternatives": ["compatible-prefix DP"],
                "uncertainty": ["scripted demo draft; not real-model reasoning or proof"],
                "next_author_actions": next_actions,
                "assumption_to_code_links": []}


def demo_chat_model() -> ConversationDemoModel:
    return ConversationDemoModel()
