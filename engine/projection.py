"""Managed checkout projection with truthful filesystem semantics.

Immutable revisions are canonical.  A SQLite transaction cannot make arbitrary
filesystem edits atomic (R06), so projection:
  * writes only under an application-owned managed root,
  * verifies every member against its expected base hash,
  * records a durable intent before writing,
  * never overwrites an externally edited file (leaves a reviewable patch),
  * reports partial state instead of pretending the checkout is complete.
"""
from __future__ import annotations

import hashlib
import pathlib

from .policy import PolicyDenied, canonical_workspace_path
from .lockfile import FileLock
from .store import ApplicationStore


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ProjectionConflict(RuntimeError):
    def __init__(self, message: str, conflicts: list[dict]):
        super().__init__(message)
        self.conflicts = conflicts


class ProjectionManager:
    def __init__(self, root: pathlib.Path | str, store: ApplicationStore, *, managed: bool = True):
        self.root = pathlib.Path(root)
        self.store = store
        self.managed = managed
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = FileLock(str(self.root / ".agent-projection.lock"))

    def current_hash(self, rel_path: str) -> str | None:
        target = canonical_workspace_path(self.root, rel_path)
        if not target.is_file():
            return None
        return _hash_bytes(target.read_bytes())

    def apply(self, run_id: str, revision: str, files: list[dict],
              base_hashes: dict[str, str | None]) -> dict:
        """Project a committed manifest; returns complete/conflict/pending state."""
        if not self.managed:
            return self._patch_only(run_id, revision, files,
                                    "checkout is not application-owned; a patch is returned")
        manifest = [{"path": f["canonical_path"], "hash": f["hash"]} for f in files]
        intent = self.store.begin_projection(run_id, revision, manifest=manifest,
                                            base_hashes=base_hashes)
        conflicts: list[dict] = []
        with self._lock:
            # Preflight every member before writing anything.
            staged: list[tuple[dict, bytes]] = []
            for entry in files:
                rel = entry["canonical_path"]
                expected = base_hashes.get(rel)
                current = self.current_hash(rel)
                if current != expected and current != entry["hash"]:
                    conflicts.append({
                        "path": rel, "expectedBase": expected, "current": current,
                        "reason": "external edit or unexpected base",
                    })
                    continue
                body = self.store.get_blob(entry["hash"])
                staged.append((entry, body))
            if conflicts:
                patch = self._make_patch(run_id, revision, files, base_hashes, conflicts)
                self.store.finish_projection(intent["id"], "conflict", conflicts=conflicts,
                                             patch_blob=patch)
                self.store.append_event(run_id, "projection_conflict", role="host",
                                        payload={"revision": revision, "conflicts": conflicts})
                return {"state": "conflict", "conflicts": conflicts, "patchBlob": patch,
                        "intent": intent["id"]}
            # Write; a crash here leaves an in-progress intent.
            written: list[dict] = []
            for entry, body in staged:
                target = canonical_workspace_path(self.root, entry["canonical_path"])
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_suffix(target.suffix + ".engine-tmp")
                tmp.write_bytes(body)
                tmp.replace(target)
                written.append({"path": entry["canonical_path"], "hash": _hash_bytes(body)})
            # Verify the whole manifest before declaring completion.
            for entry in files:
                actual = self.current_hash(entry["canonical_path"])
                if actual != entry["hash"]:
                    conflicts.append({"path": entry["canonical_path"],
                                      "expected": entry["hash"], "current": actual,
                                      "reason": "post-write mismatch"})
            state = "complete" if not conflicts else "pending"
            self.store.finish_projection(intent["id"], state, conflicts=conflicts)
            self.store.append_event(run_id, "projection_complete" if state == "complete"
                                    else "projection_pending", role="host",
                                    payload={"revision": revision, "files": written,
                                             "conflicts": conflicts})
            return {"state": state, "conflicts": conflicts, "files": written,
                    "intent": intent["id"]}

    def _patch_only(self, run_id: str, revision: str, files: list[dict],
                    base_hashes: dict, reason: str) -> dict:
        patch = self._make_patch(run_id, revision, files, base_hashes, [])
        self.store.append_event(run_id, "patch_exported", role="host",
                                payload={"revision": revision, "patchBlob": patch, "reason": reason})
        return {"state": "patch", "patchBlob": patch, "reason": reason}

    def _make_patch(self, run_id: str, revision: str, files: list[dict],
                    base_hashes: dict, conflicts: list[dict]) -> str:
        import json

        payload = {
            "revision": revision, "runId": run_id,
            "files": [{"path": f["canonical_path"], "hash": f["hash"],
                       "base": base_hashes.get(f["canonical_path"])} for f in files],
            "conflicts": conflicts, "format": "engine-explicit-import-v1",
        }
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        return self.store.put_blob(body, kind="patch")

    def reconcile(self, run_id: str) -> list[dict]:
        """After restart, report incomplete intents; never silently finish them."""
        out = []
        for intent in self.store.projection_intents(run_id):
            if intent["state"] == "in_progress":
                mismatches = []
                for entry in intent["manifest"]:
                    path = entry.get("path") or entry.get("canonical_path")
                    current = self.current_hash(path)
                    if current != entry["hash"]:
                        mismatches.append({"path": path, "expected": entry["hash"],
                                           "current": current})
                if mismatches:
                    self.store.finish_projection(intent["id"], "pending", conflicts=mismatches)
                    out.append({"intent": intent["id"], "state": "pending",
                                "conflicts": mismatches})
                else:
                    out.append({"intent": intent["id"], "state": "in_progress",
                                "note": "all members match; projection may be completed"})
        return out
