"""Service facade used by the HTTP layer and tests.

Creates one application store and controller owner per run, wires the model
adapter/worker seams, and exposes only ledger/API operations.  No caller can
submit a raw graph command or a forged wake.
"""
from __future__ import annotations

import json
import pathlib
import threading
import time

from problem_titles import validate_title

from .budget import ModelGateway
from .clock import Clock, Failpoints
from .decisions import (
    DecisionService,
    ModelDecisionAdapter,
    ScriptedDecisionAdapter,
    UnavailableDecisionAdapter,
)
from .demo import demo_script
from .graph import Runtime, _operation_expired
from .input_service import InputService
from .model import FakeModelAdapter, SingleRequestOpenAIAdapter, UnavailableModelAdapter
from .owner import OwnerRegistry
from .projection import ProjectionManager
from .prompts import bundle_hash, validate_bundle
from .schemas import sha256_text
from .stage import refusal_payload
from .store import ApplicationStore, LedgerError
from .worker import FakeWorker, IsolateWorker, available_worker


SAMPLE_PROVIDER = "studio-sample"


class EngineService:
    def __init__(
        self,
        base_root: pathlib.Path | str,
        *,
        clock: Clock | None = None,
        model_adapter=None,
        worker=None,
        fixture_dir: str | None = None,
        managed_checkout: bool = True,
        clone_models: bool = True,
        demo: bool = False,
        decision_adapter=None,
        default_budget_limits: dict | None = None,
        provider_models: dict | None = None,
    ):
        self.base_root = pathlib.Path(base_root)
        self.base_root.mkdir(parents=True, exist_ok=True)
        self.clock = clock or Clock()
        self.failpoints = Failpoints()
        self._stores: dict[str, ApplicationStore] = {}
        self._runtimes: dict[str, Runtime] = {}
        self._models: dict[str, object] = {}
        self._workers: dict[str, object] = {}
        self._owners = OwnerRegistry()
        self._locks: dict[str, threading.Lock] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._guard = threading.Lock()
        self.model_factory = model_adapter
        self.base_worker = worker
        self.fixture_dir = fixture_dir
        self.managed_checkout = managed_checkout
        self.clone_models = clone_models
        self.demo = demo
        self.decision_adapter = decision_adapter
        self.default_budget_limits = default_budget_limits
        self.provider_models = provider_models or {}
        self._decisions: dict[str, DecisionService] = {}
        self.prompt_bundle = validate_bundle()
        self.skill_manifest = bundle_hash()
        self._closing = False

    # ------------------------------------------------------------------ runs
    def _run_root(self, run_id: str) -> pathlib.Path:
        return self.base_root / "runs" / run_id

    def create_run(self, *, workspace_id: str, idea: str, seed: dict | None = None,
                   profile: str = "batch-exact-integer-v1",
                   client_request_id: str | None = None,
                   budget_limits: dict | None = None, model_provider: str = "custom",
                   title: str | None = None, reserved_run_id: str | None = None) -> dict:
        if not isinstance(model_provider, str) or (
            model_provider not in ("custom", SAMPLE_PROVIDER) and model_provider not in self.provider_models
        ):
            raise ValueError("The selected authoring provider is unavailable.")
        if title is not None:
            title = validate_title(title)
        run_id = reserved_run_id or ("run-" + sha256_text({"workspace": workspace_id, "idea": idea,
                                                          "t": self.clock.now_iso()})[:12])
        store = ApplicationStore(self._run_root(run_id), self.clock)
        inputs = InputService(store, self.clock)
        result = inputs.create_run(workspace_id=workspace_id, idea=idea, seed=seed,
                                   profile=profile, run_id=run_id,
                                   client_request_id=client_request_id,
                                   budget_limits=budget_limits or self.default_budget_limits,
                                   model_provider=model_provider, title=title)
        runtime = self._make_runtime(run_id, store, inputs)
        self._runtimes[run_id] = runtime
        self._stores[run_id] = store
        return {"runId": run_id, "run": result["run"], "input": result["input"],
                "view": inputs.view(run_id)}

    def rename_run(self, run_id: str, title: str) -> dict:
        title = validate_title(title)
        self.store(run_id).rename_problem(run_id, title)
        return {"runId": run_id, "title": title}

    def _make_runtime(self, run_id: str, store: ApplicationStore,
                      inputs: InputService) -> Runtime:
        model = self._model_for(run_id, store)
        worker = self._worker_for(run_id, store)
        gateway = ModelGateway(store, model, self.clock)
        projection = None
        if self.managed_checkout:
            projection = ProjectionManager(store.root / "checkout", store, managed=True)
        return Runtime(store=store, inputs=inputs, gateway=gateway, worker=worker,
                       clock=self.clock, projection=projection,
                       failpoints=self.failpoints, fixture_dir=self.fixture_dir,
                       model_name=getattr(model, "name", "model"))

    def _default_model(self):
        """Explicitly labelled demo model, or a visible unconfigured adapter."""
        if self.demo:
            from .demo import demo_chat_model
            return demo_chat_model()
        return UnavailableModelAdapter()

    def _model_for(self, run_id: str, store: ApplicationStore | None = None):
        if run_id not in self._models:
            provider = (store or self._stores[run_id]).get_run(run_id)["model_provider"]
            if provider == SAMPLE_PROVIDER:
                from .demo import demo_chat_model
                self._models[run_id] = demo_chat_model()
            elif provider != "custom":
                self._models[run_id] = self.provider_models.get(provider) or UnavailableModelAdapter()
            elif self.model_factory is not None:
                factory = self.model_factory
                if self.clone_models and isinstance(factory, FakeModelAdapter):
                    self._models[run_id] = factory.clone()
                else:
                    self._models[run_id] = factory
            else:
                self._models[run_id] = self._default_model()
        return self._models[run_id]

    def _worker_for(self, run_id: str, store=None):
        if run_id not in self._workers:
            provider = (store or self._stores[run_id]).get_run(run_id)["model_provider"]
            self._workers[run_id] = FakeWorker() if provider == SAMPLE_PROVIDER else (self.base_worker or FakeWorker())
        return self._workers[run_id]

    def _get(self, run_id: str) -> tuple[ApplicationStore, Runtime]:
        if run_id not in self._stores:
            root = self._run_root(run_id)
            if not (root / "app.db").is_file():
                raise LedgerError(f"Unknown run {run_id}")
            store = ApplicationStore(root, self.clock)
            inputs = InputService(store, self.clock)
            self._runtimes[run_id] = self._make_runtime(run_id, store, inputs)
            self._stores[run_id] = store
        return self._stores[run_id], self._runtimes[run_id]

    def store(self, run_id: str) -> ApplicationStore:
        return self._get(run_id)[0]

    def runtime(self, run_id: str) -> Runtime:
        return self._get(run_id)[1]

    def decisions(self, run_id: str) -> DecisionService:
        if run_id not in self._decisions:
            provider = self.store(run_id).get_run(run_id)["model_provider"]
            model = self._model_for(run_id)
            if self.decision_adapter is not None and provider == "custom":
                adapter = self.decision_adapter
                identity = getattr(adapter, "identity", None)
                version = getattr(adapter, "version", None)
            elif getattr(model, "configured", False) and not isinstance(model, ModelDecisionAdapter):
                adapter = ModelDecisionAdapter(model)
                identity = adapter.identity
                version = adapter.version
            elif getattr(model, "demo", False) or self.demo:
                adapter = ScriptedDecisionAdapter()
                identity = adapter.identity
                version = adapter.version
            else:
                adapter = UnavailableDecisionAdapter()
                identity = adapter.identity
                version = adapter.version
            self._decisions[run_id] = DecisionService(
                self.store(run_id), adapter,
                model_identity=identity, model_version=version,
                demo=getattr(adapter, "identity", "") == "scripted-decision-demo",
            )
        return self._decisions[run_id]

    def decision_capabilities(self) -> dict:
        adapter = self.decision_adapter
        if adapter is None:
            return {"configured": False, "role": "decision", "identity": "model-or-demo",
                    "demo": self.demo}
        return {"configured": True, "role": "decision",
                "identity": getattr(adapter, "identity", "configured-decision"),
                "version": getattr(adapter, "version", "0"),
                "demo": getattr(adapter, "identity", "") == "scripted-decision-demo"}

    def list_runs(self) -> list[dict]:
        root = self.base_root / "runs"
        out = []
        if not root.is_dir():
            return out
        for entry in sorted(root.iterdir(), key=lambda p: p.name):
            if not (entry / "app.db").is_file():
                continue
            try:
                store = ApplicationStore(entry, self.clock)
                run = store.get_run(entry.name)
                out.append({"runId": entry.name, "workspaceId": run["workspace_id"],
                            "status": run["status"], "idea": run["goal_text"][:300], "title": run["title"],
                            "sample": run["model_provider"] == SAMPLE_PROVIDER,
                            "updatedAt": run["updated_at"],
                            "revision": run["observed_revision"],
                            "generation": run["goal_generation"]})
            except Exception:  # noqa: BLE001
                continue
        return out

    # ------------------------------------------------------------------ control
    def _lock_for(self, run_id: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(run_id, threading.Lock())

    def pump_sync(self, run_id: str, *, max_steps: int | None = None) -> dict:
        with self._lock_for(run_id):
            with self._guard:
                if self._closing:
                    return {"status": "closed", "runId": run_id}
                _, runtime = self._get(run_id)
                owner = self._owners.owner(runtime, run_id)
            return owner.pump(run_id, max_steps=max_steps)

    def request_pump(self, run_id: str) -> dict:
        with self._guard:
            if self._closing:
                return {"scheduled": False, "runId": run_id, "detail": "service is closing"}
            thread = self._threads.get(run_id)
            if thread is not None and thread.is_alive():
                return {"scheduled": True, "alreadyRunning": True, "runId": run_id}
            thread = threading.Thread(target=self._background_pump, args=(run_id,),
                                      name=f"engine-owner-{run_id}", daemon=True)
            self._threads[run_id] = thread
            thread.start()
            return {"scheduled": True, "alreadyRunning": False, "runId": run_id}

    def _background_pump(self, run_id: str) -> None:
        try:
            self.pump_sync(run_id)
        finally:
            with self._guard:
                if self._threads.get(run_id) is threading.current_thread():
                    self._threads.pop(run_id, None)

    def wait_until_settled(self, run_id: str, *, timeout: float = 20.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._guard:
                thread = self._threads.get(run_id)
            if thread is not None and thread.is_alive():
                thread.join(timeout=0.2)
                continue
            store, _ = self._get(run_id)
            run = store.get_run(run_id)
            if run["status"] in ("waiting_human", "waiting_worker", "stage_returned",
                                 "awaiting_author", "incomplete", "blocked", "cancelled"):
                return {"status": run["status"], "run": store.projection(run_id)}
            time.sleep(0.05)
        return {"status": "timeout", "runId": run_id}

    # ------------------------------------------------------------------ ingress
    def submit_input(self, run_id: str, body: dict, *, actor: str = "local-author",
                     schedule: bool = True) -> dict:
        _, runtime = self._get(run_id)
        receipt = runtime.inputs.submit_input(run_id, body, actor=actor)
        self.failpoints.hit("after_input_commit")
        if schedule:
            self.request_pump(run_id)
        return receipt

    def submit_response(self, run_id: str, interaction_id: str, body: dict,
                        *, actor: str = "local-author", schedule: bool = True) -> dict:
        _, runtime = self._get(run_id)
        receipt = runtime.inputs.submit_response(run_id, interaction_id, body, actor=actor)
        if receipt.get("status") == "receipt" and schedule:
            self.request_pump(run_id)
        return receipt

    def create_contribution(self, run_id: str, body: dict):
        _, runtime = self._get(run_id)
        return runtime.inputs.add_contribution_from_input(run_id, body)

    # ------------------------------------------------------------------ worker
    def settle_worker(self, job_id: str, *, timeout: float = 20.0, schedule: bool = True) -> dict:
        for run_id, runtime in list(self._runtimes.items()):
            store = runtime.store
            operation = store.op_by_job(job_id)
            if operation is None:
                continue
            worker = runtime.worker
            settle = getattr(worker, "settle", None)
            if settle is None:
                return {"error": "this worker does not support deferred settlement"}
            campaign_wall = (operation.get("raw_receipt") or {}).get("campaignWallMs")
            if campaign_wall is not None and operation.get("result"):
                return {"error": "campaign already has a terminal receipt"}
            if campaign_wall is not None and _operation_expired(runtime, operation):
                if schedule:
                    self.request_pump(run_id)
                return {"error": "campaign execution deadline exceeded"}
            raw = settle(job_id)
            if campaign_wall is not None:
                raw["campaignWallMs"] = campaign_wall
            store.stage_worker_receipt(operation["operation_id"], raw=raw, job_id=job_id,
                                       status="admitted")
            store.enqueue_wake(run_id, wait_id="operation:" + operation["operation_id"],
                               reason="worker_receipt", durable_record_ref=operation["operation_id"])
            self.failpoints.hit("after_receipt_commit")
            if schedule:
                self.request_pump(run_id)
            return {"settled": True, "runId": run_id,
                    "operationId": operation["operation_id"]}
        return {"error": f"unknown job {job_id}"}

    def worker_available(self, run_id: str) -> bool:
        worker = self._worker_for(run_id)
        return bool(getattr(worker, "is_real", False)) and bool(
            getattr(worker, "describe", lambda: {})().get("configured", False)
        )

    # ------------------------------------------------------------------ views
    def view(self, run_id: str) -> dict:
        _, runtime = self._get(run_id)
        view = runtime.inputs.view(run_id)
        view["capabilities"] = self.capabilities(run_id)
        view["events"] = runtime.store.events_after(run_id, 0, 200)
        return view

    def campaign_receipt(self, run_id: str, evidence_id: str) -> dict:
        store = self.store(run_id)
        evidence = store.get_evidence(evidence_id)
        if evidence["run_id"] != run_id or evidence["domain"] != "weighted_campaign":
            raise LedgerError("Campaign receipt not found in this run")
        report = json.loads(store.get_blob(evidence["artifact_refs"][0]))
        manifest = json.loads(store.get_blob(report["manifest"]))
        return {"evidenceId": evidence_id, "freshness": evidence["freshness"],
                "workerIdentity": evidence["environment_ref"], "report": report, "manifest": manifest}

    def events(self, run_id: str, after: int = 0) -> dict:
        store, _ = self._get(run_id)
        events = store.events_after(run_id, after)
        return {"runId": run_id, "events": events,
                "nextSeq": (events[-1]["seq"] + 1) if events else max(0, after + 1),
                "gap": bool(events and events[0]["seq"] > after + 1 and after > 0)}

    def capabilities(self, run_id: str | None = None) -> dict:
        provider = self.store(run_id).get_run(run_id)["model_provider"] if run_id else "custom"
        if run_id:
            model = self._model_for(run_id)
        elif self.model_factory is not None:
            model = self.model_factory
        else:
            model = self._default_model()
        worker = self._worker_for(run_id) if run_id else (self.base_worker or IsolateWorker())
        described_model = model.describe_capabilities() if hasattr(model, "describe_capabilities") else {}
        described_worker = worker.describe() if hasattr(worker, "describe") else {}
        return {
            "provider": provider,
            "providers": [
                {"id": name, "model": item.describe_capabilities().get("model")}
                for name, item in self.provider_models.items()
            ],
            "profile": "batch-exact-integer-v1",
            "schemaVersion": 1,
            "promptBundleHash": self.prompt_bundle["hash"],
            "skillManifestHash": self.skill_manifest,
            "model": described_model,
            "modelIsFake": bool(getattr(model, "demo", False)) if model else True,
            "modelConfigured": bool(getattr(model, "configured", False)),
            "demoMode": bool(getattr(model, "demo", False)),
            "decisionModel": ({
                "identity": self.decisions(run_id).model_identity,
                "demo": self.decisions(run_id).demo,
                "configured": self.decisions(run_id).model_identity not in (
                    "scripted-decision-demo", "unconfigured-decision-model"),
                "schemaVersion": 1,
                "promptVersion": "chat-decision-v1",
            } if run_id else {"identity": "model-or-demo", "demo": self.demo,
                              "configured": bool(self.decision_adapter)}),
            "worker": described_worker,
            "workerReal": bool(described_worker.get("real")),
            "workerConfigured": bool(described_worker.get("configured")),
            "workerQualified": bool(described_worker.get("qualified")),
            "workerQualification": described_worker.get("qualification"),
            "weightedCampaign": {"modes": ["seeded", "exhaustive"], "maxSelectedCases": 50,
                                 "requiresEndpointDecision": True},
            "delivery": {"supported": False, "profile": "v0-v3"},
            "restoreMutations": {"supported": False, "profile": "v0-v3"},
            "deferred": ["general reducers", "mutation campaigns", "AgentDriver",
                          "formal proof", "public hosting", "large real-provider evaluation"],
            "disclosure": (
                "Deterministic demo uses a scripted fake model and a simulated worker. "
                "This validates workflow mechanics, not model judgment, C++ execution or containment."
            ),
        }

    # ------------------------------------------------------------------ refusal
    def refuse(self, run_id: str, kind: str) -> dict:
        # No ledger write, no graph invocation, no effect: deliberate no-op.
        return refusal_payload(kind)

    def validate_binding(self, run_id: str, approval_id: str, *, expected_revision: str,
                         expected_goal_generation: int, expected_steering_epoch: int,
                         expected_manifest_hash: str) -> dict:
        store, _ = self._get(run_id)
        return store.check_approval_binding(
            approval_id, expected_revision=expected_revision,
            expected_goal_generation=expected_goal_generation,
            expected_steering_epoch=expected_steering_epoch,
            expected_manifest_hash=expected_manifest_hash,
        )

    def close(self) -> None:
        with self._guard:
            self._closing = True
            threads = list(self._threads.values())
        for thread in threads:
            thread.join(timeout=15)
        for runtime in list(self._runtimes.values()):
            try:
                runtime.gateway.adapter.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                self._owners.close(runtime)
            except Exception:  # noqa: BLE001
                pass
