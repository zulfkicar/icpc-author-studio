"""Kattis/ICPC package model with a DOMjudge compatibility adapter.

References:
- httpC://Projects.io/problem-package-format/spec/legacy-icpc.html (ICPC subset)
- httpC://Projects.github.io/problem-package-format/ (2025-09 draft)

The model reads metadata and discovers validator programs without running
anything. The deterministic verifier remains responsible for execution.

Both spellings are supported because the ICPC subset uses ``output_validators/``
while the newer 2025-09 draft uses ``output_validator/``; ``problem_statement/``
and ``statement/`` are both accepted for the same reason.
"""
from __future__ import annotations

import pathlib
import shlex
from dataclasses import dataclass, field

import yaml

import workspace

PROGRAM_SUFFIXES = (".cpp", ".cc", ".cxx", ".c", ".py", ".java")
VALIDATION_PREFIXES = ("default", "custom")
GROUPS_FILES = ("test_group.yaml", "testdata.yaml", "data/testdata.yaml", "groups.yaml")


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
class Program:
    """A validator/interactor program and the contract used to invoke it."""

    name: str
    path: pathlib.Path
    directory: pathlib.Path
    kind: str
    contract: str
    flags: list[str] = field(default_factory=list)
    run_script: pathlib.Path | None = None
    build_script: pathlib.Path | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "path": self.path.relative_to(self.directory).as_posix() if self.path.is_relative_to(self.directory) else str(self.path),
            "kind": self.kind,
            "contract": self.contract,
            "flags": list(self.flags),
            "runScript": bool(self.run_script),
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
    def validation_tokens(self) -> list[str]:
        raw = self.metadata.get("validation", "default")
        if isinstance(raw, (list, tuple)):
            return [str(item).lower() for item in raw]
        return [token.lower() for token in str(raw).split() if token]

    @property
    def validation(self) -> str:
        tokens = self.validation_tokens
        return tokens[0] if tokens else "default"

    @property
    def is_custom(self) -> bool:
        return self.validation == "custom"

    @property
    def is_interactive(self) -> bool:
        return "interactive" in self.validation_tokens or "interactive" in self.problem_type

    @property
    def validator_flags(self) -> list[str]:
        raw = self.metadata.get("validator_flags") or self.metadata.get("validatorFlags") or ""
        if not raw:
            for name in ("data/testdata.yaml", "testdata.yaml"):
                data = _yaml(self.root / name)
                if data.get("output_validator_flags"):
                    raw = data.get("output_validator_flags")
                    break
        if isinstance(raw, (list, tuple)):
            return [str(item) for item in raw]
        try:
            return shlex.split(str(raw))
        except ValueError:
            return []

    @property
    def statement_dir(self) -> pathlib.Path | None:
        for name in ("problem_statement", "statement"):
            path = self.root / name
            if path.is_dir():
                return path
        return None

    @property
    def statement_tex(self) -> pathlib.Path | None:
        folder = self.statement_dir
        if folder is None:
            return None
        for name in ("problem.en.tex", "problem.tex"):
            if (folder / name).is_file():
                return folder / name
        for path in sorted(folder.glob("problem.*.tex")):
            return path
        return None

    def _program_from(self, path: pathlib.Path, kind: str) -> Program | None:
        directory = path if path.is_dir() else path.parent
        run_script = directory / "run" if directory.is_dir() else None
        build_script = directory / "build" if directory.is_dir() else None
        candidate: pathlib.Path | None = None
        if path.is_file():
            if path.suffix.lower() in PROGRAM_SUFFIXES or path.name == "run":
                candidate = path
        elif path.is_dir():
            if run_script and run_script.is_file():
                candidate = run_script
            else:
                preferred = ("main.cpp", "validator.cpp", "checker.cpp", "interactor.cpp", "main.py", "validator.py", "checker.py", "interactor.py")
                for name in preferred:
                    item = path / name
                    if item.is_file() and item.suffix.lower() in PROGRAM_SUFFIXES:
                        candidate = item
                        break
                if candidate is None:
                    for item in sorted(path.iterdir()):
                        if item.is_file() and item.suffix.lower() in PROGRAM_SUFFIXES:
                            candidate = item
                            break
        if candidate is None:
            return None
        contract = _detect_contract(candidate, run_script)
        return Program(
            name=candidate.stem if candidate.name != "run" else directory.name,
            path=candidate,
            directory=directory,
            kind=kind,
            contract=contract,
            flags=self.validator_flags if kind == "output" else [],
            run_script=run_script if (run_script and run_script.is_file()) else None,
            build_script=build_script if (build_script and build_script.is_file()) else None,
        )

    def _discover_folder(self, names: tuple[str, ...], kind: str) -> Program | None:
        for name in names:
            folder = self.root / name
            if not folder.is_dir():
                continue
            for item in sorted(folder.iterdir()):
                if item.name.startswith(".") or item.name == "__pycache__":
                    continue
                if kind in ("output", "input") and "transcript" in item.name.lower():
                    continue
                program = self._program_from(item, kind)
                if program is not None:
                    return program
        return None

    @property
    def output_validator_program(self) -> Program | None:
        return self._discover_folder(("output_validators", "output_validator"), "output")

    @property
    def transcript_checker_program(self) -> Program | None:
        for folder_name in ("output_validators", "output_validator"):
            folder = self.root / folder_name
            if not folder.is_dir():
                continue
            for item in sorted(folder.iterdir()):
                if "transcript" not in item.name.lower():
                    continue
                program = self._program_from(item, "transcript")
                if program is not None:
                    return program
        return None

    @property
    def input_validator_program(self) -> Program | None:
        return self._discover_folder(("input_validators", "input_format_validators"), "input")

    @property
    def output_validator(self) -> pathlib.Path | None:
        """Compatibility accessor used by the UI and older tests."""
        program = self.output_validator_program
        return program.path if program else None

    @property
    def input_validator(self) -> pathlib.Path | None:
        program = self.input_validator_program
        return program.path if program else None

    def groups(self) -> dict:
        for name in GROUPS_FILES:
            data = _yaml(self.root / name)
            if not data:
                continue
            # Kattis testdata.yaml uses scalar settings; only a map-of-maps is
            # a group declaration.
            if name.endswith("testdata.yaml") and any(not isinstance(value, dict) for value in data.values()):
                continue
            if all(isinstance(value, dict) for value in data.values()):
                return data
        return {}

    def interaction_files(self) -> list[pathlib.Path]:
        folder = self.root / "data" / "sample"
        if not folder.is_dir():
            return []
        return sorted(folder.glob("*.interaction"))

    def float_tolerance(self) -> float | None:
        for key in ("float_tolerance", "floatTolerance"):
            value = self.metadata.get(key)
            if isinstance(value, (int, float)):
                return float(value)
        for token in self.validation_tokens:
            if token.startswith("float"):
                try:
                    return float(token.split(":", 1)[1])
                except (IndexError, ValueError):
                    return 1e-6
        return None


def _detect_contract(path: pathlib.Path, run_script: pathlib.Path | None) -> str:
    if run_script is not None and run_script.is_file():
        return "spec"
    if path.suffix.lower() not in (".cpp", ".cc", ".cxx", ".c", ".h", ".hpp"):
        return "spec"
    try:
        text = path.read_text("utf-8", errors="replace")[:512_000]
    except OSError:
        return "spec"
    if "registerInteraction" in text:
        return "testlib-interactive"
    if "registerTestlibCmd" in text:
        return "testlib"
    return "spec"


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


def _dependencies(config: dict) -> list[str]:
    raw = config.get("depends", config.get("dependencies", []))
    if isinstance(raw, str):
        raw = [raw]
    return [str(item) for item in (raw or [])]


def group_errors(package: Package) -> list[str]:
    errors = []
    groups = package.groups()
    if not isinstance(groups, dict):
        return ["test groups must be a map"]
    for name, config in groups.items():
        if not isinstance(config, dict):
            errors.append(f"group {name} is not a map")
            continue
        for dep in _dependencies(config):
            if dep not in groups:
                errors.append(f"group {name} depends on unknown group {dep}")
        points = config.get("points")
        if points is not None:
            try:
                if float(points) < 0:
                    errors.append(f"group {name} has negative points")
            except (TypeError, ValueError):
                errors.append(f"group {name} has non-numeric points")
    graph = {name: _dependencies(config) for name, config in groups.items() if isinstance(config, dict)}
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
    # Every declared group should have at least one test when groups are used.
    if groups:
        present = {test.group for test in package.tests if test.kind == "secret"}
        for name in groups:
            if name not in present:
                errors.append(f"group {name} has no secret tests")
    return errors
