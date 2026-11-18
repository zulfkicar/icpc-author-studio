"""Application ledger: revisions, blobs, inputs, interactions, receipts, wakes.

Two SQLite databases live per run root (03 Â§4): ``app.db`` (this module) and
``checkpoints.db`` (LangGraph).  The application journal is authoritative for
external effects; graph state carries IDs and compact summaries only.

Openers use ``BEGIN IMMEDIATE`` so a read-modify-write sequence is serialized
against the owner thread and HTTP handler threads.  This is a local
single-author ledger, not a distributed queue.
"""
from __future__ import annotations

import contextlib
import json
import pathlib
import sqlite3
from typing import Any, Iterator

from author_studio.packages.problem_titles import statement_title

from .clock import Clock
from .schemas import (
    SCHEMA_VERSION,
    ApprovalV1,
    AuthorInputV1,
    ContributionV1,
    DelegationV1,
    EvidenceV1,
    ExplanationV1,
    FindingV1,
    GrantV1,
    HandoffV1,
    HumanInteractionV1,
    HumanResponseV1,
    OperationResultV1,
    RevisionV1,
    WakeV1,
    canonical_json,
    sha256_bytes,
    sha256_text,
    validate_response_payload,
)

TERMINAL_INPUT = ("applied", "conflict", "superseded", "cancelled")


class LedgerError(RuntimeError):
    pass


class IdempotencyConflict(LedgerError):
    """Same (run_id, client_request_id) key with a different body."""


class StaleBinding(LedgerError):
    def __init__(self, message: str, current: dict | None = None):
        super().__init__(message)
        self.current = current or {}


class UnsupportedProfile(LedgerError):
    pass


class PublicationBlocked(LedgerError):
    def __init__(self, message: str, *, kind: str = "publication_blocked"):
        super().__init__(message)
        self.kind = kind


class ApplicationStore:
    def __init__(self, root: pathlib.Path | str, clock: Clock | None = None):
        self.root = pathlib.Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "app.db"
        self.checkpoint_path = self.root / "checkpoints.db"
        self.clock = clock or Clock()
        self._schema()
        version = self.schema_version()
        if version > SCHEMA_VERSION:
            raise LedgerError(
                f"Database schema {version} is newer than this engine ({SCHEMA_VERSION}); "
                "refusing to open. Preserve the database and use the newer build."
            )

    # ---------------------------------------------------------------- plumbing
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=15000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    @contextlib.contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except Exception:
            with contextlib.suppress(Exception):
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def read_one(self, sql: str, params: tuple = ()) -> dict | None:
        conn = self._connect()
        try:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def read_all(self, sql: str, params: tuple = ()) -> list[dict]:
        conn = self._connect()
        try:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    def _schema(self) -> None:
        script = """
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS blobs (
          hash TEXT PRIMARY KEY, kind TEXT NOT NULL, size INTEGER NOT NULL,
          body BLOB NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS runs (
          run_id TEXT PRIMARY KEY,
          workspace_id TEXT NOT NULL,
          thread_id TEXT NOT NULL,
          schema_version INTEGER NOT NULL,
          goal_id TEXT,
          goal_text TEXT NOT NULL DEFAULT '',
          title TEXT,
          goal_generation INTEGER NOT NULL DEFAULT 0,
          capability_id TEXT NOT NULL,
          scope_profile_id TEXT NOT NULL,
          observed_revision TEXT,
          spec_hash TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'idle',
          stop_reason TEXT,
          applied_author_seq INTEGER NOT NULL DEFAULT 0,
          steering_epoch INTEGER NOT NULL DEFAULT 0,
          controller_epoch INTEGER NOT NULL DEFAULT 0,
          budget_id TEXT NOT NULL,
          continuation_json TEXT,
          stage_contract_json TEXT,
          collaboration_json TEXT,
          pending_interaction_id TEXT,
          active_operation_id TEXT,
          handoff_ref TEXT,
          next_input_seq INTEGER NOT NULL DEFAULT 1,
          next_response_seq INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS revisions (
          id TEXT PRIMARY KEY, parent_id TEXT, files_json TEXT NOT NULL,
          spec_hash TEXT NOT NULL DEFAULT '', profile_hash TEXT NOT NULL DEFAULT '',
          prompt_bundle_hash TEXT NOT NULL DEFAULT '',
          skill_manifest_hash TEXT NOT NULL DEFAULT '',
          compiler_identity TEXT, worker_image_identity TEXT,
          created_by TEXT NOT NULL, created_at TEXT NOT NULL,
          run_id TEXT
        );
        CREATE TABLE IF NOT EXISTS inputs (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL, seq INTEGER NOT NULL,
          kind TEXT NOT NULL, text TEXT NOT NULL DEFAULT '',
          payload_json TEXT, expected_generation INTEGER,
          referenced_json TEXT NOT NULL DEFAULT '[]',
          status TEXT NOT NULL DEFAULT 'received',
          client_request_id TEXT NOT NULL, original_hash TEXT NOT NULL,
          resolves_input_id TEXT, supersedes_input_id TEXT,
          interpretation_ref TEXT, received_at TEXT NOT NULL, applied_at TEXT,
          generation_at_receipt INTEGER NOT NULL DEFAULT 0,
          barrier INTEGER NOT NULL DEFAULT 0,
          UNIQUE(run_id, seq)
        );
        CREATE TABLE IF NOT EXISTS idempotency (
          run_id TEXT NOT NULL, client_request_id TEXT NOT NULL, scope TEXT NOT NULL,
          body_hash TEXT NOT NULL, receipt_ref TEXT NOT NULL, receipt_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          PRIMARY KEY (run_id, client_request_id)
        );
        CREATE TABLE IF NOT EXISTS interactions (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL, kind TEXT NOT NULL,
          revision TEXT NOT NULL, goal_generation INTEGER NOT NULL,
          proposal_hash TEXT NOT NULL, affected_json TEXT NOT NULL DEFAULT '[]',
          prompt_ref TEXT NOT NULL DEFAULT '', why TEXT NOT NULL DEFAULT '',
          option_ids_json TEXT NOT NULL DEFAULT '[]', options_json TEXT NOT NULL DEFAULT '[]',
          recommendation TEXT, evidence_json TEXT NOT NULL DEFAULT '[]',
          expected_response_schema TEXT NOT NULL DEFAULT 'TaggedHumanResponseV1',
          dependent_json TEXT NOT NULL DEFAULT '[]', blocking INTEGER NOT NULL DEFAULT 1,
          status TEXT NOT NULL DEFAULT 'pending', response_ids_json TEXT NOT NULL DEFAULT '[]',
          resolution_response_id TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS responses (
          id TEXT PRIMARY KEY, interaction_id TEXT NOT NULL, run_id TEXT NOT NULL,
          actor_id TEXT NOT NULL, client_request_id TEXT NOT NULL,
          expected_revision TEXT, expected_goal_generation INTEGER, expected_proposal_hash TEXT,
          kind TEXT NOT NULL, payload_json TEXT NOT NULL,
          received_seq INTEGER NOT NULL, received_at TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'receipt', applied INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS contributions (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL, actor_kind TEXT NOT NULL,
          actor_id TEXT NOT NULL, source_input_id TEXT,
          kind TEXT NOT NULL, original_blob_hash TEXT NOT NULL,
          derived_json TEXT NOT NULL DEFAULT '[]', revision TEXT NOT NULL,
          claim_ids_json TEXT NOT NULL DEFAULT '[]', validation_status TEXT NOT NULL DEFAULT 'unvalidated',
          attribution TEXT NOT NULL DEFAULT '', supersedes TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS grants (
          id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, source_input_id TEXT NOT NULL,
          run_id TEXT NOT NULL, goal_generation INTEGER NOT NULL,
          operation_kinds_json TEXT NOT NULL DEFAULT '[]',
          scope_json TEXT NOT NULL DEFAULT '[]', budget_id TEXT NOT NULL DEFAULT '',
          expires_at TEXT, revoked_at TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS delegations (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL, goal_generation INTEGER NOT NULL,
          objective TEXT NOT NULL, permitted_json TEXT NOT NULL DEFAULT '[]',
          exclusions_json TEXT NOT NULL DEFAULT '[]', claim_scope_json TEXT NOT NULL DEFAULT '[]',
          budget_ceiling_json TEXT NOT NULL DEFAULT '{}', deadline TEXT,
          return_predicate_json TEXT NOT NULL, grant_ref TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'active', return_kind TEXT NOT NULL DEFAULT 'campaign_complete',
          return_target_json TEXT NOT NULL DEFAULT '[]',
          required_evidence_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS operations (
          operation_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, kind TEXT NOT NULL,
          request_hash TEXT NOT NULL, input_revision TEXT NOT NULL,
          goal_generation INTEGER NOT NULL, steering_epoch INTEGER NOT NULL,
          controller_epoch INTEGER NOT NULL, reservation_id TEXT NOT NULL,
          status TEXT NOT NULL, classification TEXT NOT NULL DEFAULT 'pending',
          result_json TEXT, attempts_json TEXT NOT NULL DEFAULT '[]',
          raw_json TEXT, job_id TEXT, dispatched_at TEXT,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS budgets (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
          model_attempts_limit INTEGER NOT NULL, model_attempts_used INTEGER NOT NULL DEFAULT 0,
          cases_limit INTEGER NOT NULL, cases_used INTEGER NOT NULL DEFAULT 0,
          wall_ms_limit INTEGER NOT NULL, wall_ms_used INTEGER NOT NULL DEFAULT 0,
          active_seconds_limit REAL NOT NULL, active_seconds_used REAL NOT NULL DEFAULT 0,
          expires_at TEXT, settled_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS reservations (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL, budget_id TEXT NOT NULL,
          action_id TEXT NOT NULL, attempts_limit INTEGER NOT NULL,
          cases INTEGER NOT NULL DEFAULT 0, wall_ms INTEGER NOT NULL DEFAULT 0,
          state TEXT NOT NULL DEFAULT 'reserved', created_at TEXT NOT NULL,
          settled_at TEXT, UNIQUE(run_id, action_id)
        );
        CREATE TABLE IF NOT EXISTS attempts (
          id TEXT PRIMARY KEY, reservation_id TEXT NOT NULL, attempt_index INTEGER NOT NULL,
          kind TEXT NOT NULL, outcome TEXT NOT NULL, usage_json TEXT NOT NULL DEFAULT '{}',
          reservation_owner TEXT, started_at TEXT NOT NULL, ended_at TEXT NOT NULL,
          UNIQUE(reservation_id, attempt_index)
        );
        CREATE TABLE IF NOT EXISTS evidence (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL, producer_kind TEXT NOT NULL,
          producer_version TEXT NOT NULL, operation_id TEXT NOT NULL,
          input_refs_json TEXT NOT NULL DEFAULT '[]', dependency_hashes_json TEXT NOT NULL DEFAULT '{}',
          domain TEXT, seed INTEGER, enumeration_order TEXT,
          budget_json TEXT NOT NULL DEFAULT '{}', usage_json TEXT NOT NULL DEFAULT '{}',
          outcome TEXT NOT NULL, artifact_refs_json TEXT NOT NULL DEFAULT '[]',
          environment_ref TEXT, visibility TEXT NOT NULL DEFAULT 'author',
          freshness TEXT NOT NULL DEFAULT 'current', classification TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS findings (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL, claim_id TEXT, revision TEXT NOT NULL,
          origin_role TEXT NOT NULL, origin_model TEXT, severity TEXT NOT NULL,
          allegation TEXT NOT NULL, evidence_json TEXT NOT NULL DEFAULT '[]',
          suggested_discriminator TEXT, status TEXT NOT NULL DEFAULT 'open',
          disposition_reason TEXT, resolution_evidence_json TEXT NOT NULL DEFAULT '[]',
          resolver_kind TEXT, supersedes TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS explanations (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL, revision TEXT NOT NULL,
          claim_refs_json TEXT NOT NULL DEFAULT '[]', audience_depth TEXT NOT NULL,
          question TEXT NOT NULL DEFAULT '', short_answer TEXT NOT NULL DEFAULT '',
          worked_example_ref TEXT, links_json TEXT NOT NULL DEFAULT '[]',
          evidence_json TEXT NOT NULL DEFAULT '[]', alternatives_json TEXT NOT NULL DEFAULT '[]',
          uncertainty_json TEXT NOT NULL DEFAULT '[]', next_actions_json TEXT NOT NULL DEFAULT '[]',
          current INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS handoffs (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL, goal_generation INTEGER NOT NULL,
          revision TEXT NOT NULL, applied_seq INTEGER NOT NULL, outcome TEXT NOT NULL,
          decisions_json TEXT NOT NULL DEFAULT '[]', contributions_json TEXT NOT NULL DEFAULT '[]',
          completed_json TEXT NOT NULL DEFAULT '[]', open_questions_json TEXT NOT NULL DEFAULT '[]',
          evidence_json TEXT NOT NULL DEFAULT '[]', invalidations_json TEXT NOT NULL DEFAULT '[]',
          budget_json TEXT NOT NULL DEFAULT '{}', next_actions_json TEXT NOT NULL DEFAULT '[]',
          stage_return_json TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
          run_id TEXT NOT NULL, seq INTEGER NOT NULL, type TEXT NOT NULL, role TEXT NOT NULL,
          timestamp TEXT NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}',
          payload_ref TEXT, revision TEXT, goal_generation INTEGER,
          PRIMARY KEY (run_id, seq)
        );
        CREATE TABLE IF NOT EXISTS package_checks (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL, action_id TEXT NOT NULL,
          source_hash TEXT NOT NULL, case_count INTEGER NOT NULL, receipt_json TEXT
        );
        CREATE TABLE IF NOT EXISTS wake_outbox (
          wake_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, wait_id TEXT NOT NULL,
          reason TEXT NOT NULL, durable_record_ref TEXT NOT NULL, created_at TEXT NOT NULL,
          delivered_at TEXT, delivered_epoch INTEGER, consumed_at TEXT, consumed_epoch INTEGER
        );
        CREATE TABLE IF NOT EXISTS consumptions (
          wake_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, wait_id TEXT NOT NULL,
          consumed_at TEXT NOT NULL, consumed_epoch INTEGER NOT NULL, checkpoint_ref TEXT
        );
        CREATE TABLE IF NOT EXISTS approvals (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL, human_actor TEXT NOT NULL, revision TEXT NOT NULL,
          action_kind TEXT NOT NULL, effect_manifest_hash TEXT NOT NULL,
          evidence_root_hash TEXT NOT NULL DEFAULT '', goal_generation INTEGER NOT NULL,
          steering_epoch INTEGER NOT NULL, profile_hash TEXT NOT NULL DEFAULT '',
          decision TEXT NOT NULL, created_at TEXT NOT NULL, invalidated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS controller_log (
          id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, epoch INTEGER NOT NULL,
          event TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chat_messages (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL, seq INTEGER NOT NULL,
          role TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL,
          input_id TEXT, interaction_id TEXT, response_id TEXT,
          artifact_ids_json TEXT NOT NULL DEFAULT '[]',
          dedupe_key TEXT, created_at TEXT NOT NULL,
          UNIQUE(run_id, dedupe_key)
        );
        CREATE TABLE IF NOT EXISTS artifacts (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL, kind TEXT NOT NULL,
          path TEXT NOT NULL, blob_hash TEXT NOT NULL, revision TEXT,
          source_turn TEXT, provenance_json TEXT NOT NULL DEFAULT '{}',
          current INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
          generation INTEGER NOT NULL DEFAULT 0,
          validity TEXT NOT NULL DEFAULT 'current',
          validity_reason TEXT NOT NULL DEFAULT '',
          depends_json TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS decision_records (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL, message_id TEXT NOT NULL,
          input_id TEXT, text_hash TEXT NOT NULL,
          schema_version INTEGER NOT NULL, prompt_version TEXT NOT NULL,
          model_identity TEXT NOT NULL, model_version TEXT NOT NULL,
          context_revision TEXT, context_generation INTEGER NOT NULL DEFAULT 0,
          interpretation_json TEXT NOT NULL,
          disposition_json TEXT NOT NULL DEFAULT '{}',
          status TEXT NOT NULL, created_at TEXT NOT NULL,
          reservation_id TEXT, attempt_id TEXT, attempts INTEGER NOT NULL DEFAULT 0,
          usage_json TEXT NOT NULL DEFAULT '{}', latency_ms REAL,
          UNIQUE(run_id, message_id)
        );
        CREATE TABLE IF NOT EXISTS projection_intents (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL, revision TEXT NOT NULL,
          state TEXT NOT NULL, manifest_json TEXT NOT NULL,
          base_hashes_json TEXT NOT NULL, conflicts_json TEXT NOT NULL DEFAULT '[]',
          patch_blob TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS publications (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL, revision TEXT NOT NULL,
          proposal_hash TEXT NOT NULL, path TEXT NOT NULL, created_at TEXT NOT NULL,
          UNIQUE(run_id, proposal_hash)
        );
        CREATE INDEX IF NOT EXISTS idx_inputs_run ON inputs(run_id, seq);
        CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, seq);
        CREATE INDEX IF NOT EXISTS idx_operations_run ON operations(run_id);
        CREATE INDEX IF NOT EXISTS idx_wake_run ON wake_outbox(run_id, consumed_at);
        """
        conn = self._connect()
        try:
            conn.executescript(script)
            self._ensure_column(conn, "runs", "next_chat_seq", "INTEGER NOT NULL DEFAULT 1")
            self._ensure_column(conn, "runs", "model_provider", "TEXT NOT NULL DEFAULT 'custom'")
            self._ensure_column(conn, "runs", "title", "TEXT")
            self._ensure_column(conn, "inputs", "decision_ref", "TEXT")
            self._ensure_column(conn, "attempts", "context_json", "TEXT")
            for column, definition in (
                ("generation", "INTEGER NOT NULL DEFAULT 0"),
                ("validity", "TEXT NOT NULL DEFAULT 'current'"),
                ("validity_reason", "TEXT NOT NULL DEFAULT ''"),
                ("depends_json", "TEXT NOT NULL DEFAULT '[]'"),
            ):
                self._ensure_column(conn, "artifacts", column, definition)
            for column, definition in (
                ("reservation_id", "TEXT"),
                ("attempt_id", "TEXT"),
                ("attempts", "INTEGER NOT NULL DEFAULT 0"),
                ("usage_json", "TEXT NOT NULL DEFAULT '{}'"),
                ("latency_ms", "REAL"),
            ):
                self._ensure_column(conn, "decision_records", column, definition)
            conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
        finally:
            conn.close()

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    def schema_version(self) -> int:
        row = self.read_one("SELECT value FROM meta WHERE key='schema_version'")
        return int(row["value"]) if row else SCHEMA_VERSION

    # ---------------------------------------------------------------- blobs
    def put_blob(self, body: bytes, kind: str = "text") -> str:
        with self.tx() as conn:
            return self._put_blob(conn, body, kind, self.clock.now_iso())

    @staticmethod
    def _put_blob(conn, body: bytes, kind: str, now: str) -> str:
        digest = sha256_bytes(body)
        conn.execute("INSERT OR IGNORE INTO blobs(hash, kind, size, body, created_at) VALUES (?,?,?,?,?)",
                     (digest, kind, len(body), body, now))
        return digest

    def get_blob(self, digest: str) -> bytes:
        row = self.read_one("SELECT body FROM blobs WHERE hash=?", (digest,))
        if row is None:
            raise LedgerError(f"Unknown blob {digest}")
        return bytes(row["body"])

    def blob_meta(self, digest: str) -> dict:
        row = self.read_one("SELECT hash, kind, size, created_at FROM blobs WHERE hash=?", (digest,))
        if row is None:
            raise LedgerError(f"Unknown blob {digest}")
        return row

    # ---------------------------------------------------------------- runs
    def create_run(
        self,
        workspace_id: str,
        goal_text: str,
        *,
        capability_id: str = "batch-exact-integer-v1",
        scope_profile_id: str = "weighted-interval-v1",
        budget_limits: dict | None = None,
        run_id: str | None = None,
        model_provider: str = "custom",
        title: str | None = None,
    ) -> dict:
        run_id = run_id or ("run-" + sha256_text(
            {"workspace": workspace_id, "goal": goal_text, "at": self.clock.now_iso(),
             "n": self._count_runs(), "nonce": __import__("uuid").uuid4().hex}
        )[:12])
        thread_id = "thread-" + run_id
        budget_id = "budget-" + run_id
        limits = {
            "model_attempts_limit": 30,
            "cases_limit": 10000,
            "wall_ms_limit": 60000,
            "active_seconds_limit": 1200,
        }
        limits.update(budget_limits or {})
        now = self.clock.now_iso()
        rev = RevisionV1(
            id="rev-0",
            files=[],
            spec_hash=sha256_text({"goal": goal_text}),
            profile_hash=sha256_text({"profile": scope_profile_id}),
            prompt_bundle_hash=sha256_text({"prompt": "c2-base-v1"}),
            skill_manifest_hash=sha256_text({"skills": "c2-col-v1"}),
            created_by="engine",
            created_at=now,
        )
        with self.tx() as conn:
            conn.execute(
                """INSERT INTO runs(run_id, workspace_id, thread_id, schema_version, goal_id, goal_text,
                   goal_generation, capability_id, scope_profile_id, observed_revision, spec_hash,
                   status, applied_author_seq, steering_epoch, controller_epoch, budget_id,
                   created_at, updated_at, model_provider, title)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id, workspace_id, thread_id, SCHEMA_VERSION, "goal-" + run_id, goal_text,
                    0, capability_id, scope_profile_id, rev.id, rev.spec_hash, "idle",
                    0, 0, 0, budget_id, now, now, model_provider, title,
                ),
            )
            conn.execute(
                """INSERT INTO budgets(id, run_id, model_attempts_limit, cases_limit, wall_ms_limit,
                   active_seconds_limit, settled_json)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    budget_id, run_id, limits["model_attempts_limit"], limits["cases_limit"],
                    limits["wall_ms_limit"], limits["active_seconds_limit"], "{}",
                ),
            )
            conn.execute(
                """INSERT INTO revisions(id, parent_id, files_json, spec_hash, profile_hash,
                   prompt_bundle_hash, skill_manifest_hash, created_by, created_at, run_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (rev.id, None, "[]", rev.spec_hash, rev.profile_hash, rev.prompt_bundle_hash,
                 rev.skill_manifest_hash, rev.created_by, rev.created_at, run_id),
            )
        return self.get_run(run_id)

    def _count_runs(self) -> int:
        row = self.read_one("SELECT COUNT(*) AS n FROM runs")
        return int(row["n"]) if row else 0

    def get_run(self, run_id: str) -> dict:
        row = self.read_one("SELECT * FROM runs WHERE run_id=?", (run_id,))
        if row is None:
            raise LedgerError(f"Unknown run {run_id}")
        return row

    def run_exists(self, run_id: str) -> bool:
        return self.read_one("SELECT 1 AS x FROM runs WHERE run_id=?", (run_id,)) is not None

    def update_run(self, run_id: str, **fields: Any) -> dict:
        allowed = {
            "goal_text", "goal_generation", "observed_revision", "spec_hash", "status",
            "stop_reason", "applied_author_seq", "steering_epoch", "controller_epoch",
            "continuation_json", "stage_contract_json", "collaboration_json",
            "pending_interaction_id", "active_operation_id", "handoff_ref", "next_input_seq",
            "next_response_seq", "goal_id", "title",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise LedgerError(f"Unsupported run fields: {sorted(unknown)}")
        now = self.clock.now_iso()
        fields["updated_at"] = now
        sets = ", ".join(f"{key}=?" for key in fields)
        with self.tx() as conn:
            conn.execute(f"UPDATE runs SET {sets} WHERE run_id=?", (*fields.values(), run_id))
        return self.get_run(run_id)

    def rename_problem(self, run_id: str, title: str) -> None:
        now = self.clock.now_iso()
        with self.tx() as conn:
            conn.execute("UPDATE runs SET title=?, updated_at=? WHERE run_id=?", (title, now, run_id))
            item = conn.execute(
                """SELECT artifacts.*, blobs.body FROM artifacts JOIN blobs ON blobs.hash=blob_hash
                   WHERE run_id=? AND current=1 AND artifacts.kind='statement' AND path='problem_statement/problem.en.tex'
                   AND json_extract(provenance_json,'$.packageDraft')=1""", (run_id,),
            ).fetchone()
            if item is None:
                return
            old = bytes(item["body"])
            new = statement_title(old.decode("utf-8"), title).encode("utf-8")
            if new == old:
                return
            digest = self._put_blob(conn, new, "artifact:statement", now)
            depends = json.loads(item["depends_json"])
            depends = [edge for edge in depends if "previousStatement" not in edge]
            conn.execute("UPDATE artifacts SET validity='stale', validity_reason='Problem title changed' WHERE id=?",
                         (item["id"],))
            statement_id = self._write_artifact(
                conn, run_id, item["kind"], item["path"], digest, item["revision"], item["source_turn"],
                json.loads(item["provenance_json"]), item["generation"], "current", "",
                [*depends, {"previousStatement": item["id"]}], now,
            )
            self._insert_chat_message(conn, run_id, now, role="agent", kind="artifact",
                                      text="Updated the statement to use the new problem title.",
                                      artifact_ids=[statement_id])

    def projection(self, run_id: str) -> dict:
        """Versioned RunState projection rebuilt from canonical records."""
        run = self.get_run(run_id)
        return {
            "schema_version": run["schema_version"],
            "run_id": run["run_id"],
            "workspace_id": run["workspace_id"],
            "thread_id": run["thread_id"],
            "goal_id": run["goal_id"],
            "goal_generation": run["goal_generation"],
            "observed_revision": run["observed_revision"],
            "capability_id": run["capability_id"],
            "scope_profile_id": run["scope_profile_id"],
            "status": run["status"],
            "stop_reason": run["stop_reason"],
            "applied_author_seq": run["applied_author_seq"],
            "steering_epoch": run["steering_epoch"],
            "controller_epoch": run["controller_epoch"],
            "budget_id": run["budget_id"],
            "continuation": json.loads(run["continuation_json"]) if run["continuation_json"] else None,
            "stage_contract": json.loads(run["stage_contract_json"]) if run["stage_contract_json"] else None,
            "collaboration": json.loads(run["collaboration_json"]) if run["collaboration_json"] else {},
            "pending_interaction_id": run["pending_interaction_id"],
            "active_operation_id": run["active_operation_id"],
            "handoff_ref": run["handoff_ref"],
        }

    # ---------------------------------------------------------------- events
    def append_event(
        self,
        run_id: str,
        kind: str,
        *,
        role: str = "host",
        payload: dict | None = None,
        payload_ref: str | None = None,
        revision: str | None = None,
        goal_generation: int | None = None,
    ) -> int:
        now = self.clock.now_iso()
        with self.tx() as conn:
            seq = int(conn.execute(
                "SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE run_id=?", (run_id,)
            ).fetchone()[0])
            conn.execute(
                """INSERT INTO events(run_id, seq, type, role, timestamp, payload_json, payload_ref,
                   revision, goal_generation) VALUES (?,?,?,?,?,?,?,?,?)""",
                (run_id, seq, kind, role, now, canonical_json(payload or {}), payload_ref, revision,
                 goal_generation),
            )
        return seq

    def events_after(self, run_id: str, after: int = 0, limit: int = 500) -> list[dict]:
        rows = self.read_all(
            "SELECT * FROM events WHERE run_id=? AND seq>? ORDER BY seq LIMIT ?",
            (run_id, int(after), int(limit)),
        )
        for row in rows:
            row["payload"] = json.loads(row.pop("payload_json") or "{}")
        return rows

    # ---------------------------------------------------------------- chat transcript
    def append_chat_message(self, run_id: str, *, role: str, kind: str, text: str,
                            input_id: str | None = None, interaction_id: str | None = None,
                            response_id: str | None = None,
                            artifact_ids: list[str] | None = None,
                            dedupe_key: str | None = None) -> dict:
        now = self.clock.now_iso()
        with self.tx() as conn:
            if dedupe_key:
                existing = conn.execute(
                    "SELECT * FROM chat_messages WHERE run_id=? AND dedupe_key=?",
                    (run_id, dedupe_key),
                ).fetchone()
                if existing is not None:
                    return self._chat_row(dict(existing))
            message_id = self._insert_chat_message(
                conn, run_id, now, role=role, kind=kind, text=text, input_id=input_id,
                interaction_id=interaction_id, response_id=response_id, artifact_ids=artifact_ids,
                dedupe_key=dedupe_key,
            )
        return self.get_chat_message(message_id)

    @staticmethod
    def _insert_chat_message(conn, run_id, now, *, role, kind, text, input_id=None,
                             interaction_id=None, response_id=None, artifact_ids=None, dedupe_key=None):
        run = conn.execute("SELECT next_chat_seq FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if run is None:
            raise LedgerError(f"Unknown run {run_id}")
        seq = int(run["next_chat_seq"] or 1)
        message_id = "msg-" + sha256_text(
            {"run": run_id, "seq": seq, "role": role, "kind": kind, "dedupe": dedupe_key}
        )[:14]
        conn.execute("UPDATE runs SET next_chat_seq=?, updated_at=? WHERE run_id=?", (seq + 1, now, run_id))
        conn.execute(
            """INSERT INTO chat_messages(id, run_id, seq, role, kind, text, input_id,
               interaction_id, response_id, artifact_ids_json, dedupe_key, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (message_id, run_id, seq, role, kind, text[:100_000], input_id, interaction_id,
             response_id, canonical_json(artifact_ids or []), dedupe_key, now),
        )
        return message_id

    def append_chat_turn(self, run_id: str, *, role: str, text: str,
                         payload: dict, client_request_id: str,
                         dedupe_key: str | None = None) -> dict:
        """Atomically append an author turn, input receipt, barrier and link.

        The transcript row, stable input identity, barrier flag, wake row and
        idempotency record commit in one transaction.  A committed transcript
        row can therefore never be visible without the publication barrier.
        """
        from .policy import classify_input_barrier

        if not client_request_id or not str(client_request_id).strip():
            raise ValueError("clientRequestId is required")
        body = {"kind": "chat_turn", "text": text, "payload": payload}
        body_hash = sha256_text(body)
        now = self.clock.now_iso()
        with self.tx() as conn:
            if dedupe_key:
                existing = conn.execute(
                    "SELECT * FROM chat_messages WHERE run_id=? AND dedupe_key=?",
                    (run_id, dedupe_key),
                ).fetchone()
                if existing is not None:
                    message = self._chat_row(dict(existing))
                    input_row = (self.get_input(message["input_id"])
                                 if message.get("input_id") else None)
                    return {"message": message, "input": input_row}
            existing_receipt = self._idempotency_lookup(
                conn, run_id, client_request_id, "input", body_hash)
            if existing_receipt is not None:
                message = conn.execute(
                    "SELECT * FROM chat_messages WHERE run_id=? AND input_id=?",
                    (run_id, existing_receipt["inputId"]),
                ).fetchone()
                return {"message": self._chat_row(dict(message)) if message else None,
                        "input": self.get_input(existing_receipt["inputId"])}
            run = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise LedgerError(f"Unknown run {run_id}")
            chat_seq = int(run["next_chat_seq"] or 1)
            input_seq = int(run["next_input_seq"])
            message_id = "msg-" + sha256_text(
                {"run": run_id, "seq": chat_seq, "role": role, "kind": "message",
                 "dedupe": dedupe_key})[:14]
            input_id = "input-" + sha256_text(
                {"run": run_id, "seq": input_seq, "key": client_request_id})[:12]
            barrier = classify_input_barrier("chat_turn", payload)
            steering_epoch = int(run["steering_epoch"]) + (1 if barrier else 0)
            conn.execute(
                "UPDATE runs SET next_chat_seq=?, next_input_seq=?, steering_epoch=?, "
                "updated_at=? WHERE run_id=?",
                (chat_seq + 1, input_seq + 1, steering_epoch, now, run_id))
            conn.execute(
                """INSERT INTO chat_messages(id, run_id, seq, role, kind, text, input_id,
                   interaction_id, response_id, artifact_ids_json, dedupe_key, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (message_id, run_id, chat_seq, role, "message", text[:100_000],
                 input_id, None, None, "[]", dedupe_key, now),
            )
            conn.execute(
                """INSERT INTO inputs(id, run_id, seq, kind, text, payload_json,
                   expected_generation, referenced_json, status, client_request_id,
                   original_hash, resolves_input_id, supersedes_input_id, received_at,
                   generation_at_receipt, barrier)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (input_id, run_id, input_seq, "chat_turn", text[:100_000],
                 canonical_json(payload), int(run["goal_generation"]), "[]", "received",
                 client_request_id, body_hash, None, None, now,
                 int(run["goal_generation"]), 1 if barrier else 0),
            )
            wake_id = "wake-" + sha256_text(
                {"run": run_id, "ref": input_id, "kind": "chat_turn"})[:16]
            conn.execute(
                """INSERT INTO wake_outbox(wake_id, run_id, wait_id, reason,
                   durable_record_ref, created_at) VALUES (?,?,?,?,?,?)""",
                (wake_id, run_id, run["pending_interaction_id"] or "boundary",
                 "chat_turn", input_id, now),
            )
            receipt = {
                "inputId": input_id, "runId": run_id, "seq": input_seq,
                "status": "received", "barrier": barrier,
                "steeringEpoch": steering_epoch,
                "statusUrl": f"/api/engine/runs/{run_id}/inputs/{input_id}",
                "wakeId": wake_id,
            }
            conn.execute(
                """INSERT INTO idempotency(run_id, client_request_id, scope, body_hash,
                   receipt_ref, receipt_json, created_at) VALUES (?,?,?,?,?,?,?)""",
                (run_id, client_request_id, "input", body_hash, input_id,
                 canonical_json(receipt), now),
            )
        self.append_event(run_id, "chat_turn_received", role="author",
                          payload={"messageId": message_id, **receipt})
        return {"message": self.get_chat_message(message_id),
                "input": self.get_input(input_id)}

    @staticmethod
    def _chat_row(row: dict) -> dict:
        row["artifact_ids"] = json.loads(row.pop("artifact_ids_json") or "[]")
        return row

    def get_chat_message(self, message_id: str) -> dict:
        row = self.read_one("SELECT * FROM chat_messages WHERE id=?", (message_id,))
        if row is None:
            raise LedgerError(f"Unknown chat message {message_id}")
        return self._chat_row(row)

    def list_chat_messages(self, run_id: str, after: int = 0, limit: int = 500) -> list[dict]:
        rows = self.read_all(
            "SELECT * FROM chat_messages WHERE run_id=? AND seq>? ORDER BY seq LIMIT ?",
            (run_id, int(after), int(limit)),
        )
        return [self._chat_row(row) for row in rows]

    def recent_chat_messages(self, run_id: str, *, limit: int, before: int | None = None, after: int = 0) -> list[dict]:
        rows = self.read_all(
            "SELECT * FROM chat_messages WHERE run_id=? AND seq>? AND seq<? ORDER BY seq DESC LIMIT ?",
            (run_id, after, before if before is not None else 2**63 - 1, limit),
        )
        return [self._chat_row(row) for row in reversed(rows)]

    def update_chat_links(self, message_id: str, *, input_id: str | None = None,
                          interaction_id: str | None = None,
                          response_id: str | None = None,
                          artifact_ids: list[str] | None = None) -> dict:
        fields = {}
        if input_id is not None:
            fields["input_id"] = input_id
        if interaction_id is not None:
            fields["interaction_id"] = interaction_id
        if response_id is not None:
            fields["response_id"] = response_id
        if artifact_ids is not None:
            fields["artifact_ids_json"] = canonical_json(artifact_ids)
        if fields:
            sets = ", ".join(f"{key}=?" for key in fields)
            with self.tx() as conn:
                conn.execute(f"UPDATE chat_messages SET {sets} WHERE id=?",
                             (*fields.values(), message_id))
        return self.get_chat_message(message_id)

    # ---------------------------------------------------------------- internal artifacts
    def create_artifact(self, run_id: str, *, kind: str, path: str, body: bytes,
                        revision: str | None = None, source_turn: str | None = None,
                        provenance: dict | None = None, generation: int | None = None,
                        validity: str = "current", validity_reason: str = "",
                        depends: list[dict] | None = None) -> dict:
        """Project one artifact with explicit validity.

        Identity covers the content, generation and dependency set.  Bytes that
        recur under a changed dependency therefore form a different record and
        cannot silently reactivate a stale projection.
        """
        digest = self.put_blob(body, kind=f"artifact:{kind}")
        now = self.clock.now_iso()
        run = self.get_run(run_id)
        generation = int(run["goal_generation"] if generation is None else generation)
        depends = list(depends or [])
        with self.tx() as conn:
            artifact_id = self._write_artifact(conn, run_id, kind, path, digest, revision,
                                               source_turn, provenance or {}, generation,
                                               validity, validity_reason, depends, now,
                                               refresh_existing=True)
        return self.get_artifact(artifact_id)

    @staticmethod
    def _write_artifact(conn, run_id, kind, path, digest, revision, source_turn,
                        provenance, generation, validity, validity_reason, depends, now,
                        *, refresh_existing=False):
        artifact_id = "art-" + sha256_text({
            "run": run_id, "kind": kind, "path": path, "hash": digest,
            "generation": generation, "depends": depends,
        })[:14]
        existing = conn.execute("SELECT * FROM artifacts WHERE id=?", (artifact_id,)).fetchone()
        if existing is not None:
            if refresh_existing and (validity == "revalidated" or
                                     (validity == "current" and existing["validity"] in ("current", "revalidated"))):
                conn.execute("UPDATE artifacts SET current=1, validity=? WHERE id=?", (validity, artifact_id))
            return artifact_id
        conn.execute(
            "UPDATE artifacts SET current=0 WHERE run_id=? AND kind=? AND path=? AND current=1",
            (run_id, kind, path),
        )
        conn.execute(
            """INSERT INTO artifacts(id, run_id, kind, path, blob_hash, revision,
               source_turn, provenance_json, current, created_at, generation,
               validity, validity_reason, depends_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (artifact_id, run_id, kind, path, digest, revision, source_turn,
             canonical_json(provenance), int(validity in ("current", "revalidated")),
             now, generation, validity, validity_reason, canonical_json(depends)),
        )
        return artifact_id

    @staticmethod
    def _check_package_context(conn, run_id: str, context: dict) -> None:
        run = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if (run["status"] == "cancelled" or run["observed_revision"] != context["revision"]
                or any(run[key] != context[key] for key in
                       ("goal_generation", "steering_epoch", "controller_epoch", "applied_author_seq"))):
            raise PublicationBlocked("The conversation changed while drafting", kind="stale_draft")
        if conn.execute(
            "SELECT 1 FROM inputs WHERE run_id=? AND barrier=1 AND status IN ('received','interpreting')",
            (run_id,),
        ).fetchone():
            raise PublicationBlocked("New author input is pending", kind="input_barrier")

    def start_package_check(self, run_id: str, *, check_id: str, action_id: str,
                            source_hash: str, cases: int, context: dict) -> tuple[bool, dict | None]:
        """Claim one execution and its case budget together. Never replay an ambiguous dispatch."""
        with self.tx() as conn:
            self._check_package_context(conn, run_id, context)
            existing = conn.execute("SELECT receipt_json FROM package_checks WHERE id=?", (check_id,)).fetchone()
            if existing is not None:
                return False, json.loads(existing["receipt_json"] or "null")
            scoped_limit = ((context.get("delegation") or {}).get("budget_ceiling") or {}).get("cases")
            if scoped_limit is not None:
                used = conn.execute(
                    "SELECT COALESCE(SUM(case_count),0) FROM package_checks WHERE run_id=? AND action_id=?",
                    (run_id, action_id),
                ).fetchone()[0]
                if used + cases > int(scoped_limit):
                    raise PublicationBlocked("Delegated case budget exhausted", kind="case_budget_exhausted")
            charge = conn.execute(
                "UPDATE budgets SET cases_used=cases_used+? WHERE run_id=? AND cases_used+?<=cases_limit",
                (cases, run_id, cases),
            )
            if not charge.rowcount:
                raise PublicationBlocked("Run case budget exhausted", kind="case_budget_exhausted")
            conn.execute(
                "INSERT INTO package_checks (id,run_id,action_id,source_hash,case_count) VALUES (?,?,?,?,?)",
                (check_id, run_id, action_id, source_hash, cases),
            )
            return True, None

    def require_package_context(self, run_id: str, context: dict) -> None:
        with self.tx() as conn:
            self._check_package_context(conn, run_id, context)

    def finish_package_check(self, check_id: str, receipt: dict) -> None:
        with self.tx() as conn:
            conn.execute("UPDATE package_checks SET receipt_json=? WHERE id=? AND receipt_json IS NULL",
                         (canonical_json(receipt), check_id))

    def publish_package_draft(self, run_id: str, files: list[dict], *, context: dict,
                              source_turn: str, action_id: str, model: str,
                              endpoint_decision: dict, check: dict | None = None) -> list[str]:
        prepared = [(file, self.put_blob(file["text"].encode("utf-8"), f"artifact:{file['kind']}"))
                    for file in files]
        receipt_blob = self.put_blob(canonical_json(check).encode("utf-8"), "package-oracle-receipt") if check else None
        now = self.clock.now_iso()
        depends = [{"requirementId": "endpoint_semantics", "decisionId": endpoint_decision["id"],
                    "generation": context["goal_generation"]},
                   {"packageDraftAction": action_id}]
        with self.tx() as conn:
            self._check_package_context(conn, run_id, context)
            title = conn.execute("SELECT title FROM runs WHERE run_id=?", (run_id,)).fetchone()["title"]
            if title:
                # Read at commit time so a rename during model or worker execution wins.
                prepared = [(file, self._put_blob(conn, statement_title(file["text"], title).encode("utf-8"),
                                                   "artifact:statement", now) if file["kind"] == "statement" else digest)
                            for file, digest in prepared]
            if check is not None:
                row = conn.execute(
                    "SELECT source_hash, receipt_json FROM package_checks WHERE id=? AND run_id=? AND action_id=?",
                    (check["id"], run_id, action_id),
                ).fetchone()
                source = next(digest for file, digest in prepared if file["kind"] == "solution")
                if not row or row["source_hash"] != source or json.loads(row["receipt_json"] or "null") != check:
                    raise PublicationBlocked("The oracle receipt does not match this draft", kind="invalid_draft_receipt")
                test_hashes = {file["path"]: digest for file, digest in prepared if file["kind"] == "test"}
                if check["status"] != "pass" or check["inputHashes"] != test_hashes:
                    raise PublicationBlocked("The reference has unresolved checks", kind="invalid_draft_receipt")
            latest = conn.execute(
                "SELECT provenance_json FROM artifacts WHERE run_id=? AND current=1 AND path=?",
                (run_id, "submissions/accepted/reference.cpp"),
            ).fetchone()
            if not latest or json.loads(latest["provenance_json"]).get("actionId") != action_id:
                conn.execute(
                    """UPDATE artifacts SET current=0, validity='stale', validity_reason='superseded package draft'
                       WHERE run_id=? AND current=1 AND json_extract(provenance_json,'$.packageDraft')=1""",
                    (run_id,),
                )
                conn.execute("UPDATE evidence SET freshness='stale' WHERE run_id=? AND domain='package_reference'",
                             (run_id,))
            artifact_ids = []
            for file, digest in prepared:
                generated = file["kind"] != "validator"
                provenance = {
                    "packageDraft": True, "actionId": action_id,
                    "authorKind": "model" if generated else "host",
                    "model": model if generated else None,
                    "purpose": file.get("purpose"), "oracleExpected": file.get("oracleExpected"),
                }
                if check is not None:
                    provenance["packageCheck"] = {"id": check["id"], "cases": len(check["cases"]),
                                                   "repairs": check["round"], "worker": check["worker"]}
                artifact_ids.append(self._write_artifact(
                    conn, run_id, file["kind"], file["path"], digest, context["revision"],
                    source_turn, provenance, context["goal_generation"], "current", "", depends, now,
                ))
            if check is not None and receipt_blob is not None:
                reference = next(artifact_id for (file, _), artifact_id in zip(prepared, artifact_ids)
                                 if file["kind"] == "solution")
                evidence = EvidenceV1(
                    id="ev-" + check["id"], producer_kind="deterministic",
                    producer_version="isolated-package-oracle-v1", operation_id=check["id"],
                    input_refs=[receipt_blob], artifact_refs=[receipt_blob],
                    dependency_hashes={"candidate": check["sourceHash"], "semantics": check["semantics"]},
                    domain="package_reference", outcome="campaign", classification="bounded_agreement",
                    usage_observed={"complete": True, "cases": len(check["cases"]), "referenceId": reference,
                                    "referencePath": "submissions/accepted/reference.cpp"},
                    environment_ref=check["worker"],
                )
                self._write_evidence(conn, run_id, evidence, now)
            return artifact_ids

    def get_artifact(self, artifact_id: str) -> dict:
        row = self.read_one("SELECT * FROM artifacts WHERE id=?", (artifact_id,))
        if row is None:
            raise LedgerError(f"Unknown artifact {artifact_id}")
        row["provenance"] = json.loads(row.pop("provenance_json") or "{}")
        row["depends"] = json.loads(row.pop("depends_json") or "[]")
        row["current"] = bool(row["current"])
        return row

    def artifact_body(self, artifact_id: str) -> bytes:
        return self.get_blob(self.get_artifact(artifact_id)["blob_hash"])

    def list_artifacts(self, run_id: str, *, current_only: bool = False) -> list[dict]:
        sql = "SELECT id FROM artifacts WHERE run_id=?"
        if current_only:
            sql += " AND current=1"
        sql += " ORDER BY created_at, rowid"
        return [self.get_artifact(row["id"]) for row in self.read_all(sql, (run_id,))]

    def invalidate_artifacts(self, run_id: str, *, kinds: list[str] | None = None,
                             reason: str = "superseded", generation: int | None = None,
                             depends_requirement: str | None = None,
                             decision_id: str | None = None) -> list[str]:
        """Mark dependent projections stale without deleting their bodies."""
        ids = []
        with self.tx() as conn:
            rows = conn.execute("SELECT * FROM artifacts WHERE run_id=? AND current=1",
                                (run_id,)).fetchall()
            for row in rows:
                if kinds is not None and row["kind"] not in kinds:
                    continue
                depends = json.loads(row["depends_json"] or "[]")
                if depends_requirement is not None and not any(
                        d.get("requirementId") == depends_requirement for d in depends):
                    continue
                if generation is not None and int(row["generation"] or 0) >= int(generation):
                    continue
                conn.execute(
                    "UPDATE artifacts SET current=0, validity='stale', validity_reason=? WHERE id=?",
                    (reason, row["id"]),
                )
                ids.append(row["id"])
        if ids:
            self.append_event(run_id, "artifacts_invalidated", role="host",
                              payload={"artifactIds": ids, "reason": reason,
                                       "decisionId": decision_id,
                                       "dependsRequirement": depends_requirement})
        return ids

    def set_artifact_validity(self, artifact_id: str, validity: str, *,
                              reason: str = "", current: bool | None = None) -> dict:
        if validity not in ("current", "stale", "unresolved", "revalidated"):
            raise LedgerError(f"Unknown artifact validity {validity!r}")
        with self.tx() as conn:
            conn.execute(
                "UPDATE artifacts SET validity=?, validity_reason=?, current=? WHERE id=?",
                (validity, reason, 1 if (current if current is not None
                                         else validity in ("current", "revalidated")) else 0,
                 artifact_id),
            )
        return self.get_artifact(artifact_id)

    # ---------------------------------------------------------------- decisions
    def add_decision_record(self, run_id: str, *, message_id: str, text_hash: str,
                            interpretation: dict, disposition: dict,
                            status: str, schema_version: int, prompt_version: str,
                            model_identity: str, model_version: str,
                            context_revision: str | None,
                            context_generation: int,
                            reservation_id: str | None = None,
                            attempt_id: str | None = None,
                            attempts: int = 0,
                            usage: dict | None = None,
                            latency_ms: float | None = None) -> dict:
        record_id = "dec-" + sha256_text({"run": run_id, "message": message_id})[:14]
        now = self.clock.now_iso()
        with self.tx() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO decision_records(
                   id, run_id, message_id, input_id, text_hash, schema_version,
                   prompt_version, model_identity, model_version, context_revision,
                   context_generation, interpretation_json, disposition_json, status, created_at,
                   reservation_id, attempt_id, attempts, usage_json, latency_ms)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (record_id, run_id, message_id, None, text_hash, int(schema_version),
                 prompt_version, model_identity, model_version, context_revision,
                 int(context_generation), canonical_json(interpretation),
                 canonical_json(disposition), status, now, reservation_id, attempt_id,
                 int(attempts), canonical_json(usage or {"unknown": True}), latency_ms),
            )
        return self.get_decision_record(record_id)

    def get_decision_record(self, record_id: str) -> dict:
        row = self.read_one("SELECT * FROM decision_records WHERE id=?", (record_id,))
        if row is None:
            raise LedgerError(f"Unknown decision record {record_id}")
        row["interpretation"] = json.loads(row.pop("interpretation_json") or "{}")
        row["disposition"] = json.loads(row.pop("disposition_json") or "{}")
        row["usage"] = json.loads(row.pop("usage_json") or "{}")
        return row

    def reservation_for_action(self, run_id: str, action_id: str) -> dict | None:
        row = self.read_one(
            "SELECT * FROM reservations WHERE run_id=? AND action_id=?",
            (run_id, action_id),
        )
        return dict(row) if row else None

    def decision_for_message(self, run_id: str, message_id: str) -> dict | None:
        row = self.read_one(
            "SELECT id FROM decision_records WHERE run_id=? AND message_id=?",
            (run_id, message_id),
        )
        return self.get_decision_record(row["id"]) if row else None

    def list_decision_records(self, run_id: str) -> list[dict]:
        return [self.get_decision_record(row["id"]) for row in self.read_all(
            "SELECT id FROM decision_records WHERE run_id=? ORDER BY created_at, rowid",
            (run_id,))]

    def bind_decision_input(self, record_id: str, input_id: str) -> dict:
        with self.tx() as conn:
            conn.execute("UPDATE decision_records SET input_id=? WHERE id=?",
                         (input_id, record_id))
            conn.execute("UPDATE inputs SET decision_ref=? WHERE id=?", (record_id, input_id))
        return self.get_decision_record(record_id)

    def decision_for_input(self, input_id: str) -> dict | None:
        row = self.read_one("SELECT decision_ref FROM inputs WHERE id=?", (input_id,))
        if row is None or not row["decision_ref"]:
            return None
        try:
            return self.get_decision_record(row["decision_ref"])
        except LedgerError:
            return None

    def update_decision_disposition(self, record_id: str, disposition: dict,
                                    status: str | None = None) -> dict:
        with self.tx() as conn:
            if status is None:
                conn.execute("UPDATE decision_records SET disposition_json=? WHERE id=?",
                             (canonical_json(disposition), record_id))
            else:
                conn.execute(
                    "UPDATE decision_records SET disposition_json=?, status=? WHERE id=?",
                    (canonical_json(disposition), status, record_id),
                )
        return self.get_decision_record(record_id)

    # ---------------------------------------------------------------- inputs
    def _idempotency_lookup(self, conn: sqlite3.Connection, run_id: str, key: str, scope: str, body_hash: str) -> dict | None:
        row = conn.execute(
            "SELECT * FROM idempotency WHERE run_id=? AND client_request_id=?",
            (run_id, key),
        ).fetchone()
        if row is None:
            return None
        row = dict(row)
        if row["scope"] != scope or row["body_hash"] != body_hash:
            raise IdempotencyConflict(
                "client_request_id was already used with a different request body"
            )
        return json.loads(row["receipt_json"])

    def append_input(
        self,
        run_id: str,
        *,
        kind: str,
        text: str = "",
        payload: dict | None = None,
        client_request_id: str,
        expected_generation: int | None = None,
        referenced_artifacts: list[str] | None = None,
        resolves_input_id: str | None = None,
        supersedes_input_id: str | None = None,
    ) -> dict:
        from .policy import classify_input_barrier

        if not client_request_id or not str(client_request_id).strip():
            raise ValueError("clientRequestId is required")
        body = {
            "kind": kind, "text": text, "payload": payload,
            "expectedGeneration": expected_generation,
            "referencedArtifacts": referenced_artifacts or [],
            "resolvesInputId": resolves_input_id, "supersedesInputId": supersedes_input_id,
        }
        body_hash = sha256_text(body)
        scope = "input"
        now = self.clock.now_iso()
        with self.tx() as conn:
            existing = self._idempotency_lookup(conn, run_id, client_request_id, scope, body_hash)
            if existing is not None:
                return existing
            run = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise LedgerError(f"Unknown run {run_id}")
            seq = int(run["next_input_seq"])
            barrier = classify_input_barrier(kind, payload)
            steering_epoch = int(run["steering_epoch"]) + (1 if barrier else 0)
            input_id = "input-" + sha256_text({"run": run_id, "seq": seq, "key": client_request_id})[:12]
            conn.execute("UPDATE runs SET next_input_seq=?, steering_epoch=?, updated_at=? WHERE run_id=?",
                         (seq + 1, steering_epoch, now, run_id))
            conn.execute(
                """INSERT INTO inputs(id, run_id, seq, kind, text, payload_json, expected_generation,
                   referenced_json, status, client_request_id, original_hash, resolves_input_id,
                   supersedes_input_id, received_at, generation_at_receipt, barrier)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (input_id, run_id, seq, kind, text[:100_000],
                 canonical_json(payload) if payload is not None else None,
                 expected_generation, canonical_json(referenced_artifacts or []),
                 "received", client_request_id, sha256_text({"text": text, "payload": payload}),
                 resolves_input_id, supersedes_input_id, now, int(run["goal_generation"]),
                 1 if barrier else 0),
            )
            reason = "cancel" if kind == "cancel" else ("response" if kind == "respond" else "steering")
            wake_id = "wake-" + sha256_text({"run": run_id, "ref": input_id, "kind": reason})[:16]
            conn.execute(
                """INSERT INTO wake_outbox(wake_id, run_id, wait_id, reason, durable_record_ref, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (wake_id, run_id, run["pending_interaction_id"] or "boundary", reason, input_id, now),
            )
            receipt = {
                "inputId": input_id,
                "runId": run_id,
                "seq": seq,
                "status": "received",
                "barrier": barrier,
                "steeringEpoch": steering_epoch,
                "statusUrl": f"/api/engine/runs/{run_id}/inputs/{input_id}",
                "wakeId": wake_id,
            }
            conn.execute(
                """INSERT INTO idempotency(run_id, client_request_id, scope, body_hash, receipt_ref,
                   receipt_json, created_at) VALUES (?,?,?,?,?,?,?)""",
                (run_id, client_request_id, scope, body_hash, input_id, canonical_json(receipt), now),
            )
        self.append_event(run_id, "input_received", role="author", payload=receipt)
        return receipt

    def get_input(self, input_id: str) -> dict:
        row = self.read_one("SELECT * FROM inputs WHERE id=?", (input_id,))
        if row is None:
            raise LedgerError(f"Unknown input {input_id}")
        row["payload"] = json.loads(row.pop("payload_json") or "null")
        row["referenced_artifacts"] = json.loads(row.pop("referenced_json") or "[]")
        return row

    def list_inputs(self, run_id: str) -> list[dict]:
        rows = self.read_all("SELECT * FROM inputs WHERE run_id=? ORDER BY seq", (run_id,))
        for row in rows:
            row["payload"] = json.loads(row.pop("payload_json") or "null")
            row["referenced_artifacts"] = json.loads(row.pop("referenced_json") or "[]")
        return rows

    def received_inputs(self, run_id: str) -> list[dict]:
        return [row for row in self.list_inputs(run_id) if row["status"] == "received"]

    def disposition_input(self, input_id: str, status: str, *, reason: str | None = None,
                          interpretation_ref: str | None = None) -> None:
        if status not in TERMINAL_INPUT + ("needs_disambiguation", "interpreting"):
            raise LedgerError(f"Bad input disposition {status}")
        now = self.clock.now_iso()
        with self.tx() as conn:
            conn.execute(
                "UPDATE inputs SET status=?, interpretation_ref=?, applied_at=? WHERE id=?",
                (status, interpretation_ref, now if status in TERMINAL_INPUT else None, input_id),
            )
            run_id = conn.execute("SELECT run_id FROM inputs WHERE id=?", (input_id,)).fetchone()["run_id"]
            rows = conn.execute(
                "SELECT seq, status FROM inputs WHERE run_id=? ORDER BY seq", (run_id,)
            ).fetchall()
            watermark = 0
            for row in rows:
                if row["seq"] != watermark + 1:
                    break
                if row["status"] in TERMINAL_INPUT:
                    watermark += 1
                else:
                    break
            conn.execute("UPDATE runs SET applied_author_seq=?, updated_at=? WHERE run_id=?",
                         (watermark, now, run_id))
        self.append_event(run_id, "input_disposition", role="host",
                          payload={"inputId": input_id, "status": status, "reason": reason})

    def applied_watermark(self, run_id: str) -> int:
        return int(self.get_run(run_id)["applied_author_seq"])

    # ---------------------------------------------------------------- interactions
    def create_interaction(self, interaction: HumanInteractionV1, *, wait_id: str | None = None) -> dict:
        with self.tx() as conn:
            existing = conn.execute(
                "SELECT * FROM interactions WHERE id=?", (interaction.id,)
            ).fetchone()
            if existing is not None:
                return dict(existing)
            conn.execute(
                """INSERT INTO interactions(id, run_id, kind, revision, goal_generation, proposal_hash,
                   affected_json, prompt_ref, why, option_ids_json, options_json, recommendation,
                   evidence_json, expected_response_schema, dependent_json, blocking, status, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (interaction.id, interaction.run_id, interaction.kind, interaction.revision,
                 interaction.goal_generation, interaction.proposal_hash,
                 canonical_json(interaction.affected_claim_ids), interaction.prompt_ref,
                 interaction.why, canonical_json(interaction.option_ids),
                 canonical_json(interaction.options), interaction.recommendation,
                 canonical_json(interaction.evidence_refs), interaction.expected_response_schema,
                 canonical_json(interaction.dependent_operations), 1 if interaction.blocking else 0,
                 "pending", self.clock.now_iso()),
            )
            conn.execute(
                "UPDATE runs SET pending_interaction_id=?, updated_at=? WHERE run_id=?",
                (interaction.id, self.clock.now_iso(), interaction.run_id),
            )
        self.append_event(interaction.run_id, "interaction_proposed", role="host",
                          payload={"interactionId": interaction.id, "kind": interaction.kind,
                                   "prompt": interaction.prompt_ref, "why": interaction.why})
        return self.get_interaction(interaction.id)

    def get_interaction(self, interaction_id: str) -> dict:
        row = self.read_one("SELECT * FROM interactions WHERE id=?", (interaction_id,))
        if row is None:
            raise LedgerError(f"Unknown interaction {interaction_id}")
        row["affected_claim_ids"] = json.loads(row.pop("affected_json") or "[]")
        row["option_ids"] = json.loads(row.pop("option_ids_json") or "[]")
        row["options"] = json.loads(row.pop("options_json") or "[]")
        row["evidence_refs"] = json.loads(row.pop("evidence_json") or "[]")
        row["dependent_operations"] = json.loads(row.pop("dependent_json") or "[]")
        row["response_ids"] = json.loads(row.pop("response_ids_json") or "[]")
        row["blocking"] = bool(row["blocking"])
        return row

    def pending_interaction(self, run_id: str) -> dict | None:
        row = self.read_one(
            "SELECT * FROM interactions WHERE run_id=? AND status='pending' ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (run_id,),
        )
        if row is None:
            return None
        return self.get_interaction(row["id"])

    def withdraw_pending_interactions(self, run_id: str, status: str = "superseded") -> int:
        if status not in ("superseded", "withdrawn"):
            raise LedgerError(f"Bad interaction disposition {status}")
        with self.tx() as conn:
            rows = conn.execute(
                "SELECT id FROM interactions WHERE run_id=? AND status='pending'", (run_id,)
            ).fetchall()
            for row in rows:
                conn.execute("UPDATE interactions SET status=? WHERE id=?", (status, row["id"]))
            conn.execute("UPDATE runs SET pending_interaction_id=NULL WHERE run_id=?", (run_id,))
        return len(rows)

    def apply_response(self, response_id: str, *, status: str = "receipt", close: bool = True) -> dict:
        """Mark a validated response applied and optionally close the interaction."""
        now = self.clock.now_iso()
        with self.tx() as conn:
            row = conn.execute("SELECT * FROM responses WHERE id=?", (response_id,)).fetchone()
            if row is None:
                raise LedgerError(f"Unknown response {response_id}")
            if row["applied"]:
                return self.get_response(response_id)
            conn.execute("UPDATE responses SET applied=1, status=? WHERE id=?", (status, response_id))
            if close:
                conn.execute(
                    "UPDATE interactions SET status='answered', resolution_response_id=? WHERE id=?",
                    (response_id, row["interaction_id"]),
                )
                conn.execute(
                    "UPDATE runs SET pending_interaction_id=NULL, updated_at=? WHERE run_id=?",
                    (now, row["run_id"]),
                )
        return self.get_response(response_id)

    def get_response(self, response_id: str) -> dict:
        row = self.read_one("SELECT * FROM responses WHERE id=?", (response_id,))
        if row is None:
            raise LedgerError(f"Unknown response {response_id}")
        row["payload"] = json.loads(row.pop("payload_json") or "{}")
        return row

    def responses_for(self, interaction_id: str) -> list[dict]:
        rows = self.read_all("SELECT * FROM responses WHERE interaction_id=? ORDER BY received_seq", (interaction_id,))
        for row in rows:
            row["payload"] = json.loads(row.pop("payload_json") or "{}")
        return rows

    def append_response(
        self,
        run_id: str,
        interaction_id: str,
        *,
        actor_id: str,
        kind: str,
        payload: dict,
        client_request_id: str,
        expected_revision: str | None = None,
        expected_goal_generation: int | None = None,
        expected_proposal_hash: str | None = None,
    ) -> dict:
        if not client_request_id:
            raise ValueError("clientRequestId is required")
        body = {"kind": kind, "payload": payload, "expectedRevision": expected_revision,
                "expectedGoalGeneration": expected_goal_generation,
                "expectedProposalHash": expected_proposal_hash}
        body_hash = sha256_text(body)
        now = self.clock.now_iso()
        with self.tx() as conn:
            existing = self._idempotency_lookup(conn, run_id, client_request_id, "response", body_hash)
            if existing is not None:
                return existing
            run = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise LedgerError(f"Unknown run {run_id}")
            interaction = conn.execute(
                "SELECT * FROM interactions WHERE id=? AND run_id=?", (interaction_id, run_id)
            ).fetchone()
            if interaction is None:
                raise LedgerError(f"Unknown interaction {interaction_id} for this run")
            # Validate payload before recording anything.
            validate_response_payload(kind, payload)
            seq = int(run["next_response_seq"])
            conn.execute("UPDATE runs SET next_response_seq=?, updated_at=? WHERE run_id=?",
                         (seq + 1, now, run_id))
            response_id = "resp-" + sha256_text({"run": run_id, "seq": seq, "key": client_request_id})[:12]
            stale_reasons = []
            if expected_revision is not None and expected_revision != interaction["revision"]:
                stale_reasons.append("revision")
            if expected_goal_generation is not None and int(expected_goal_generation) != int(interaction["goal_generation"]):
                stale_reasons.append("goal_generation")
            if expected_proposal_hash is not None and expected_proposal_hash != interaction["proposal_hash"]:
                stale_reasons.append("proposal_hash")
            status = "conflict" if stale_reasons else "receipt"
            conn.execute(
                """INSERT INTO responses(id, interaction_id, run_id, actor_id, client_request_id,
                   expected_revision, expected_goal_generation, expected_proposal_hash, kind,
                   payload_json, received_seq, received_at, status, applied)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (response_id, interaction_id, run_id, actor_id, client_request_id,
                 expected_revision, expected_goal_generation, expected_proposal_hash, kind,
                 canonical_json(payload), seq, now, status, 0),
            )
            receipt = {
                "responseId": response_id,
                "clientRequestId": client_request_id,
                "status": status,
                "stale": stale_reasons,
                "interactionId": interaction_id,
                "statusUrl": f"/api/engine/runs/{run_id}/responses/{response_id}",
            }
            conn.execute(
                """INSERT INTO idempotency(run_id, client_request_id, scope, body_hash, receipt_ref,
                   receipt_json, created_at) VALUES (?,?,?,?,?,?,?)""",
                (run_id, client_request_id, "response", body_hash, response_id, canonical_json(receipt), now),
            )
            if status == "receipt":
                reason = "response"
                wait_id = interaction_id
                wake_id = "wake-" + sha256_text({"run": run_id, "resp": response_id})[:16]
                conn.execute(
                    """INSERT OR IGNORE INTO wake_outbox(wake_id, run_id, wait_id, reason,
                       durable_record_ref, created_at) VALUES (?,?,?,?,?,?)""",
                    (wake_id, run_id, wait_id, reason, response_id, now),
                )
                receipt["wakeId"] = wake_id
            conn.execute(
                "UPDATE idempotency SET receipt_json=? WHERE run_id=? AND client_request_id=?",
                (canonical_json(receipt), run_id, client_request_id),
            )
        self.append_event(run_id, "response_received", role="author",
                          payload={"responseId": response_id, "interactionId": interaction_id,
                                   "status": status, "stale": stale_reasons})
        return receipt

    def stale_conflict_context(self, run_id: str, interaction_id: str) -> dict:
        interaction = self.get_interaction(interaction_id)
        return {
            "interactionId": interaction_id,
            "revision": interaction["revision"],
            "goalGeneration": interaction["goal_generation"],
            "proposalHash": interaction["proposal_hash"],
            "options": interaction["options"],
            "status": interaction["status"],
            "pending": self.pending_interaction(run_id),
        }

    # ---------------------------------------------------------------- wakes
    def enqueue_wake(self, run_id: str, *, wait_id: str, reason: str, durable_record_ref: str) -> dict:
        now = self.clock.now_iso()
        wake_id = "wake-" + sha256_text({"run": run_id, "ref": durable_record_ref, "reason": reason})[:16]
        with self.tx() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO wake_outbox(wake_id, run_id, wait_id, reason,
                   durable_record_ref, created_at) VALUES (?,?,?,?,?,?)""",
                (wake_id, run_id, wait_id, reason, durable_record_ref, now),
            )
        return self.next_pending_wake(run_id) or {}

    def next_pending_wake(self, run_id: str, wait_id: str | None = None) -> dict | None:
        sql = "SELECT * FROM wake_outbox WHERE run_id=? AND consumed_at IS NULL"
        params: tuple = (run_id,)
        if wait_id is not None:
            sql += " AND (wait_id=? OR wait_id='boundary')"
            params = (run_id, wait_id)
        sql += " ORDER BY created_at, wake_id LIMIT 1"
        row = self.read_one(sql, params)
        return row

    def pending_wakes(self, run_id: str) -> list[dict]:
        return self.read_all(
            "SELECT * FROM wake_outbox WHERE run_id=? AND consumed_at IS NULL ORDER BY created_at, wake_id",
            (run_id,),
        )

    def mark_wake_delivered(self, wake_id: str, epoch: int) -> None:
        with self.tx() as conn:
            conn.execute(
                "UPDATE wake_outbox SET delivered_at=COALESCE(delivered_at,?), delivered_epoch=? WHERE wake_id=?",
                (self.clock.now_iso(), int(epoch), wake_id),
            )

    def consume_wake(self, wake_id: str, epoch: int, *, wait_id: str | None = None,
                     checkpoint_ref: str | None = None) -> dict:
        """Consume exactly once.  Returns the existing consumption on replay."""
        now = self.clock.now_iso()
        with self.tx() as conn:
            sid = conn.execute("SELECT * FROM wake_outbox WHERE wake_id=?", (wake_id,)).fetchone()
            if sid is None:
                raise LedgerError(f"Unknown wake {wake_id}")
            prior = conn.execute("SELECT * FROM consumptions WHERE wake_id=?", (wake_id,)).fetchone()
            if prior is not None:
                return dict(prior)
            conn.execute(
                "UPDATE wake_outbox SET consumed_at=?, consumed_epoch=? WHERE wake_id=?",
                (now, int(epoch), wake_id),
            )
            conn.execute(
                """INSERT INTO consumptions(wake_id, run_id, wait_id, consumed_at, consumed_epoch,
                   checkpoint_ref) VALUES (?,?,?,?,?,?)""",
                (wake_id, sid["run_id"], wait_id or sid["wait_id"], now, int(epoch), checkpoint_ref),
            )
            return dict(conn.execute("SELECT * FROM consumptions WHERE wake_id=?", (wake_id,)).fetchone())

    def consumption_for(self, wake_id: str) -> dict | None:
        return self.read_one("SELECT * FROM consumptions WHERE wake_id=?", (wake_id,))

    def consume_settled_wakes(self, run_id: str, epoch: int) -> int:
        """Acknowledge boundary wakes whose durable record is already processed.

        A wake is not an effect; consuming it only records that the owner saw
        the record.  Duplicate consumption is a no-op.
        """
        consumed = 0
        for wake in self.pending_wakes(run_id):
            ref = wake["durable_record_ref"]
            settled = True
            if ref.startswith("input-"):
                row = self.read_one("SELECT status FROM inputs WHERE id=?", (ref,))
                settled = row is not None and row["status"] in TERMINAL_INPUT + ("needs_disambiguation",)
            elif ref.startswith("resp-"):
                row = self.read_one("SELECT applied FROM responses WHERE id=?", (ref,))
                settled = row is not None and int(row["applied"]) == 1
            elif ref.startswith("op-"):
                row = self.read_one("SELECT status FROM operations WHERE operation_id=?", (ref,))
                settled = row is not None and row["status"] in (
                    "completed", "failed", "incomplete", "cancelled", "outcome_unknown")
            if settled:
                self.consume_wake(wake["wake_id"], epoch, wait_id=wake["wait_id"],
                                  checkpoint_ref="reconcile")
                consumed += 1
        return consumed


    def wake_view(self, run_id: str) -> dict:
        pending = self.pending_wakes(run_id)
        consumed = self.read_all(
            "SELECT wake_id, wait_id, consumed_at, consumed_epoch FROM consumptions WHERE run_id=? ORDER BY consumed_at",
            (run_id,),
        )
        return {"pending": pending, "consumed": consumed}

    # ---------------------------------------------------------------- revisions / contributions
    def create_revision(self, run_id: str, parent_id: str | None, files: list[dict], *,
                       created_by: str = "engine", spec_hash: str | None = None) -> dict:
        run = self.get_run(run_id)
        revision_id = "rev-" + str(int(run["goal_generation"]))
        # Multiple commits inside one generation need distinct ids.
        base = revision_id
        n = 0
        while self.read_one("SELECT 1 AS x FROM revisions WHERE id=?", (revision_id,)):
            n += 1
            revision_id = f"{base}-{n}"
        now = self.clock.now_iso()
        payload = sorted(files, key=lambda f: f.get("canonical_path", ""))
        rev = RevisionV1(
            id=revision_id, parent_id=parent_id, files=payload,
            spec_hash=spec_hash or run["spec_hash"],
            profile_hash=sha256_text({"profile": run["scope_profile_id"]}),
            prompt_bundle_hash=sha256_text({"prompt": "c2-base-v1"}),
            skill_manifest_hash=sha256_text({"skills": "c2-col-v1"}),
            created_by=created_by, created_at=now,
        )
        with self.tx() as conn:
            conn.execute(
                """INSERT INTO revisions(id, parent_id, files_json, spec_hash, profile_hash,
                   prompt_bundle_hash, skill_manifest_hash, created_by, created_at, run_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (rev.id, rev.parent_id, canonical_json(rev.files), rev.spec_hash, rev.profile_hash,
                 rev.prompt_bundle_hash, rev.skill_manifest_hash, rev.created_by, rev.created_at, run_id),
            )
            conn.execute("UPDATE runs SET observed_revision=?, updated_at=? WHERE run_id=?",
                         (rev.id, now, run_id))
        return self.get_revision(rev.id)

    def publish_revision(self, run_id: str, parent_id: str | None, files: list[dict], *,
                         expected_revision: str, expected_generation: int,
                         required_edit_path: str, proposal_hash: str,
                         created_by: str = "author-authorized-patch",
                         spec_hash: str | None = None,
                         evidence: EvidenceV1 | None = None) -> dict:
        """Guarded canonical revision/evidence/publication commit.

        Barrier, generation, revision, authority and publication identity are
        read and the protected writes are performed in one transaction and on
        one connection.  A receipt that commits before this transaction blocks
        it; a publication that commits first is returned on replay.
        """
        now = self.clock.now_iso()
        payload_files = sorted(files, key=lambda f: f.get("canonical_path", ""))
        with self.tx() as conn:
            run = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise LedgerError(f"Unknown run {run_id}")
            existing = conn.execute(
                "SELECT * FROM publications WHERE run_id=? AND proposal_hash=?",
                (run_id, proposal_hash),
            ).fetchone()
            if existing is not None:
                revision = self.get_revision(existing["revision"])
                return {"revision": revision, "publication": dict(existing),
                        "replayed": True}
            if str(run["observed_revision"]) != str(expected_revision):
                raise PublicationBlocked(
                    f"expected revision {expected_revision}, current {run['observed_revision']}",
                    kind="stale_revision")
            if int(run["goal_generation"]) != int(expected_generation):
                raise PublicationBlocked("goal generation changed", kind="stale_generation")
            barriers = conn.execute(
                "SELECT id FROM inputs WHERE run_id=? AND barrier=1 AND status IN "
                "('received','interpreting','needs_disambiguation')", (run_id,)
            ).fetchall()
            if barriers:
                raise PublicationBlocked(
                    "durable author barrier is active: "
                    + ",".join(row["id"] for row in barriers), kind="input_barrier")
            collab = json.loads(run["collaboration_json"] or "{}")
            if collab.get("edit_denied"):
                raise PublicationBlocked("editing is denied by the author", kind="edit_denied")
            intent = (collab.get("author_edit_intent") or {}).get("value")
            if intent != "edit":
                raise PublicationBlocked("author edit intent is not active",
                                         kind="edit_intent")
            grants = conn.execute(
                "SELECT operation_kinds_json, scope_json FROM grants "
                "WHERE run_id=? AND revoked_at IS NULL", (run_id,)
            ).fetchall()
            allowed = False
            for grant in grants:
                kinds = json.loads(grant["operation_kinds_json"] or "[]")
                scope = json.loads(grant["scope_json"] or "[]")
                if "edit" in kinds and (f"path:{required_edit_path}" in scope
                                        or "path:*" in scope):
                    allowed = True
                    break
            if not allowed:
                raise PublicationBlocked("no live path-scoped edit authority",
                                         kind="edit_authority")
            revision_id = "rev-" + str(int(run["goal_generation"]))
            base = revision_id
            n = 0
            while conn.execute("SELECT 1 AS x FROM revisions WHERE id=?",
                               (revision_id,)).fetchone():
                n += 1
                revision_id = f"{base}-{n}"
            rev = RevisionV1(
                id=revision_id, parent_id=parent_id, files=payload_files,
                spec_hash=spec_hash or run["spec_hash"],
                profile_hash=sha256_text({"profile": run["scope_profile_id"]}),
                prompt_bundle_hash=sha256_text({"prompt": "c2-base-v1"}),
                skill_manifest_hash=sha256_text({"skills": "c2-col-v1"}),
                created_by=created_by, created_at=now,
            )
            conn.execute(
                """INSERT INTO revisions(id, parent_id, files_json, spec_hash, profile_hash,
                   prompt_bundle_hash, skill_manifest_hash, created_by, created_at, run_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (rev.id, rev.parent_id, canonical_json(rev.files), rev.spec_hash,
                 rev.profile_hash, rev.prompt_bundle_hash, rev.skill_manifest_hash,
                 rev.created_by, rev.created_at, run_id),
            )
            conn.execute("UPDATE runs SET observed_revision=?, updated_at=? WHERE run_id=?",
                         (rev.id, now, run_id))
            publication = {
                "id": "pub-" + sha256_text({"run": run_id, "proposal": proposal_hash})[:14],
                "run_id": run_id, "revision": rev.id, "proposal_hash": proposal_hash,
                "path": required_edit_path, "created_at": now,
            }
            conn.execute(
                """INSERT INTO publications(id, run_id, revision, proposal_hash, path,
                   created_at) VALUES (?,?,?,?,?,?)""",
                (publication["id"], run_id, rev.id, proposal_hash, required_edit_path, now),
            )
            if evidence is not None:
                conn.execute(
                    """INSERT OR REPLACE INTO evidence(id, run_id, producer_kind,
                       producer_version, operation_id, input_refs_json, dependency_hashes_json,
                       domain, seed, enumeration_order, budget_json, usage_json, outcome,
                       artifact_refs_json, environment_ref, visibility, freshness,
                       classification, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (evidence.id, run_id, evidence.producer_kind,
                     evidence.producer_version, evidence.operation_id,
                     canonical_json(evidence.input_refs),
                     canonical_json(evidence.dependency_hashes), evidence.domain,
                     evidence.seed, evidence.enumeration_order,
                     canonical_json(evidence.budget_requested),
                     canonical_json(evidence.usage_observed), evidence.outcome,
                     canonical_json(evidence.artifact_refs), evidence.environment_ref,
                     evidence.visibility, evidence.freshness, evidence.classification, now),
                )
        return {"revision": self.get_revision(rev.id), "publication": publication,
                "replayed": False}

    def get_publication(self, run_id: str, proposal_hash: str) -> dict | None:
        row = self.read_one(
            "SELECT * FROM publications WHERE run_id=? AND proposal_hash=?",
            (run_id, proposal_hash))
        return dict(row) if row else None

    def get_revision(self, revision_id: str) -> dict:
        row = self.read_one("SELECT * FROM revisions WHERE id=?", (revision_id,))
        if row is None:
            raise LedgerError(f"Unknown revision {revision_id}")
        row["files"] = json.loads(row.pop("files_json") or "[]")
        return row

    def add_contribution(self, run_id: str, *, source_input_id: str | None, actor_kind: str,
                         actor_id: str, kind: str, blob_hash: str, revision: str,
                         claim_ids: list[str] | None = None,
                         attribution: str = "", derived: list[str] | None = None,
                         supersedes: str | None = None) -> dict:
        contribution_id = "contrib-" + sha256_text(
            {"run": run_id, "blob": blob_hash, "kind": kind, "actor": actor_id}
        )[:12]
        now = self.clock.now_iso()
        with self.tx() as conn:
            row = conn.execute("SELECT * FROM contributions WHERE id=?", (contribution_id,)).fetchone()
            if row is not None:
                return dict(row)
            conn.execute(
                """INSERT INTO contributions(id, run_id, actor_kind, actor_id, source_input_id, kind,
                   original_blob_hash, derived_json, revision, claim_ids_json, validation_status,
                   attribution, supersedes, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (contribution_id, run_id, actor_kind, actor_id, source_input_id, kind, blob_hash,
                 canonical_json(derived or []), revision, canonical_json(claim_ids or []),
                 "unvalidated", attribution, supersedes, now),
            )
        self.append_event(run_id, "contribution_recorded", role=actor_kind,
                          payload={"contributionId": contribution_id, "kind": kind,
                                   "blobHash": blob_hash, "attribution": attribution})
        return self.get_contribution(contribution_id)

    def get_contribution(self, contribution_id: str) -> dict:
        row = self.read_one("SELECT * FROM contributions WHERE id=?", (contribution_id,))
        if row is None:
            raise LedgerError(f"Unknown contribution {contribution_id}")
        row["derived_artifact_refs"] = json.loads(row.pop("derived_json") or "[]")
        row["claim_ids"] = json.loads(row.pop("claim_ids_json") or "[]")
        return row

    def list_contributions(self, run_id: str) -> list[dict]:
        return [self.get_contribution(r["id"]) for r in self.read_all(
            "SELECT id FROM contributions WHERE run_id=? ORDER BY created_at", (run_id,)
        )]

    def set_contribution_validation(self, contribution_id: str, status: str) -> None:
        with self.tx() as conn:
            conn.execute("UPDATE contributions SET validation_status=? WHERE id=?",
                         (status, contribution_id))

    # ---------------------------------------------------------------- grants / delegations
    def create_grant(self, run_id: str, *, actor_id: str, source_input_id: str,
                     operation_kinds: list[str], scope: list[str],
                     goal_generation: int, budget_id: str = "",
                     expires_at: str | None = None) -> dict:
        grant_id = "grant-" + sha256_text(
            {"run": run_id, "input": source_input_id, "ops": operation_kinds, "scope": scope}
        )[:12]
        now = self.clock.now_iso()
        with self.tx() as conn:
            row = conn.execute("SELECT * FROM grants WHERE id=?", (grant_id,)).fetchone()
            if row is not None:
                return dict(row)
            conn.execute(
                """INSERT INTO grants(id, actor_id, source_input_id, run_id, goal_generation,
                   operation_kinds_json, scope_json, budget_id, expires_at, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (grant_id, actor_id, source_input_id, run_id, goal_generation,
                 canonical_json(operation_kinds), canonical_json(scope), budget_id, expires_at, now),
            )
        return self.get_grant(grant_id)

    def get_grant(self, grant_id: str) -> dict:
        row = self.read_one("SELECT * FROM grants WHERE id=?", (grant_id,))
        if row is None:
            raise LedgerError(f"Unknown grant {grant_id}")
        row["operation_kinds"] = json.loads(row.pop("operation_kinds_json") or "[]")
        row["scope"] = json.loads(row.pop("scope_json") or "[]")
        return row

    def active_grant(self, run_id: str) -> dict | None:
        row = self.read_one(
            """SELECT * FROM grants WHERE run_id=? AND revoked_at IS NULL
               ORDER BY created_at DESC, rowid DESC LIMIT 1""",
            (run_id,),
        )
        return self.get_grant(row["id"]) if row else None

    def revoke_grants(self, run_id: str, *, operation_kind: str | None = None) -> list[str]:
        """Revoke grants, optionally only those granting one operation kind.

        Returns the revoked IDs so the caller can preserve an explicit history
        event.  Rows are retained with ``revoked_at``.
        """
        now = self.clock.now_iso()
        revoked: list[str] = []
        with self.tx() as conn:
            rows = conn.execute(
                "SELECT id, operation_kinds_json FROM grants WHERE run_id=? AND revoked_at IS NULL",
                (run_id,),
            ).fetchall()
            for row in rows:
                kinds = json.loads(row["operation_kinds_json"] or "[]")
                if operation_kind is not None and operation_kind not in kinds:
                    continue
                conn.execute("UPDATE grants SET revoked_at=? WHERE id=?", (now, row["id"]))
                revoked.append(row["id"])
        return revoked

    def create_delegation(self, run_id: str, *, objective: str, permitted_operations: list[str],
                          exclusions: list[str], claim_scope: list[str], budget_ceiling: dict,
                          deadline: str | None, return_predicate: dict, grant_ref: str,
                          return_kind: str, return_target_refs: list[str],
                          required_evidence_kinds: list[str]) -> dict:
        delegation_id = "deleg-" + sha256_text(
            {"run": run_id, "objective": objective, "grant": grant_ref}
        )[:12]
        run = self.get_run(run_id)
        now = self.clock.now_iso()
        with self.tx() as conn:
            row = conn.execute("SELECT * FROM delegations WHERE id=?", (delegation_id,)).fetchone()
            if row is not None:
                return self.get_delegation(delegation_id)
            conn.execute(
                """INSERT INTO delegations(id, run_id, goal_generation, objective, permitted_json,
                   exclusions_json, claim_scope_json, budget_ceiling_json, deadline,
                   return_predicate_json, grant_ref, status, return_kind, return_target_json,
                   required_evidence_json, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (delegation_id, run_id, int(run["goal_generation"]), objective,
                 canonical_json(permitted_operations), canonical_json(exclusions),
                 canonical_json(claim_scope), canonical_json(budget_ceiling), deadline,
                 canonical_json(return_predicate), grant_ref, "active", return_kind,
                 canonical_json(return_target_refs), canonical_json(required_evidence_kinds), now),
            )
        return self.get_delegation(delegation_id)

    def get_delegation(self, delegation_id: str) -> dict:
        row = self.read_one("SELECT * FROM delegations WHERE id=?", (delegation_id,))
        if row is None:
            raise LedgerError(f"Unknown delegation {delegation_id}")
        return self._decode_delegation(row)

    @staticmethod
    def _decode_delegation(row: dict) -> dict:
        """Single validated decoder for active/list/view/history paths."""
        row = dict(row)
        try:
            for source, target in (
                ("permitted_json", "permitted_operations"),
                ("exclusions_json", "exclusions"),
                ("claim_scope_json", "claim_scope"),
                ("return_target_json", "return_target_refs"),
                ("required_evidence_json", "required_evidence_kinds"),
            ):
                value = json.loads(row.pop(source) or "[]")
                if not isinstance(value, list):
                    raise ValueError(f"{source} must be a list")
                row[target] = value
            budget = json.loads(row.pop("budget_ceiling_json") or "{}")
            predicate = json.loads(row.pop("return_predicate_json") or "{}")
            if not isinstance(budget, dict) or not isinstance(predicate, dict):
                raise ValueError("budget/predicate must be objects")
            row["budget_ceiling"] = budget
            row["return_predicate"] = predicate
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise LedgerError(
                f"Corrupt delegation record {row.get('id')}: {exc}"
            ) from exc
        row["status"] = str(row.get("status") or "active")
        row["return_kind"] = str(row.get("return_kind") or "campaign_complete")
        if row["status"] not in ("active", "returned", "revoked", "exhausted"):
            raise LedgerError(f"Corrupt delegation record {row.get('id')}: bad status")
        if row["return_kind"] not in ("first_valid_witness", "campaign_complete",
                                      "explanation_delivered", "patch_reviewed"):
            raise LedgerError(f"Corrupt delegation record {row.get('id')}: bad return kind")
        if row.get("deadline"):
            import datetime as _dt

            try:
                _dt.datetime.fromisoformat(str(row["deadline"]).replace("Z", "+00:00"))
            except ValueError as exc:
                raise LedgerError(
                    f"Corrupt delegation record {row.get('id')}: bad deadline"
                ) from exc
        return row

    def active_delegation(self, run_id: str) -> dict | None:
        row = self.read_one(
            "SELECT * FROM delegations WHERE run_id=? AND status='active' ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (run_id,),
        )
        return self.get_delegation(row["id"]) if row else None

    def list_delegations(self, run_id: str) -> list[dict]:
        return [self.get_delegation(r["id"]) for r in self.read_all(
            "SELECT id FROM delegations WHERE run_id=? ORDER BY created_at, rowid", (run_id,)
        )]

    def set_delegation_status(self, delegation_id: str, status: str) -> None:
        if status not in ("active", "returned", "revoked", "exhausted"):
            raise LedgerError(f"Bad delegation status {status}")
        with self.tx() as conn:
            conn.execute("UPDATE delegations SET status=? WHERE id=?", (status, delegation_id))

    # ---------------------------------------------------------------- operations
    def admit_operation(
        self,
        run_id: str,
        *,
        operation_id: str,
        kind: str,
        request_hash: str,
        input_revision: str,
        goal_generation: int,
        steering_epoch: int,
        controller_epoch: int,
        reservation_id: str,
        case_charge: int = 0,
        wall_charge: int = 0,
    ) -> tuple[dict, bool]:
        now = self.clock.now_iso()
        with self.tx() as conn:
            row = conn.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
            if row is not None:
                if row["request_hash"] != request_hash:
                    raise LedgerError("operation id reused with different arguments")
                return self.get_operation(operation_id), False
            if case_charge or wall_charge:
                run = conn.execute("SELECT observed_revision, goal_generation, steering_epoch, controller_epoch FROM runs WHERE run_id=?",
                                   (run_id,)).fetchone()
                barrier = conn.execute(
                    "SELECT 1 FROM inputs WHERE run_id=? AND barrier=1 AND status IN ('received','interpreting')", (run_id,)
                ).fetchone()
                if not run or tuple(run) != (input_revision, goal_generation, steering_epoch, controller_epoch) or barrier:
                    raise PublicationBlocked("Investigation changed before the campaign could start")
                charged = conn.execute(
                    """UPDATE budgets SET cases_used=cases_used+?, wall_ms_used=wall_ms_used+? WHERE run_id=?
                       AND cases_used+?<=cases_limit AND wall_ms_used+?<=wall_ms_limit""",
                    (case_charge, wall_charge, run_id, case_charge, wall_charge),
                )
                if not charged.rowcount:
                    raise LedgerError("campaign case or wall budget exhausted")
            conn.execute(
                """INSERT INTO operations(operation_id, run_id, kind, request_hash, input_revision,
                   goal_generation, steering_epoch, controller_epoch, reservation_id, status,
                   classification, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (operation_id, run_id, kind, request_hash, input_revision, goal_generation,
                 steering_epoch, controller_epoch, reservation_id, "admitted", "pending", now, now),
            )
            conn.execute("UPDATE runs SET active_operation_id=?, updated_at=? WHERE run_id=?",
                         (operation_id, now, run_id))
        return self.get_operation(operation_id), True

    def get_operation(self, operation_id: str) -> dict:
        row = self.read_one("SELECT * FROM operations WHERE operation_id=?", (operation_id,))
        if row is None:
            raise LedgerError(f"Unknown operation {operation_id}")
        row["result"] = json.loads(row.pop("result_json") or "null")
        row["attempts"] = json.loads(row.pop("attempts_json") or "[]")
        row["raw_receipt"] = json.loads(row.pop("raw_json") or "null")
        return row

    def stage_worker_receipt(self, operation_id: str, *, raw: dict, job_id: str | None,
                             status: str = "pending") -> dict:
        now = self.clock.now_iso()
        with self.tx() as conn:
            if raw.get("campaignWallMs") is not None:
                operation = conn.execute("SELECT result_json FROM operations WHERE operation_id=?",
                                         (operation_id,)).fetchone()
                if operation and operation["result_json"]:
                    return self.get_operation(operation_id)
            conn.execute(
                """UPDATE operations SET raw_json=?, job_id=COALESCE(?,job_id), status=?,
                   dispatched_at=COALESCE(dispatched_at,?), updated_at=? WHERE operation_id=?""",
                (canonical_json(raw), job_id, status, now, now, operation_id),
            )
        return self.get_operation(operation_id)

    def add_case_usage(self, run_id: str, cases: int) -> None:
        with self.tx() as conn:
            conn.execute("UPDATE budgets SET cases_used=cases_used+? WHERE run_id=?",
                         (int(cases), run_id))

    def op_by_job(self, job_id: str) -> dict | None:
        row = self.read_one("SELECT * FROM operations WHERE job_id=?", (job_id,))
        return self.get_operation(row["operation_id"]) if row else None

    def list_operations(self, run_id: str) -> list[dict]:
        return [self.get_operation(r["operation_id"]) for r in self.read_all(
            "SELECT operation_id FROM operations WHERE run_id=? ORDER BY created_at", (run_id,)
        )]

    def mark_operation_status(self, operation_id: str, status: str, *, classification: str | None = None) -> None:
        now = self.clock.now_iso()
        with self.tx() as conn:
            conn.execute(
                "UPDATE operations SET status=?, classification=COALESCE(?,classification), updated_at=? WHERE operation_id=?",
                (status, classification, now, operation_id),
            )
        self.append_event(self.get_operation(operation_id)["run_id"], "operation_status", role="host",
                          payload={"operationId": operation_id, "status": status,
                                   "classification": classification})

    def commit_operation_result(self, operation_id: str, result: OperationResultV1,
                                evidence: EvidenceV1 | None = None, *, evidence_epoch: tuple | None = None) -> dict:
        now = self.clock.now_iso()
        run_id = ""
        with self.tx() as conn:
            row = conn.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
            if row is None:
                raise LedgerError(f"Unknown operation {operation_id}")
            run_id = row["run_id"]
            if row["result_json"]:
                return self.get_operation(operation_id)
            if evidence_epoch and evidence is not None and evidence.freshness == "current":
                run = conn.execute("SELECT observed_revision, goal_generation, steering_epoch, controller_epoch FROM runs WHERE run_id=?",
                                   (run_id,)).fetchone()
                barrier = conn.execute(
                    "SELECT 1 FROM inputs WHERE run_id=? AND barrier=1 AND status IN ('received','interpreting')", (run_id,)
                ).fetchone()
                if not run or tuple(run) != evidence_epoch or barrier:
                    evidence = evidence.model_copy(update={"freshness": "stale"})
                    result = result.model_copy(update={"status": "incomplete", "classification": "stale"})
            conn.execute(
                "UPDATE operations SET status=?, classification=?, result_json=?, updated_at=? WHERE operation_id=?",
                (result.status, result.classification, canonical_json(result.model_dump()), now, operation_id),
            )
            if evidence is not None:
                conn.execute(
                    """INSERT OR REPLACE INTO evidence(id, run_id, producer_kind, producer_version,
                       operation_id, input_refs_json, dependency_hashes_json, domain, seed,
                       enumeration_order, budget_json, usage_json, outcome, artifact_refs_json,
                       environment_ref, visibility, freshness, classification, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (evidence.id, run_id, evidence.producer_kind, evidence.producer_version,
                     evidence.operation_id, canonical_json(evidence.input_refs),
                     canonical_json(evidence.dependency_hashes), evidence.domain, evidence.seed,
                     evidence.enumeration_order, canonical_json(evidence.budget_requested),
                     canonical_json(evidence.usage_observed), evidence.outcome,
                     canonical_json(evidence.artifact_refs), evidence.environment_ref,
                     evidence.visibility, evidence.freshness, evidence.classification, now),
                )
            conn.execute("UPDATE runs SET active_operation_id=NULL, updated_at=? WHERE run_id=?",
                         (now, run_id))
        self.append_event(run_id, "operation_receipt", role="worker",
                          payload={"operationId": operation_id, "status": result.status,
                                   "classification": result.classification,
                                   "evidenceId": evidence.id if evidence else None})
        return self.get_operation(operation_id)

    def add_evidence(self, run_id: str, evidence: EvidenceV1) -> dict:
        with self.tx() as conn:
            self._write_evidence(conn, run_id, evidence, self.clock.now_iso())
        return self.get_evidence(evidence.id)

    @staticmethod
    def _write_evidence(conn, run_id: str, evidence: EvidenceV1, now: str) -> None:
        conn.execute(
                """INSERT OR REPLACE INTO evidence(id, run_id, producer_kind, producer_version,
                   operation_id, input_refs_json, dependency_hashes_json, domain, seed,
                   enumeration_order, budget_json, usage_json, outcome, artifact_refs_json,
                   environment_ref, visibility, freshness, classification, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (evidence.id, run_id, evidence.producer_kind,
                 evidence.producer_version, evidence.operation_id,
                 canonical_json(evidence.input_refs), canonical_json(evidence.dependency_hashes),
                 evidence.domain, evidence.seed, evidence.enumeration_order,
                 canonical_json(evidence.budget_requested), canonical_json(evidence.usage_observed),
                 evidence.outcome, canonical_json(evidence.artifact_refs), evidence.environment_ref,
                 evidence.visibility, evidence.freshness, evidence.classification,
                 now),
            )

    def get_evidence(self, evidence_id: str) -> dict:
        row = self.read_one("SELECT * FROM evidence WHERE id=?", (evidence_id,))
        if row is None:
            raise LedgerError(f"Unknown evidence {evidence_id}")
        row["input_refs"] = json.loads(row.pop("input_refs_json") or "[]")
        row["dependency_hashes"] = json.loads(row.pop("dependency_hashes_json") or "{}")
        row["budget_requested"] = json.loads(row.pop("budget_json") or "{}")
        row["usage_observed"] = json.loads(row.pop("usage_json") or "{}")
        row["artifact_refs"] = json.loads(row.pop("artifact_refs_json") or "[]")
        row["freshness"] = row.get("freshness")
        return row

    def list_evidence(self, run_id: str) -> list[dict]:
        return [self.get_evidence(r["id"]) for r in self.read_all(
            "SELECT id FROM evidence WHERE run_id=? ORDER BY created_at", (run_id,)
        )]

    def invalidate_current_results(self, run_id: str, *, reason: str) -> list[str]:
        now = self.clock.now_iso()
        invalidated: list[str] = []
        with self.tx() as conn:
            rows = conn.execute(
                "SELECT id FROM evidence WHERE run_id=? AND freshness='current'", (run_id,)
            ).fetchall()
            invalidated = [r["id"] for r in rows]
            for evidence_id in invalidated:
                conn.execute("UPDATE evidence SET freshness='stale' WHERE id=?", (evidence_id,))
            conn.execute("UPDATE explanations SET current=0 WHERE run_id=?", (run_id,))
        if invalidated:
            self.append_event(run_id, "evidence_invalidated", role="host",
                              payload={"evidenceIds": invalidated, "reason": reason, "at": now})
        return invalidated

    # ---------------------------------------------------------------- findings / explanations / handoffs
    def upsert_finding(self, run_id: str, finding: FindingV1, *, require_current_evidence: str | None = None) -> dict:
        with self.tx() as conn:
            row = conn.execute("SELECT * FROM findings WHERE id=?", (finding.id,)).fetchone()
            if row is not None:
                return dict(row)
            if require_current_evidence:
                current = conn.execute("SELECT 1 FROM evidence WHERE id=? AND run_id=? AND freshness='current'",
                                       (require_current_evidence, run_id)).fetchone()
                barrier = conn.execute("SELECT 1 FROM inputs WHERE run_id=? AND barrier=1 AND status IN ('received','interpreting')",
                                       (run_id,)).fetchone()
                if not current or barrier:
                    return {}
            conn.execute(
                """INSERT INTO findings(id, run_id, claim_id, revision, origin_role, origin_model,
                   severity, allegation, evidence_json, suggested_discriminator, status,
                   disposition_reason, resolution_evidence_json, resolver_kind, supersedes, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (finding.id, run_id, finding.claim_id, finding.revision, finding.origin_role,
                 finding.origin_model, finding.severity, finding.allegation,
                 canonical_json(finding.evidence_refs), finding.suggested_discriminator,
                 finding.status, finding.disposition_reason,
                 canonical_json(finding.resolution_evidence_refs), finding.resolver_kind,
                 finding.supersedes, self.clock.now_iso()),
            )
        self.append_event(run_id, "finding_recorded", role=finding.origin_role,
                          payload={"findingId": finding.id, "status": finding.status,
                                   "severity": finding.severity, "claimId": finding.claim_id})
        return self.get_finding(finding.id)

    def get_finding(self, finding_id: str) -> dict:
        row = self.read_one("SELECT * FROM findings WHERE id=?", (finding_id,))
        if row is None:
            raise LedgerError(f"Unknown finding {finding_id}")
        row["evidence_refs"] = json.loads(row.pop("evidence_json") or "[]")
        row["resolution_evidence_refs"] = json.loads(row.pop("resolution_evidence_json") or "[]")
        return row

    def list_findings(self, run_id: str) -> list[dict]:
        return [self.get_finding(r["id"]) for r in self.read_all(
            "SELECT id FROM findings WHERE run_id=? ORDER BY created_at", (run_id,)
        )]

    def add_explanation(self, run_id: str, explanation: ExplanationV1) -> dict:
        with self.tx() as conn:
            conn.execute("UPDATE explanations SET current=0 WHERE run_id=?", (run_id,))
            conn.execute(
                """INSERT OR REPLACE INTO explanations(id, run_id, revision, claim_refs_json,
                   audience_depth, question, short_answer, worked_example_ref, links_json,
                   evidence_json, alternatives_json, uncertainty_json, next_actions_json,
                   current, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (explanation.id, run_id, explanation.revision,
                 canonical_json(explanation.claim_refs), explanation.audience_depth,
                 explanation.question, explanation.short_answer, explanation.worked_example_ref,
                 canonical_json(explanation.assumption_to_code_links),
                 canonical_json(explanation.evidence_refs),
                 canonical_json(explanation.alternatives),
                 canonical_json(explanation.uncertainty),
                 canonical_json(explanation.next_author_actions),
                 1, self.clock.now_iso()),
            )
        self.append_event(run_id, "explanation_committed", role="host",
                          payload={"explanationId": explanation.id, "depth": explanation.audience_depth})
        return self.get_explanation(explanation.id)

    def get_explanation(self, explanation_id: str) -> dict:
        row = self.read_one("SELECT * FROM explanations WHERE id=?", (explanation_id,))
        if row is None:
            raise LedgerError(f"Unknown explanation {explanation_id}")
        row["claim_refs"] = json.loads(row.pop("claim_refs_json") or "[]")
        row["links"] = json.loads(row.pop("links_json") or "[]")
        row["assumption_to_code_links"] = row["links"]
        row["evidence_refs"] = json.loads(row.pop("evidence_json") or "[]")
        row["alternatives"] = json.loads(row.pop("alternatives_json") or "[]")
        row["uncertainty"] = json.loads(row.pop("uncertainty_json") or "[]")
        row["next_author_actions"] = json.loads(row.pop("next_actions_json") or "[]")
        row["current"] = bool(row["current"])
        return row

    def current_explanation(self, run_id: str) -> dict | None:
        row = self.read_one(
            "SELECT id FROM explanations WHERE run_id=? AND current=1 ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (run_id,),
        )
        return self.get_explanation(row["id"]) if row else None

    def add_handoff(self, run_id: str, handoff: HandoffV1) -> dict:
        with self.tx() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO handoffs(id, run_id, goal_generation, revision, applied_seq,
                   outcome, decisions_json, contributions_json, completed_json, open_questions_json,
                   evidence_json, invalidations_json, budget_json, next_actions_json,
                   stage_return_json, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (handoff.id, run_id, handoff.goal_generation, handoff.revision,
                 handoff.last_applied_author_seq, handoff.outcome,
                 canonical_json(handoff.decisions), canonical_json(handoff.contributions),
                 canonical_json(handoff.completed_work), canonical_json(handoff.open_questions),
                 canonical_json(handoff.current_evidence), canonical_json(handoff.invalidations),
                 canonical_json(handoff.remaining_budget), canonical_json(handoff.next_actions),
                 canonical_json(handoff.stage_return), self.clock.now_iso()),
            )
            conn.execute("UPDATE runs SET handoff_ref=?, updated_at=? WHERE run_id=?",
                         (handoff.id, self.clock.now_iso(), run_id))
        self.append_event(run_id, "stage_returned" if handoff.outcome == "stage_returned" else "handoff",
                          role="host", payload={"handoffId": handoff.id, "outcome": handoff.outcome})
        return self.get_handoff(handoff.id)

    def get_handoff(self, handoff_id: str) -> dict:
        row = self.read_one("SELECT * FROM handoffs WHERE id=?", (handoff_id,))
        if row is None:
            raise LedgerError(f"Unknown handoff {handoff_id}")
        for key in ("decisions_json", "contributions_json", "completed_json",
                    "open_questions_json", "evidence_json", "invalidations_json",
                    "next_actions_json"):
            row[key.replace("_json", "")] = json.loads(row.pop(key) or "[]")
        row["remaining_budget"] = json.loads(row.pop("budget_json") or "{}")
        row["stage_return"] = json.loads(row.pop("stage_return_json") or "null")
        return row

    def latest_handoff(self, run_id: str) -> dict | None:
        row = self.read_one(
            "SELECT id FROM handoffs WHERE run_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1", (run_id,)
        )
        return self.get_handoff(row["id"]) if row else None

    # ---------------------------------------------------------------- budget
    def get_budget(self, run_id: str) -> dict:
        row = self.read_one("SELECT * FROM budgets WHERE run_id=?", (run_id,))
        if row is None:
            raise LedgerError(f"Unknown budget for {run_id}")
        return row

    def reserve_action(self, run_id: str, *, action_id: str, attempts_limit: int = 3,
                       cases: int = 0, wall_ms: int = 0) -> dict:
        budget = self.get_budget(run_id)
        now = self.clock.now_iso()
        with self.tx() as conn:
            existing = conn.execute(
                "SELECT * FROM reservations WHERE run_id=? AND action_id=?", (run_id, action_id)
            ).fetchone()
            if existing is not None:
                return dict(existing)
            if int(budget["model_attempts_used"]) >= int(budget["model_attempts_limit"]):
                raise LedgerError("run model attempt budget exhausted")
            reservation_id = "resv-" + sha256_text({"run": run_id, "action": action_id})[:12]
            conn.execute(
                """INSERT INTO reservations(id, run_id, budget_id, action_id, attempts_limit,
                   cases, wall_ms, state, created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                (reservation_id, run_id, budget["id"], action_id, int(attempts_limit),
                 int(cases), int(wall_ms), "reserved", now),
            )
        return self.get_reservation(reservation_id)

    def get_reservation(self, reservation_id: str) -> dict:
        row = self.read_one("SELECT * FROM reservations WHERE id=?", (reservation_id,))
        if row is None:
            raise LedgerError(f"Unknown reservation {reservation_id}")
        return row

    def record_attempt(self, reservation_id: str, *, kind: str, outcome: str,
                       usage: dict | None = None, attempt_index: int | None = None) -> dict:
        now = self.clock.now_iso()
        with self.tx() as conn:
            resv = conn.execute("SELECT * FROM reservations WHERE id=?", (reservation_id,)).fetchone()
            if resv is None:
                raise LedgerError(f"Unknown reservation {reservation_id}")
            budget = conn.execute(
                "SELECT model_attempts_used, model_attempts_limit FROM budgets WHERE id=?",
                (resv["budget_id"],),
            ).fetchone()
            if budget is None:
                raise LedgerError("Unknown budget for reservation")
            if int(budget["model_attempts_used"]) >= int(budget["model_attempts_limit"]):
                raise LedgerError("run model attempt budget exhausted")
            n = conn.execute("SELECT COUNT(*) AS n FROM attempts WHERE reservation_id=?",
                             (reservation_id,)).fetchone()["n"]
            index = int(attempt_index if attempt_index is not None else n + 1)
            if index > int(resv["attempts_limit"]):
                raise LedgerError("action attempt ceiling exhausted")
            attempt_id = "attempt-" + sha256_text({"resv": reservation_id, "index": index})[:14]
            conn.execute(
                """INSERT OR REPLACE INTO attempts(id, reservation_id, attempt_index, kind, outcome,
                   usage_json, started_at, ended_at) VALUES (?,?,?,?,?,?,?,?)""",
                (attempt_id, reservation_id, index, kind, outcome,
                 canonical_json(usage or {}), now, now),
            )
            conn.execute(
                "UPDATE budgets SET model_attempts_used=model_attempts_used+1 WHERE id=?",
                (resv["budget_id"],),
            )
        return {"attemptId": attempt_id, "index": index}

    def attempts_for(self, reservation_id: str) -> list[dict]:
        rows = self.read_all("SELECT * FROM attempts WHERE reservation_id=? ORDER BY attempt_index",
                             (reservation_id,))
        for row in rows:
            row["usage"] = json.loads(row.pop("usage_json") or "{}")
        return rows

    def finish_attempt(self, attempt_id: str, *, outcome: str, usage: dict | None = None, meter: dict | None = None) -> None:
        with self.tx() as conn:
            conn.execute(
                "UPDATE attempts SET outcome=?, usage_json=?, context_json=?, ended_at=? WHERE id=? AND outcome='in_flight'",
                (outcome, canonical_json(usage or {}), canonical_json(meter) if meter else None, self.clock.now_iso(), attempt_id),
            )

    def request_context(self, run_id: str) -> list[dict]:
        rows = self.read_all(
            """SELECT id, started_at, context_json FROM (
                SELECT a.id, a.started_at, a.context_json, a.rowid AS sequence,
                       ROW_NUMBER() OVER (PARTITION BY json_extract(a.context_json, '$.role')
                           ORDER BY a.started_at DESC, a.rowid DESC) AS rank
                FROM attempts a JOIN reservations r ON r.id=a.reservation_id
                WHERE r.run_id=? AND a.context_json IS NOT NULL
               ) WHERE rank=1 ORDER BY started_at DESC, sequence DESC""",
            (run_id,),
        )
        return [{**json.loads(row["context_json"]), "id": row["id"], "requestedAt": row["started_at"]} for row in rows]

    def settle_reservation(self, reservation_id: str, state: str = "settled") -> dict:
        if state not in ("settled", "exhausted", "cancelled", "unknown"):
            raise LedgerError(f"Bad reservation state {state}")
        now = self.clock.now_iso()
        budget = self.get_budget(self.get_reservation(reservation_id)["run_id"])
        with self.tx() as conn:
            conn.execute("UPDATE reservations SET state=?, settled_at=? WHERE id=?",
                         (state, now, reservation_id))
            settles = json.loads(budget["settled_json"] or "{}")
            if reservation_id not in settles:
                settles[reservation_id] = state
                conn.execute("UPDATE budgets SET settled_json=? WHERE id=?",
                             (canonical_json(settles), budget["id"]))
        return self.get_reservation(reservation_id)

    def add_active_seconds(self, run_id: str, seconds: float) -> None:
        with self.tx() as conn:
            conn.execute("UPDATE budgets SET active_seconds_used=active_seconds_used+? WHERE run_id=?",
                         (float(seconds), run_id))

    def budget_view(self, run_id: str) -> dict:
        b = self.get_budget(run_id)
        pending = self.read_all(
            "SELECT id, action_id, state FROM reservations WHERE run_id=? AND state='reserved'", (run_id,)
        )
        settled = self.read_all("SELECT id, action_id, state FROM reservations WHERE run_id=? AND state!='reserved'", (run_id,))
        return {
            "modelAttemptsLimit": b["model_attempts_limit"],
            "modelAttemptsUsed": b["model_attempts_used"],
            "modelAttemptsRemaining": b["model_attempts_limit"] - b["model_attempts_used"],
            "casesLimit": b["cases_limit"],
            "casesUsed": b["cases_used"],
            "campaignWallMsLimit": b["wall_ms_limit"],
            "campaignWallMsReserved": b["wall_ms_used"],
            "activeSecondsLimit": b["active_seconds_limit"],
            "activeSecondsUsed": b["active_seconds_used"],
            "unknownUsage": self._unknown_usage(run_id),
            "pendingReservations": pending,
            "settledReservations": settled,
        }

    def _unknown_usage(self, run_id: str) -> bool:
        rows = self.read_all(
            """SELECT a.usage_json FROM attempts a JOIN reservations r ON r.id=a.reservation_id
               WHERE r.run_id=?""", (run_id,),
        )
        return any(json.loads(r["usage_json"] or "{}").get("unknown") for r in rows)

    # ---------------------------------------------------------------- approvals / denial
    def create_approval(self, run_id: str, approval: ApprovalV1) -> dict:
        with self.tx() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO approvals(id, run_id, human_actor, revision, action_kind,
                   effect_manifest_hash, evidence_root_hash, goal_generation, steering_epoch,
                   profile_hash, decision, created_at, invalidated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (approval.id, run_id, approval.human_actor, approval.revision, approval.action_kind,
                 approval.effect_manifest_hash, approval.evidence_root_hash,
                 approval.goal_generation, approval.steering_epoch, approval.profile_hash,
                 approval.decision, self.clock.now_iso(), approval.invalidated_at),
            )
        return self.get_approval(approval.id)

    def get_approval(self, approval_id: str) -> dict:
        row = self.read_one("SELECT * FROM approvals WHERE id=?", (approval_id,))
        if row is None:
            raise LedgerError(f"Unknown approval {approval_id}")
        return row

    def check_approval_binding(self, approval_id: str, *, expected_revision: str,
                               expected_goal_generation: int, expected_steering_epoch: int,
                               expected_manifest_hash: str) -> dict:
        approval = self.get_approval(approval_id)
        run = self.get_run(approval["run_id"])
        reasons = []
        if approval["invalidated_at"]:
            reasons.append("invalidated")
        if approval["revision"] != expected_revision or run["observed_revision"] != expected_revision:
            reasons.append("revision")
        if int(approval["goal_generation"]) != int(expected_goal_generation):
            reasons.append("goal_generation")
        if int(approval["steering_epoch"]) != int(expected_steering_epoch):
            reasons.append("steering_epoch")
        if approval["effect_manifest_hash"] != expected_manifest_hash:
            reasons.append("effect_manifest")
        return {"ok": not reasons, "reasons": reasons, "approval": approval}

    def log_controller(self, run_id: str, epoch: int, event: str, detail: str = "") -> None:
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO controller_log(run_id, epoch, event, detail, created_at) VALUES (?,?,?,?,?)",
                (run_id, int(epoch), event, detail[:4000], self.clock.now_iso()),
            )

    def controller_events(self, run_id: str) -> list[dict]:
        return self.read_all("SELECT * FROM controller_log WHERE run_id=? ORDER BY id", (run_id,))

    # ---------------------------------------------------------------- projection
    def begin_projection(self, run_id: str, revision: str, *, manifest: list[dict],
                         base_hashes: dict) -> dict:
        intent_id = "proj-" + sha256_text({"run": run_id, "revision": revision})[:12]
        now = self.clock.now_iso()
        with self.tx() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO projection_intents(id, run_id, revision, state,
                   manifest_json, base_hashes_json, conflicts_json, patch_blob, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (intent_id, run_id, revision, "in_progress", canonical_json(manifest),
                 canonical_json(base_hashes), "[]", None, now, now),
            )
        return self.get_projection_intent(intent_id)

    def get_projection_intent(self, intent_id: str) -> dict:
        row = self.read_one("SELECT * FROM projection_intents WHERE id=?", (intent_id,))
        if row is None:
            raise LedgerError(f"Unknown projection intent {intent_id}")
        row["manifest"] = json.loads(row.pop("manifest_json") or "[]")
        row["base_hashes"] = json.loads(row.pop("base_hashes_json") or "{}")
        row["conflicts"] = json.loads(row.pop("conflicts_json") or "[]")
        return row

    def finish_projection(self, intent_id: str, state: str, *,
                          conflicts: list[dict] | None = None,
                          patch_blob: str | None = None) -> dict:
        if state not in ("complete", "conflict", "pending"):
            raise LedgerError(f"Bad projection state {state}")
        with self.tx() as conn:
            conn.execute(
                """UPDATE projection_intents SET state=?, conflicts_json=?, patch_blob=?, updated_at=?
                   WHERE id=?""",
                (state, canonical_json(conflicts or []), patch_blob,
                 self.clock.now_iso(), intent_id),
            )
        return self.get_projection_intent(intent_id)

    def projection_intents(self, run_id: str) -> list[dict]:
        return [self.get_projection_intent(r["id"]) for r in self.read_all(
            "SELECT id FROM projection_intents WHERE run_id=? ORDER BY created_at", (run_id,)
        )]
