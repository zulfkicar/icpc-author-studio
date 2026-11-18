"""Offline audit probes. Uses synthetic temporary files and mocks, never a provider.

These describe current behavior, not desired regression-test expectations.
Run from any cwd with: python -B <absolute path to this file>
"""
from __future__ import annotations

import contextlib
import json
import os
import pathlib
import re
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from author_studio.classic import agent
from workers import isolate_worker
from author_studio.judging import judge0_adapter
from author_studio import mcp_consent
from author_studio import mcp_server
from author_studio.classic import skill_registry
from author_studio.classic import agent_state
from author_studio.judging import verify
from author_studio import winutil
from author_studio.packages import workspace


def main():
    results = []
    with tempfile.TemporaryDirectory(prefix="icpc-audit-", dir=pathlib.Path(__file__).parent) as directory:
        base = pathlib.Path(directory)
        assert base.resolve().parent == pathlib.Path(__file__).resolve().parent
        root = base / "audit-problem"
        (root / "data/secret").mkdir(parents=True)
        (root / "data/secret/sentinel.in").write_text("SYNTHETIC_AUDIT_SENTINEL", encoding="utf-8")
        (root / "data/valid_output").mkdir(parents=True)
        (root / "data/valid_output/example.out").write_text("before", encoding="utf-8")
        with patch.object(workspace, "WORKSPACES", base):
            consent = {"enabled": True, "tools": {"read_file": True}, "roots": ["."]}
            for name, fn in (
                ("mcp-path-alias", lambda: mcp_server.call("audit-problem", "read_file", {"path": "./data/secret/sentinel.in"}, consent)),
                ("agent-path-alias", lambda: agent._dispatch("audit-problem", "read_file", {"path": "data/./secret/sentinel.in"}, lambda *_: None)),
            ):
                try:
                    value = fn()
                    results.append({"probe": name, "syntheticProtectedContentReturned": value.get("content") == "SYNTHETIC_AUDIT_SENTINEL"})
                except Exception as exc:
                    results.append({"probe": name, "blocked": type(exc).__name__})

            before = workspace.snapshot_hash("audit-problem")
            (root / "data/valid_output/example.out").write_text("after", encoding="utf-8")
            after = workspace.snapshot_hash("audit-problem")
            results.append({"probe": "output-fixture-snapshot", "changedOutFixtureChangesSnapshot": before != after})

            workspace._write_json(root / ".agent/state.json", {"limitsMeasured": True, "measuredLimits": {"sourceRevision": "old"}})
            workspace.write_text("audit-problem", "submissions/accepted/reference.py", "print(0)\n", source="test")
            results.append({"probe": "measurement-invalidation", "limitsMeasuredAfterReferenceChange": workspace.state("audit-problem").get("limitsMeasured")})

            (root / ".agent/mcp.json").write_text("{broken", encoding="utf-8")
            result = mcp_consent.state("audit-problem")
            results.append({"probe": "corrupt-consent", "enabled": result.get("enabled"), "allToolsEnabled": all(result.get("tools", {}).values())})

            package = SimpleNamespace(root=root, is_interactive=True, problem_type="interactive", groups=lambda: {})
            test = {"relative": "data/secret/sentinel.in", "kind": "secret", "group": ""}
            spec = {"status": "pass", "counts": {"pass": 1, "checks": 1, "warn": 0}, "warnings": [], "errors": []}
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(verify, "_tests", return_value=[test, {**test, "relative": "data/secret/second.in"}]))
                stack.enter_context(patch.object(verify, "_solutions", return_value=[{"path": "reference.py", "kind": "accepted"}, {"path": "wrong.py", "kind": "negative"}]))
                stack.enter_context(patch.object(verify, "_validator", return_value=object()))
                stack.enter_context(patch.object(verify, "_structure", return_value=[]))
                stack.enter_context(patch.object(verify.package_model, "load", return_value=package))
                stack.enter_context(patch.object(verify.package_model, "group_errors", return_value=[]))
                stack.enter_context(patch.object(verify.verification_modes, "interactive_selftest", return_value={"status": "pass", "detail": "synthetic selftest"}))
                stack.enter_context(patch.object(verify.icpc_spec, "audit", return_value=spec))
                save = stack.enter_context(patch.object(workspace, "set_report"))
                statement = stack.enter_context(patch.object(verify, "_statement"))
                result = verify.verify("audit-problem")
                results.append({"probe": "interactive-control-flow", "method": "mocked prerequisite checks, real verify dispatch", "status": result["status"], "hasSnapshot": "snapshot" in result, "reportPersisted": save.called, "statementChecked": statement.called, "negativeStatuses": [r["status"] for r in result["negative"]]})

    source = (ROOT / "web/app.js").read_text("utf-8")
    declarations = [i for i, line in enumerate(source.splitlines(), 1) if re.match(r"function renderToolResult\(", line)]
    results.append({"probe": "duplicate-tool-renderer", "declarationLines": declarations})

    with patch.dict(os.environ, {}, clear=True):
        results.append({"probe": "native-execution-default", "remoteExecutorRequiredByDefault": winutil._require_local_or_executor()})

    default_limits = isolate_worker._limits({})
    changed_limits = isolate_worker._limits({"processes": 1, "stack": 1, "openFiles": 1})
    results.append({"probe": "worker-limit-controls", "processStackAndOpenFileOverridesChangeParsedLimits": default_limits != changed_limits, "parsedFields": sorted(default_limits)})

    with patch.object(judge0_adapter, "_request", return_value={"status": {"id": 1, "description": "In Queue"}}):
        result = judge0_adapter.quick_run("print(0)", "py", base_url="http://invalid.audit")
        results.append({"probe": "queued-judge0-result", "status": result["status"], "ok": result["ok"]})

    first = ["constraints"]
    a, _ = skill_registry.activate(first, "test-design")
    b, _ = skill_registry.activate(first, "validator-design")
    merged = agent_state.merge_skills({n: True for n in a}, {n: True for n in b})
    results.append({"probe": "parallel-skill-invariant", "method": "two loads from same state followed by real reducer", "activeCount": sum(merged.values()), "configuredMaximum": skill_registry.MAX_ACTIVE})

    payload = {"date": "2026-11-10", "scope": "Offline source-level and synthetic behavior probes. No live sandbox or provider assurance.", "results": results}
    output = pathlib.Path(__file__).with_name("audit-probes.json")
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
