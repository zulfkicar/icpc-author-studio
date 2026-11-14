"""Canonical visibility, capability and ingress policy.

Fail-closed by construction: unknown principals, operation kinds, visibility
classes, paths and payload shapes are denied.  Actor, run and epoch are
server-owned; they are never read from a request body as trusted values.
"""
from __future__ import annotations

import pathlib
import re
import unicodedata
from typing import Any

from .schemas import CapabilityRecord

LOCAL_ACTOR = "local-author"
LOCAL_SESSION = "loopback-author-session"

MAX_CONTRIBUTION_BYTES = 1 * 1024 * 1024
MAX_INPUT_BYTES = 10 * 1024 * 1024
MAX_TEXT_CHARS = 200_000
MAX_ARTIFACTS_PER_INPUT = 32

_ALLOWED_OPERATION_KINDS = {
    "differential_search",
    "replay_diagnostic",
    "evaluate_mutants",  # deferred; admission fails closed with unsupported
    "reduce_counterexample",  # deferred
    "read_artifact",
}

_DEFERRED_OPERATION_KINDS = {"evaluate_mutants", "reduce_counterexample"}

_REQUIRED_PROFILE = "batch-exact-integer-v1"

CAPABILITIES: dict[str, CapabilityRecord] = {
    "author-engine": CapabilityRecord(
        id="author-engine",
        name="Author engine",
        operation_kinds=sorted(_ALLOWED_OPERATION_KINDS),
        visibility=["author"],
        can_execute=True,
        can_mutate=True,
        can_approve=False,
    ),
    "review-mode": CapabilityRecord(
        id="review-mode",
        name="Review mode / specialist",
        operation_kinds=["read_artifact"],
        visibility=["review"],
        can_execute=False,
        can_mutate=False,
        can_approve=False,
    ),
    "worker-candidate": CapabilityRecord(
        id="worker-candidate",
        name="Worker candidate",
        operation_kinds=[],
        visibility=[],
        can_execute=True,
        can_mutate=False,
        can_approve=False,
    ),
    "human-ui": CapabilityRecord(
        id="human-ui",
        name="Human UI",
        operation_kinds=["read_artifact"],
        visibility=["author"],
        can_execute=False,
        can_mutate=True,
        can_approve=False,
    ),
}


class PolicyDenied(PermissionError):
    def __init__(self, message: str, code: str = "policy_denied"):
        super().__init__(message)
        self.code = code


def capability(principal: str) -> CapabilityRecord:
    try:
        return CAPABILITIES[principal]
    except KeyError as exc:
        raise PolicyDenied(f"Unknown principal {principal}", "unknown_principal") from exc


def require_principal(principal: str) -> CapabilityRecord:
    return capability(principal)


def require_profile(profile: str) -> None:
    if profile != _REQUIRED_PROFILE:
        raise PolicyDenied(
            f"Profile {profile!r} is not qualified in V0-V3", "unsupported_profile"
        )


def operation_supported(kind: str, grant_kinds: list[str]) -> bool:
    if kind not in _ALLOWED_OPERATION_KINDS or kind in _DEFERRED_OPERATION_KINDS:
        return False
    return kind in grant_kinds


def _normalize_relative(path: str) -> str:
    if not isinstance(path, str):
        raise PolicyDenied("Path must be a string", "bad_path")
    if "\x00" in path:
        raise PolicyDenied("NUL byte in path", "bad_path")
    # Normalize unicode and separators before any prefix comparison.
    raw = unicodedata.normalize("NFC", path).replace("\\", "/")
    if raw.startswith("/") or raw.startswith("~"):
        raise PolicyDenied("Absolute paths are not allowed", "bad_path")
    if re.match(r"^[A-Za-z]:", raw):
        raise PolicyDenied("Drive-letter paths are not allowed", "bad_path")
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise PolicyDenied("Parent traversal is not allowed", "bad_path")
    if not parts:
        raise PolicyDenied("Empty path", "bad_path")
    reserved = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
                *(f"lpt{i}" for i in range(1, 10))}
    for part in parts:
        stem = part.split(".")[0].lower()
        if stem in reserved:
            raise PolicyDenied(f"Reserved Windows name {part!r}", "bad_path")
        if part.endswith((" ", ".")):
            raise PolicyDenied("Trailing dot or space in path", "bad_path")
    return "/".join(parts)


def canonical_workspace_path(root: pathlib.Path | str, path: str) -> pathlib.Path:
    """Resolve a staged package path inside ``root`` without following links.

    The first slice rejects symlinks/junctions in staged inputs (03 §3) rather
    than attempting portable link support.  Case-insensitive collisions are
    rejected on Windows semantics.
    """
    root_path = pathlib.Path(root).resolve()
    relative = _normalize_relative(path)
    target = (root_path / relative).resolve()
    try:
        target.relative_to(root_path)
    except ValueError as exc:
        raise PolicyDenied("Path escapes the workspace root", "bad_path") from exc
    probe = root_path
    seen: set[str] = set()
    for part in pathlib.PurePosixPath(relative).parts:
        parent = probe
        if parent.is_dir():
            for existing in parent.iterdir():
                if existing.name.casefold() == part.casefold() and existing.name != part:
                    raise PolicyDenied("Case-insensitive path collision", "bad_path")
        probe = probe / part
        key = str(probe).casefold()
        if key in seen:
            raise PolicyDenied("Case-insensitive path collision", "bad_path")
        seen.add(key)
        if probe.is_symlink():
            raise PolicyDenied("Symlinks/junctions are not accepted", "bad_path")
    return target


def classify_input_barrier(kind: str, payload: dict | None) -> bool:
    """Deterministic barrier classification performed before acknowledgement.

    A typed depth/engagement-only preference and an explanation request do not
    advance the steering epoch.  Every free-text input, contribution, semantic
    response, scope change or cancellation conservatively does (03 §2).
    """
    if kind == "set_engagement":
        if not isinstance(payload, dict):
            raise PolicyDenied("set_engagement requires a typed payload", "bad_schema")
        allowed = {"engagement", "explanation_depth", "preference_source"}
        unknown = set(payload) - allowed
        if unknown:
            raise PolicyDenied(f"Unexpected engagement fields: {sorted(unknown)}", "bad_schema")
        engagement = payload.get("engagement")
        depth = payload.get("explanation_depth")
        if engagement not in (None, "together", "explain_as_we_go", "delegated"):
            raise PolicyDenied("Unknown engagement value", "bad_schema")
        if depth not in (None, "brief", "standard", "detailed"):
            raise PolicyDenied("Unknown explanation depth", "bad_schema")
        return False
    if kind == "respond":
        response_kind = (payload or {}).get("kind") if isinstance(payload, dict) else None
        if response_kind == "request_explanation":
            return False
        return True
    if kind in ("new_goal", "steer", "contribute", "cancel", "chat_turn"):
        return True
    raise PolicyDenied(f"Unknown input kind {kind}", "bad_schema")


def validate_text(value: str, *, field: str = "text") -> str:
    if not isinstance(value, str):
        raise PolicyDenied(f"{field} must be a string", "bad_schema")
    if len(value) > MAX_TEXT_CHARS:
        raise PolicyDenied(f"{field} exceeds {MAX_TEXT_CHARS} characters", "oversized")
    if "\x00" in value:
        raise PolicyDenied(f"{field} contains a NUL byte", "bad_schema")
    return value


def validate_contribution(blob: bytes, *, declared_bytes: int | None = None) -> None:
    if declared_bytes is not None and declared_bytes != len(blob):
        raise PolicyDenied("Declared size does not match bytes", "bad_schema")
    if len(blob) > MAX_CONTRIBUTION_BYTES:
        raise PolicyDenied("Contribution exceeds the 1 MiB bound", "oversized")
    try:
        blob.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PolicyDenied("Contribution must be valid UTF-8 text", "bad_schema") from exc


def validate_referenced_artifacts(refs: list[str]) -> list[str]:
    if not isinstance(refs, list):
        raise PolicyDenied("referencedArtifacts must be a list", "bad_schema")
    if len(refs) > MAX_ARTIFACTS_PER_INPUT:
        raise PolicyDenied("Too many referenced artifacts", "oversized")
    for ref in refs:
        if not isinstance(ref, str) or len(ref) > 512 or "\x00" in ref:
            raise PolicyDenied("Malformed artifact reference", "bad_schema")
    return refs


def validate_artifact_visibility(store_owner_run: str, expected_run: str, artifact_id: str) -> None:
    if store_owner_run != expected_run:
        raise PolicyDenied(
            f"Artifact {artifact_id} belongs to a different run", "cross_run_artifact"
        )


_ASSIGNMENT = re.compile(r"^\s*(?P<key>[a-z][a-z0-9_]{1,40})\s*[=:]\s*(?P<value>.+?)\s*$", re.I)


def classify_free_text(text: str, *, initial: bool = False) -> dict[str, Any]:
    """A conservative deterministic interpretation of free text.

    This is a proposal with a typed shape, never authority.  Consequential
    effects still require confirmation; a clear non-consequential preference is
    recorded directly without a second ceremony (03 §2).  Endpoint language is
    classified separately so a mention, question, quotation, tentative
    suggestion or negation is not promoted into a decision.
    """
    from .interpretation import interpret_semantics

    lowered = " ".join(text.lower().split())
    depth = None
    if re.search(r"\b(brief|briefly|short|concise)\b", lowered):
        depth = "brief"
    elif re.search(r"\b(detailed|in depth|full detail|thorough)\b", lowered):
        depth = "detailed"
    engagement = None
    if re.search(r"\b(delegate|for you to|on your own|take it)\b", lowered):
        engagement = "delegated"
    elif re.search(r"\b(together|work with me)\b", lowered):
        engagement = "together"
    semantic = interpret_semantics(text, initial=initial)
    cancel = lowered in {"cancel", "stop", "stop this stage", "cancel this stage"}
    return {
        "depth": depth,
        "engagement": engagement,
        "endpointSemantics": semantic.endpoint,
        "semanticMode": semantic.mode,
        "semanticMentioned": list(semantic.mentioned),
        "semanticAmbiguous": semantic.ambiguous,
        "semanticReason": semantic.reason,
        "cancel": cancel,
        "consequential": not (depth or engagement) or semantic.endpoint is not None,
        "rawHashSource": text,
    }


def render_text_escaped(value: str) -> str:
    """UI rendering helper: never treat author/model text as trusted HTML."""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )
