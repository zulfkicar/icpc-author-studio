"""ICPC Problem Package Format audit.

Implements the checks from the ICPC subset specification:
httpC://Projects.io/problem-package-format/spec/legacy-icpc.html

The audit is deterministic and read-only. It complements the verifier: this
module answers "is this a well-formed package?" while ``verify.py`` answers
"does this package behave correctly when executed?".
"""
from __future__ import annotations

import pathlib
import re

from author_studio.packages import package_model

FILENAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,253}[a-zA-Z0-9]$")
LANGUAGES = ("en",)
LICENSES = {
    "unknown", "public domain", "cc0", "cc by", "cc by-sa", "educational", "permission",
}
KNOWN_METADATA = {
    "problem_format_version", "name", "uuid", "author", "source", "source_url",
    "license", "rights_owner", "limits", "validation", "validator_flags", "keywords", "type",
}
TEXT_SUFFIXES = {".yaml", ".yml", ".tex", ".md", ".txt", ".py", ".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".java", ".interaction", ".ini"}
LIMIT_KEYS = {
    "time_multiplier", "time_safety_margin", "memory", "output", "code",
    "compilation_time", "compilation_memory", "validation_time",
    "validation_memory", "validation_output",
}


def _check(checks: list[dict], ident: str, name: str, status: str, detail: str) -> None:
    checks.append({"id": ident, "name": name, "status": status, "detail": detail})


def _text(value) -> str:
    return " ".join(str(value or "").split())


def audit(slug: str) -> dict:
    package = package_model.load(slug)
    root = package.root
    checks: list[dict] = []

    # --- top-level structure -------------------------------------------------
    _check(checks, "problem-yaml", "problem.yaml", "pass" if (root / "problem.yaml").is_file() else "fail",
           "present" if (root / "problem.yaml").is_file() else "missing problem.yaml")
    statement_dir = package.statement_dir
    _check(checks, "statement-dir", "Problem statement directory",
           "pass" if statement_dir else "fail",
           statement_dir.name if statement_dir else "missing problem_statement/ or statement/")

    if statement_dir:
        tex = package.statement_tex
        _check(checks, "statement-file", "Problem statement file",
               "pass" if tex else "fail",
               tex.name if tex else "no problem.<language>.tex or .pdf")
        if tex and tex.suffix.lower() == ".tex":
            text = tex.read_text("utf-8", errors="replace")
            _check(checks, "problemname", "\\problemname command",
                   "pass" if "\\problemname" in text else "warn",
                   "present" if "\\problemname" in text else "missing \\problemname")

    secret = [test for test in package.tests if test.kind == "secret"]
    _check(checks, "secret-tests", "Secret test data",
           "pass" if secret else "fail", f"{len(secret)} secret input(s)")
    missing_answers = [test.relative for test in package.tests if test.answer is None]
    _check(checks, "answers", "Answer files",
           "pass" if not missing_answers else ("warn" if package.is_interactive else "fail"),
           "all tests have answers" if not missing_answers else f"missing answers for {len(missing_answers)} test(s)")

    accepted = sorted((root / "submissions" / "accepted").glob("*")) if (root / "submissions" / "accepted").is_dir() else []
    accepted = [item for item in accepted if item.is_file() and not item.name.startswith(".") and item.name != ".keep"]
    _check(checks, "accepted", "Accepted reference", "pass" if accepted else "fail",
           f"{len(accepted)} accepted source(s)")

    validator = package.input_validator_program
    _check(checks, "input-validator", "Input validator", "pass" if validator else "fail",
           validator.path.name if validator else "missing input_validators/")
    if validator:
        _check(checks, "input-validator-exit", "Input validator exit code contract",
               "pass" if _validator_returns_42(validator.path) else "warn",
               "exits 42 on valid input" if _validator_returns_42(validator.path) else "ICPC spec requires exit code 42")

    # --- metadata ------------------------------------------------------------
    metadata = package.metadata
    unknown = sorted(set(metadata) - KNOWN_METADATA - {"timelimit", "short-name", "color", "name"})
    _check(checks, "unknown-keys", "Unknown problem.yaml keys",
           "pass" if not unknown else "warn",
           "none" if not unknown else ", ".join(unknown))

    version = metadata.get("problem_format_version")
    if version is not None:
        _check(checks, "format-version", "Problem format version",
               "pass" if str(version) in ("legacy-icpc", "2025-09", "legacy") else "warn",
               str(version))

    name = metadata.get("name")
    _check(checks, "name", "Problem name", "pass" if _text(name) else "fail",
           _text(name) or "missing name")

    license_value = _text(metadata.get("license") or "unknown").lower()
    _check(checks, "license", "License", "pass" if license_value in LICENSES else "fail",
           license_value if license_value in LICENSES else f"invalid license: {license_value}")
    rights_owner = _text(metadata.get("rights_owner"))
    if license_value == "public domain":
        _check(checks, "rights-owner", "rights_owner", "pass" if not rights_owner else "fail",
               "must be absent for public domain" if rights_owner else "absent")
    elif license_value in LICENSES and license_value not in ("unknown", "public domain"):
        _check(checks, "rights-owner", "rights_owner", "pass" if rights_owner else "warn",
               rights_owner or "required when license is not unknown/public domain")

    limits = metadata.get("limits") if isinstance(metadata.get("limits"), dict) else {}
    unknown_limits = sorted(set(limits) - LIMIT_KEYS)
    _check(checks, "limits", "Limits map", "pass" if not unknown_limits else "warn",
           "memory=%s MiB" % limits.get("memory") if limits else "no limits map")
    _check(checks, "memory", "Memory limit", "pass" if limits.get("memory") else "warn",
           f"{limits.get('memory')} MiB" if limits.get("memory") else "limits.memory is not set")

    tokens = package.validation_tokens
    valid_validation = bool(tokens) and tokens[0] in ("default", "custom")
    _check(checks, "validation", "Validation mode",
           "pass" if valid_validation else "fail",
           " ".join(tokens) if tokens else "missing")
    if valid_validation and tokens[0] == "custom":
        output = package.output_validator_program
        _check(checks, "custom-validator", "Custom output validator",
               "pass" if output else "fail",
               output.path.name if output else "validation: custom requires output_validators/")
    if package.is_interactive and tokens and tokens[0] != "custom":
        _check(checks, "interactive-validation", "Interactive validation mode", "warn",
               "use validation: custom interactive for interactive problems")
    if package.is_interactive and not package.output_validator_program:
        _check(checks, "interactive-validator", "Interactive validator", "fail",
               "interactive problems require an output validator/interactor")
    interactions = package.interaction_files()
    if package.is_interactive:
        _check(checks, "interaction-files", "Sample .interaction files",
               "pass" if interactions else "warn",
               f"{len(interactions)} file(s)" if interactions else "no data/sample/*.interaction")
        for path in interactions[:3]:
            lines = [line for line in path.read_text("utf-8", errors="replace").splitlines() if line.strip()]
            valid = bool(lines) and all(line[:1] in (">", "<") for line in lines)
            _check(checks, f"interaction-{path.name}", f"Interaction format {path.name}",
                   "pass" if valid else "warn",
                   "lines begin with > or <" if valid else "every non-empty line must begin with > or <")

    # --- file hygiene --------------------------------------------------------
    bad_names = []
    bad_encoding = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".agent" in path.parts or "__pycache__" in path.parts:
            continue
        rel = path.relative_to(root).as_posix()
        if path.name not in ("build", "run") and not FILENAME_RE.match(path.name) and not path.name.startswith("."):
            bad_names.append(rel)
        if path.suffix.lower() in TEXT_SUFFIXES:
            try:
                data = path.read_bytes()
            except OSError:
                continue
            if data.startswith(b"\xef\xbb\xbf"):
                bad_encoding.append(f"{rel} (BOM)")
            elif b"\r\n" in data:
                bad_encoding.append(f"{rel} (CRLF)")
            else:
                try:
                    data.decode("utf-8")
                except UnicodeDecodeError:
                    bad_encoding.append(f"{rel} (not UTF-8)")
    _check(checks, "filenames", "File names", "pass" if not bad_names else "warn",
           "valid" if not bad_names else ", ".join(bad_names[:5]))
    _check(checks, "text-encoding", "Text encoding and line endings",
           "pass" if not bad_encoding else "warn",
           "UTF-8/LF" if not bad_encoding else ", ".join(bad_encoding[:5]))

    # --- groups --------------------------------------------------------------
    if package.groups():
        errors = package_model.group_errors(package)
        _check(checks, "groups", "Test groups", "pass" if not errors else "fail",
               "valid" if not errors else "; ".join(errors))

    errors = [f"{item['name']}: {item['detail']}" for item in checks if item["status"] == "fail"]
    warnings = [f"{item['name']}: {item['detail']}" for item in checks if item["status"] == "warn"]
    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "counts": {
            "checks": len(checks),
            "pass": sum(1 for item in checks if item["status"] == "pass"),
            "warn": len(warnings),
            "fail": len(errors),
        },
        "spec": "legacy-icpc",
        "reference": "httpC://Projects.io/problem-package-format/spec/legacy-icpc.html",
    }


def _validator_returns_42(path: pathlib.Path) -> bool:
    try:
        text = path.read_text("utf-8", errors="replace")
    except OSError:
        return False
    return "42" in text and ("exit" in text or "SystemExit" in text or "return" in text)
