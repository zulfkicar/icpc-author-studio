"""Validate plan links, traceability and unchanged audited runtime source."""
from __future__ import annotations

import hashlib
import json
import pathlib
import re

PLAN = pathlib.Path(__file__).resolve().parent.parent
ROOT = PLAN.parents[2]


def main():
    files = list(PLAN.glob("*.md")) + [ROOT / path for path in (
        "README.md", "docs/MASTER-PLAN.md", "docs/IMPLEMENTATION-STATUS.md",
        "docs/DOMAIN-DEPTH-PLAN.md", "docs/READINESS.md",
    )]
    errors = []
    links = 0
    for path in files:
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text("utf-8")):
            if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
                continue
            target = target.split("#", 1)[0]
            if target:
                links += 1
                if not (path.parent / target).resolve().exists():
                    errors.append(f"Missing link: {path.relative_to(ROOT)} -> {target}")

    audit = (PLAN / "01-AUDIT.md").read_text("utf-8")
    backlog = (PLAN / "04-BACKLOG.md").read_text("utf-8")
    findings = re.findall(r"^\| (A\d{2}) \|", audit, re.M)
    tasks = re.findall(r"^\| (T\d{2}) /", backlog, re.M)
    if findings != [f"A{i:02}" for i in range(1, 38)]:
        errors.append("Finding definitions must be unique and continuous A01–A37")
    if tasks != [f"T{i:02}" for i in range(1, 57)]:
        errors.append("Task definitions must be unique and continuous T01–T56")

    ranges = re.findall(r"A(\d{2})[–-]A(\d{2})", backlog)
    for finding in findings:
        if finding not in backlog and not any(int(a) <= int(finding[1:]) <= int(b) for a, b in ranges):
            errors.append("Finding missing from backlog: " + finding)

    # Dependencies are the fourth cell of each task row. Reject missing tasks,
    # self-dependencies and cycles, including compact ranges such as T34–T39.
    graph = {}
    for line in backlog.splitlines():
        match = re.match(r"^\| (T\d{2}) /", line)
        if not match:
            continue
        task = match[1]
        dependency_cell = line.split("|")[3]
        dependencies = set(re.findall(r"T\d{2}", dependency_cell))
        for first, last in re.findall(r"T(\d{2})[–-]T(\d{2})", dependency_cell):
            dependencies.update(f"T{i:02}" for i in range(int(first), int(last) + 1))
        graph[task] = dependencies
        for dependency in dependencies:
            if dependency not in tasks or dependency == task:
                errors.append(f"Invalid dependency: {task} -> {dependency}")

    done = set()

    def visit(task, visiting):
        if task in visiting:
            errors.append("Dependency cycle: " + " -> ".join((*visiting, task)))
            return
        if task in done:
            return
        for dependency in graph.get(task, set()):
            visit(dependency, (*visiting, task))
        done.add(task)

    for task in graph:
        visit(task, ())

    inventory = json.loads((PLAN / "evidence/source-inventory.json").read_text("utf-8"))
    coverage = json.loads((PLAN / "evidence/audit-coverage.json").read_text("utf-8"))
    if {r["path"] for r in inventory["files"]} != {r["path"] for r in coverage["files"]}:
        errors.append("Per-file audit coverage differs from baseline inventory")
    checked_source = 0
    for row in inventory["files"]:
        if row["category"] not in ("runtime", "ui", "prompt", "skill", "operations", "evaluation", "test", "template", "vendor"):
            continue
        checked_source += 1
        actual = hashlib.sha256((ROOT / row["path"]).read_bytes()).hexdigest()
        if actual != row["sha256"]:
            errors.append("Audited non-document source changed: " + row["path"])
    for row in coverage["files"]:
        for task in row["plannedTasks"]:
            if task not in tasks:
                errors.append("Unknown coverage task: " + task)

    payload = {
        "date": "2026-11-10", "markdownFilesChecked": len(files),
        "localLinksChecked": links, "findings": len(findings),
        "p0Findings": len(re.findall(r"^\| A\d{2} \| P0", audit, re.M)),
        "implementationTasks": len(tasks), "trackedFilesCovered": len(coverage["files"]),
        "nonDocumentSourceHashesChecked": checked_source,
        "dependencyGraphAcyclic": not any("cycle" in error for error in errors),
        "errors": errors,
    }
    (PLAN / "evidence/plan-validation.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
