"""Kattis/ICPC package model with a DOMjudge compatibility adapter.

This module reads package metadata and discovers tests/programs without running
anything. The deterministic verifier remains responsible for execution.
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass, field

import yaml

import workspace


@dataclass
class TestCase:
    name: str
    kind: str
    input: pathlib.Path
    answer: pathlib.Path | None
    group: str = ""
    relative: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "group": self.group,
            "relative": self.relative,
            "hasAnswer": bool(self.answer and self.answer.is_file()),
        }


@dataclass
class Package:
    slug: str
    root: pathlib.Path
    metadata: dict = field(default_factory=dict)
    tests: list[TestCase] = field(default_factory=list)

    @property
    def problem_type(self) -> str:
        value = self.metadata.get("type", "pass-fail")
        if isinstance(value, list):
            return ",".join(str(item) for item in value)
        return str(value)

    @property
    def is_interactive(self) -> bool:
        return "interactive" in self.problem_type

    @property
    def output_validator(self) -> pathlib.Path | None:
        folder = self.root / "output_validator"
        if not folder.is_dir():
            return None
        for name in ("run", "main.py", "validator.py", "checker.py"):
            path = folder / name
            if path.is_file():
                return path
        for path in sorted(folder.iterdir()):
            if path.is_file() and path.suffix.lower() in (".py", ".cpp", ".cc", ".cxx", ".c"):
                return path
        return None

    @property
    def input_validator(self) -> pathlib.Path | None:
        folder = self.root / "input_validators"
        if not folder.is_dir():
            return None
        for name in ("validate.py", "validator.py"):
            path = folder / name
            if path.is_file():
                return path
        for path in sorted(folder.iterdir()):
            if path.is_file() and path.suffix.lower() in (".py", ".cpp", ".cc", ".cxx", ".c"):
                return path
        return None

    def groups(self) -> dict:
        data = _yaml(self.root / "test_group.yaml")
        return data if isinstance(data, dict) else {}

    def float_tolerance(self) -> float | None:
        for key in ("float_tolerance", "floatTolerance"):
            value = self.metadata.get(key)
            if isinstance(value, (int, float)):
                return float(value)
        validation = self.metadata.get("validation")
        if isinstance(validation, str) and validation.startswith("float"):
            try:
                return float(validation.split(":", 1)[1])
            except (IndexError, ValueError):
                return 1e-6
        return None


def _yaml(path: pathlib.Path) -> dict:
    try:
        value = yaml.safe_load(path.read_text("utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, yaml.YAMLError):
        return {}


def discover_tests(root: pathlib.Path) -> list[TestCase]:
    tests: list[TestCase] = []
    for kind in ("sample", "secret"):
        folder = root / "data" / kind
        if not folder.is_dir():
            continue
        for input_path in sorted(folder.rglob("*.in")):
            if input_path.name.startswith("."):
                continue
            answer = input_path.with_suffix(".ans")
            relative = input_path.relative_to(root).as_posix()
            group = input_path.parent.relative_to(folder).as_posix()
            if group == ".":
                group = ""
            tests.append(TestCase(
                name=f"{kind}/{relative[len('data/' + kind + '/'):]}",
                kind=kind,
                input=input_path,
                answer=answer if answer.is_file() else None,
                group=group,
                relative=relative,
            ))
    return tests


def load(slug: str) -> Package:
    root = workspace.ws_path(slug)
    metadata = _yaml(root / "problem.yaml")
    # DOMjudge metadata is a compatibility fallback.
    ini = root / "domjudge-problem.ini"
    if ini.is_file():
        for line in ini.read_text("utf-8", errors="replace").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, value = line.split("=", 1)
                metadata.setdefault(key.strip(), value.strip().strip('"'))
    return Package(slug=slug, root=root, metadata=metadata, tests=discover_tests(root))


def group_errors(package: Package) -> list[str]:
    errors = []
    groups = package.groups()
    tests = package.tests
    names = {test.group for test in tests if test.kind == "secret"}
    if groups:
        for name, config in groups.items():
            if not isinstance(config, dict):
                errors.append(f"group {name} is not a map")
                continue
            depends = config.get("depends", [])
            if isinstance(depends, str):
                depends = [depends]
            for dep in depends or []:
                if dep not in groups:
                    errors.append(f"group {name} depends on unknown group {dep}")
    # Cycles are detected over declared groups.
    graph = {}
    for name, config in groups.items() if isinstance(groups, dict) else []:
        deps = config.get("depends", []) if isinstance(config, dict) else []
        if isinstance(deps, str):
            deps = [deps]
        graph[name] = [str(item) for item in (deps or [])]
    visiting, done = set(), set()

    def visit(node):
        if node in visiting:
            return True
        if node in done:
            return False
        visiting.add(node)
        for dep in graph.get(node, []):
            if visit(dep):
                return True
        visiting.remove(node)
        done.add(node)
        return False

    if any(visit(node) for node in graph):
        errors.append("test group dependency cycle")
    return errors
