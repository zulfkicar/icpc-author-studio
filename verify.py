"""Deterministic DOMjudge package checks.

The agent may *say* anything. This module is the part that actually compiles
solutions, runs the input validator, compares reference output with answers,
tests negative solutions and builds the statement. Its report is the evidence
the UI shows before export is allowed.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import shutil
import sys
import time
import uuid
import zipfile

from config import TEMPLATES
import winutil
import workspace

SOLUTION_EXT = {".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".c": "c", ".py": "py", ".java": "java"}
NEGATIVE_DIRS = ("wrong_answer", "time_limit_exceeded", "wrong_solutions")
OUTPUT_CAP = 8 * 1024 * 1024
VERIFY_BUDGET_SECONDS = 15 * 60


def _which(name: str) -> str | None:
    return shutil.which(name)


def _run(argv: list[str], cwd: pathlib.Path, data: bytes = b"", timeout: float = 10.0, env: dict | None = None) -> dict:
    run_env = winutil.python_env()
    if env:
        run_env.update(env)
    result = winutil.run_captured(argv, cwd, data=data, timeout=timeout, env=run_env)
    result["stdout"] = result["stdout"][:OUTPUT_CAP]
    result["stderr"] = result["stderr"][:OUTPUT_CAP]
    return result


def _new_build_dir(slug: str) -> pathlib.Path:
    root = workspace.ws_path(slug) / ".agent" / "build"
    root.mkdir(parents=True, exist_ok=True)
    run = root / f"run-{uuid.uuid4().hex[:8]}"
    run.mkdir()
    try:
        old_runs = sorted(root.glob("run-*"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in old_runs[5:]:
            shutil.rmtree(old, ignore_errors=True)
    except OSError:
        pass
    return run


def _read_meta(slug: str) -> dict:
    root = workspace.ws_path(slug)
    yaml_text = ""
    try:
        yaml_text = (root / "problem.yaml").read_text("utf-8")
    except OSError:
        pass
    ini_text = ""
    try:
        ini_text = (root / "domjudge-problem.ini").read_text("utf-8")
    except OSError:
        pass

    def ini_value(key: str) -> str | None:
        match = re.search(rf"^\s*{re.escape(key)}\s*=\s*[\"']?([^\"'\r\n]+)", ini_text, re.M)
        return match.group(1).strip() if match else None

    name = ini_value("name")
    if not name:
        match = re.search(r"^\s*name\s*:\s*[\"']?([^\"'\r\n]+)", yaml_text, re.M)
        name = match.group(1).strip() if match else None
    memory = None
    match = re.search(r"limits\s*:\s*(?:\n[ \t]+[^\n]*)*?\n?[ \t]+memory\s*:\s*(\d+)", yaml_text)
    if match:
        memory = int(match.group(1))
    validation = None
    match = re.search(r"^\s*validation\s*:\s*[\"']?([^\"'\r\n]+)", yaml_text, re.M)
    if match:
        validation = match.group(1).strip()
    timelimit_raw = ini_value("timelimit")
    try:
        timelimit = float(timelimit_raw) if timelimit_raw else 2.0
    except ValueError:
        timelimit = 2.0
    return {
        "name": name,
        "memoryMb": memory,
        "validation": validation,
        "timeLimitSeconds": timelimit,
        "hasTimeLimit": bool(timelimit_raw),
    }


def _solutions(slug: str) -> list[dict]:
    root = workspace.ws_path(slug)
    out = []
    for kind, depth in (("accepted", 0), ("negative", 1)):
        if kind == "accepted":
            folders = [root / "submissions" / "accepted"]
        else:
            folders = [root / "submissions" / d for d in NEGATIVE_DIRS]
        if not folders or not any(f.is_dir() for f in folders):
            continue
        for folder in folders:
            if not folder.is_dir():
                continue
            for path in sorted(folder.iterdir()):
                if not path.is_file() or path.name.startswith(".") or path.name.startswith("README"):
                    continue
                language = SOLUTION_EXT.get(path.suffix.lower())
                if not language:
                    continue
                out.append({
                    "path": path.relative_to(root).as_posix(),
                    "absolute": path,
                    "language": language,
                    "kind": kind,
                })
    return out


def _compile(slug: str, solution: dict, build: pathlib.Path) -> dict:
    key = hashlib.sha256(str(solution["absolute"]).encode()).hexdigest()[:10]
    stem = re.sub(r"[^A-Za-z0-9_]", "_", solution["absolute"].stem)
    language = solution["language"]
    if language in ("cpp", "c"):
        compiler = _which("g++" if language == "cpp" else "gcc")
        if not compiler:
            return {"ok": False, "error": f"{'g++' if language == 'cpp' else 'gcc'} was not found on PATH"}
        exe = build / f"{stem}_{key}.exe"
        std = "-std=gnu++20" if language == "cpp" else "-std=gnu11"
        result = _run([compiler, "-O2", std, "-pipe", "-o", str(exe), str(solution["absolute"])], cwd=build, timeout=90)
        if not result["ok"] or result["returncode"] != 0:
            return {"ok": False, "error": result["stderr"].decode("utf-8", "replace")[-4000:], "command": [compiler, std]}
        return {"ok": True, "argv": [str(exe)]}
    if language == "py":
        return {"ok": True, "argv": [sys.executable, str(solution["absolute"])]}
    if language == "java":
        javac = _which("javac")
        java = _which("java")
        if not javac or not java:
            return {"ok": False, "error": "javac/java were not found on PATH"}
        classes = build / f"classes_{key}"
        classes.mkdir(exist_ok=True)
        result = _run([javac, "-encoding", "UTF-8", "-d", str(classes), str(solution["absolute"])], cwd=build, timeout=90)
        if not result["ok"] or result["returncode"] != 0:
            return {"ok": False, "error": result["stderr"].decode("utf-8", "replace")[-4000:]}
        class_name = solution["absolute"].stem
        return {"ok": True, "argv": [java, "-cp", str(classes), class_name]}
    return {"ok": False, "error": "Unsupported language"}


def _tokens(value: bytes) -> list[bytes]:
    return value.split()


def _compare(actual: bytes, expected: bytes) -> bool:
    return _tokens(actual) == _tokens(expected)


def _verdict(result: dict, expected: bytes | None, time_limit: float) -> str:
    if result["timedOut"]:
        return "TLE"
    if not result["ok"]:
        return "RE"
    if result["returncode"] != 0:
        return "RE"
    if expected is None:
        return "NO_ANSWER"
    return "AC" if _compare(result["stdout"], expected) else "WA"


def _tests(slug: str) -> list[dict]:
    root = workspace.ws_path(slug)
    tests = []
    for kind in ("sample", "secret"):
        folder = root / "data" / kind
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.in")):
            if path.name.startswith("."):
                continue
            answer = path.with_suffix(".ans")
            tests.append({
                "name": f"{kind}/{path.name}",
                "kind": kind,
                "input": path,
                "answer": answer,
                "relative": path.relative_to(root).as_posix(),
            })
    return tests


def _validator(slug: str) -> pathlib.Path | None:
    root = workspace.ws_path(slug)
    for rel in ("input_validators/validate.py", "input_validators/validator.py"):
        path = root / rel
        if path.is_file():
            return path
    folder = root / "input_validators"
    if folder.is_dir():
        for path in sorted(folder.glob("*.py")):
            if not path.name.startswith("."):
                return path
    return None


def _structure(slug: str, tests: list[dict], accepted: list[dict], negative: list[dict], validator: pathlib.Path | None) -> list[dict]:
    root = workspace.ws_path(slug)
    checks = []

    def check(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    for rel in ("problem.yaml", "domjudge-problem.ini", "problem_statement/problem.en.tex"):
        check(f"File {rel}", "pass" if (root / rel).is_file() else "fail",
              "present" if (root / rel).is_file() else "missing")
    meta = _read_meta(slug)
    check("Problem name", "pass" if meta.get("name") else "fail",
          meta.get("name") or "no name in problem.yaml or domjudge-problem.ini")
    check("Memory limit", "pass" if meta.get("memoryMb") else "fail",
          f"{meta.get('memoryMb')} MiB" if meta.get("memoryMb") else "limits.memory is missing from problem.yaml")
    check("Time limit", "pass" if meta.get("hasTimeLimit") else "fail",
          f"{meta.get('timeLimitSeconds')} s" if meta.get("hasTimeLimit") else "timelimit is missing from domjudge-problem.ini")
    check("At least one sample test", "pass" if any(t["kind"] == "sample" for t in tests) else "fail",
          f"{sum(1 for t in tests if t['kind'] == 'sample')} sample input(s)")
    secret = sum(1 for t in tests if t["kind"] == "secret")
    check("At least one secret test", "pass" if secret else "fail", f"{secret} secret input(s)")
    check("Reference solution", "pass" if accepted else "fail",
          f"{len(accepted)} accepted source(s)")
    check("Negative solutions", "pass" if negative else "fail",
          f"{len(negative)} negative source(s)")
    check("Input validator", "pass" if validator else "fail",
          "present" if validator else "missing input_validators/validate.py")
    return checks


def _statement(slug: str) -> dict:
    root = workspace.ws_path(slug)
    tex = root / "problem_statement" / "problem.en.tex"
    if not tex.is_file():
        return {"status": "fail", "detail": "problem_statement/problem.en.tex is missing"}
    pdflatex = _which("pdflatex")
    if not pdflatex:
        return {"status": "skip", "detail": "pdflatex was not found; statement compile was not checked"}
    env = {"TEXINPUTS": str(TEMPLATES) + os.pathsep + os.environ.get("TEXINPUTS", "")}
    first = _run([pdflatex, "-interaction=nonstopmode", "-halt-on-error", "problem.en.tex"], cwd=tex.parent, timeout=180, env=env)
    if not first["ok"] or first["returncode"] != 0:
        tail = first["stderr"].decode("utf-8", "replace")[-3000:]
        log = tex.parent / "problem.en.log"
        if log.is_file():
            tail = log.read_text("utf-8", errors="replace")[-3000:]
        return {"status": "fail", "detail": "pdflatex failed\n" + tail}
    second = _run([pdflatex, "-interaction=nonstopmode", "-halt-on-error", "problem.en.tex"], cwd=tex.parent, timeout=180, env=env)
    pdf = tex.parent / "problem.en.pdf"
    if not second["ok"] or second["returncode"] != 0 or not pdf.is_file():
        return {"status": "fail", "detail": "second pdflatex pass failed"}
    shutil.copyfile(pdf, root / "problem.pdf")
    for suffix in (".aux", ".log", ".out", ".toc", ".synctex.gz"):
        artifact = tex.parent / ("problem.en" + suffix)
        if artifact.is_file():
            artifact.unlink()
    return {"status": "pass", "detail": "problem.pdf compiled"}


def _check_cancel(cancelled, deadline: float | None = None) -> None:
    if cancelled is not None and cancelled():
        raise RuntimeError("Cancelled by user")
    if deadline is not None and time.monotonic() > deadline:
        raise RuntimeError("Verification exceeded its 15-minute budget")


def build_answers(slug: str, cancelled=None) -> dict:
    winutil.prepare()
    deadline = time.monotonic() + VERIFY_BUDGET_SECONDS
    _check_cancel(cancelled, deadline)
    tests = _tests(slug)
    accepted = _solutions(slug)
    accepted = [s for s in accepted if s["kind"] == "accepted"]
    if not accepted:
        raise ValueError("Add at least one reference solution in submissions/accepted")
    meta = _read_meta(slug)
    build_root = _new_build_dir(slug)
    compiled = {s["path"]: _compile(slug, s, build_root) for s in accepted}
    broken = [{"path": p, "error": c.get("error", "compile failed")} for p, c in compiled.items() if not c["ok"]]
    if broken:
        return {"ok": False, "errors": broken, "written": 0}
    written = 0
    reports = []
    for test in tests:
        _check_cancel(cancelled, deadline)
        data = test["input"].read_bytes()
        outputs = []
        for solution in accepted:
            result = _run(compiled[solution["path"]]["argv"], cwd=workspace.ws_path(slug), data=data,
                          timeout=meta["timeLimitSeconds"] + 2.0)
            if result["timedOut"] or not result["ok"] or result["returncode"] != 0:
                return {"ok": False, "errors": [{"path": solution["path"], "error": "Reference failed on " + test["relative"]}], "written": written}
            outputs.append((solution["path"], result["stdout"]))
        if len({tuple(_tokens(o)) for _, o in outputs}) > 1:
            reports.append({"test": test["relative"], "status": "reference_disagreement",
                            "solutions": [p for p, _ in outputs]})
            continue
        workspace.write_text(slug, test["answer"].relative_to(workspace.ws_path(slug)).as_posix(),
                             outputs[0][1].decode("utf-8", "replace"), source="verify")
        written += 1
    return {"ok": not reports, "written": written, "tests": len(tests), "disagreements": reports}


def verify(slug: str, write_answers: bool = False, cancelled=None) -> dict:
    winutil.prepare()
    deadline = time.monotonic() + VERIFY_BUDGET_SECONDS
    _check_cancel(cancelled, deadline)
    root = workspace.ws_path(slug)
    meta = _read_meta(slug)
    tests = _tests(slug)
    solutions = _solutions(slug)
    accepted = [s for s in solutions if s["kind"] == "accepted"]
    negative = [s for s in solutions if s["kind"] == "negative"]
    validator = _validator(slug)
    checks = _structure(slug, tests, accepted, negative, validator)
    errors: list[str] = []
    warnings: list[str] = []

    for check in checks:
        if check["status"] == "fail":
            errors.append(f"{check['name']}: {check['detail']}")
        elif check["status"] == "warn":
            warnings.append(f"{check['name']}: {check['detail']}")

    built = {"ok": False, "written": 0, "errors": [], "disagreements": []}
    if accepted and write_answers:
        built = build_answers(slug, cancelled=cancelled)
        tests = _tests(slug)
        if not built["ok"]:
            errors.append("Answer generation failed")
            warnings.extend(str(e) for e in built.get("errors", []))
            warnings.extend(f"Reference disagreement on {d['test']}" for d in built.get("disagreements", []))

    compiled = {}
    build_root = _new_build_dir(slug)
    for solution in accepted + negative:
        _check_cancel(cancelled, deadline)
        compiled[solution["path"]] = _compile(slug, solution, build_root)

    validator_results = []
    if validator:
        for test in tests:
            _check_cancel(cancelled, deadline)
            result = _run([sys.executable, str(validator)], cwd=root, data=test["input"].read_bytes(), timeout=15)
            valid = result["ok"] and result["returncode"] in (0, 42)
            validator_results.append({
                "test": test["relative"],
                "valid": valid,
                "exitCode": result["returncode"],
                "stderr": result["stderr"].decode("utf-8", "replace")[-800:],
            })
        invalid = [r for r in validator_results if not r["valid"]]
        checks.append({
            "name": "Validator results",
            "status": "pass" if not invalid else "fail",
            "detail": f"{len(validator_results) - len(invalid)}/{len(validator_results)} inputs valid",
        })
        if invalid:
            errors.append("Input validator rejected " + ", ".join(r["test"] for r in invalid))

    test_results = []
    answer_mismatch = []
    missing_answer = []
    for test in tests:
        _check_cancel(cancelled, deadline)
        expected = test["answer"].read_bytes() if test["answer"].is_file() else None
        if expected is None:
            missing_answer.append(test["relative"])
        row = {"test": test["relative"], "kind": test["kind"], "solutions": []}
        for solution in accepted:
            comp = compiled[solution["path"]]
            if not comp["ok"]:
                row["solutions"].append({"path": solution["path"], "verdict": "CE", "error": comp.get("error", "")[-1000:]})
                continue
            result = _run(comp["argv"], cwd=root, data=test["input"].read_bytes(),
                          timeout=meta["timeLimitSeconds"] + 0.5)
            verdict = _verdict(result, expected, meta["timeLimitSeconds"])
            row["solutions"].append({
                "path": solution["path"], "verdict": verdict, "ms": round(result["ms"], 1),
                "stderr": result["stderr"].decode("utf-8", "replace")[-500:] if verdict != "AC" else "",
            })
            if verdict not in ("AC",):
                answer_mismatch.append({"test": test["relative"], "path": solution["path"], "verdict": verdict})
        test_results.append(row)
    if missing_answer:
        errors.append("Missing answer files for: " + ", ".join(missing_answer) + ". Run Build answers.")
    if answer_mismatch:
        errors.append(f"{len(answer_mismatch)} reference check(s) did not match the stored answer")

    negative_results = []
    survivors = []
    invalid_negatives = []
    for solution in negative:
        comp = compiled[solution["path"]]
        if not comp["ok"]:
            negative_results.append({"path": solution["path"], "status": "compile_failed", "error": comp.get("error", "")[-1000:]})
            invalid_negatives.append(solution["path"])
            continue
        kills = []
        counts = {"AC": 0, "WA": 0, "TLE": 0, "RE": 0, "NO_ANSWER": 0}
        for test in tests:
            _check_cancel(cancelled, deadline)
            expected = test["answer"].read_bytes() if test["answer"].is_file() else None
            result = _run(comp["argv"], cwd=root, data=test["input"].read_bytes(),
                          timeout=meta["timeLimitSeconds"] + 0.5)
            verdict = _verdict(result, expected, meta["timeLimitSeconds"])
            counts[verdict] = counts.get(verdict, 0) + 1
            if verdict != "AC":
                kills.append({"test": test["relative"], "verdict": verdict, "kind": test["kind"]})
        if kills:
            first = kills[0]
            negative_results.append({
                "path": solution["path"], "status": "killed", "test": first["test"],
                "verdict": first["verdict"], "kind": first["kind"],
                "secretKill": any(k["kind"] == "secret" for k in kills),
                "counts": counts,
            })
        else:
            negative_results.append({"path": solution["path"], "status": "survived", "counts": counts})
            survivors.append(solution["path"])
    valid_negatives = [r for r in negative_results if r["status"] == "killed"]
    if survivors:
        errors.append("Negative solution(s) survived every test: " + ", ".join(survivors))
    if negative and not valid_negatives:
        errors.append("No negative solution produced a valid non-AC result")
    if invalid_negatives:
        warnings.append("Negative solution(s) failed to compile: " + ", ".join(invalid_negatives))
    sample_only = [r["path"] for r in negative_results if r["status"] == "killed" and not r.get("secretKill")]
    if sample_only:
        warnings.append("Negative solution(s) were not killed by any secret test: " + ", ".join(sample_only))

    statement = _statement(slug)
    checks.append({"name": "Statement PDF", "status": statement["status"], "detail": statement["detail"]})
    if statement["status"] == "fail":
        errors.append("Statement PDF: " + statement["detail"].splitlines()[0])
    elif statement["status"] == "skip":
        warnings.append("Statement PDF: " + statement["detail"])

    for solution in accepted:
        comp = compiled[solution["path"]]
        if not comp["ok"]:
            errors.append(f"Reference solution failed to compile: {solution['path']}")

    warnings.append("Output comparison is token-based; custom checkers and interactive problems are not checked by this verifier")
    warnings.append("Memory limit is recorded but not enforced by this local verifier")

    status = "verified" if not errors else "failed"
    report = {
        "status": status,
        "at": workspace.now(),
        "problem": meta,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
        "tests": test_results,
        "validator": validator_results,
        "accepted": [{"path": s["path"], "compiled": compiled[s["path"]]["ok"]} for s in accepted],
        "negative": negative_results,
        "answers": built,
        "counts": {
            "tests": len(tests),
            "sample": sum(1 for t in tests if t["kind"] == "sample"),
            "secret": sum(1 for t in tests if t["kind"] == "secret"),
            "accepted": len(accepted),
            "negative": len(negative),
        },
        "limits": {"timeSeconds": meta["timeLimitSeconds"], "memoryMb": meta["memoryMb"]},
        "snapshot": workspace.snapshot_hash(slug),
    }
    workspace.set_report(slug, report)
    return report


def export_package(slug: str) -> dict:
    st = workspace.state(slug)
    report = st.get("lastReport")
    if not report or report.get("status") != "verified":
        raise ValueError("Export is blocked until package verification passes")
    if report.get("snapshot") != workspace.snapshot_hash(slug):
        raise ValueError("The workspace changed after the last verification. Run Verify again before exporting.")
    if workspace.summary(slug).get("unreviewed"):
        raise ValueError("Mark all changes reviewed before exporting")
    root = workspace.ws_path(slug)
    out_dir = root / ".agent" / "export"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{workspace.safe_slug(slug)}-domjudge.zip"
    manifest = {
        "problem": st.get("meta", {}),
        "verifiedAt": report.get("at"),
        "snapshot": report.get("snapshot"),
        "counts": report.get("counts"),
        "files": {},
    }
    include_roots = [
        "problem.yaml", "domjudge-problem.ini", "problem.pdf", "NOTES.md",
        "problem_statement", "data", "submissions", "input_validators", "output_validators",
    ]
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in include_roots:
            path = root / name
            if path.is_file():
                zf.write(path, name)
                manifest["files"][name] = hashlib.sha256(path.read_bytes()).hexdigest()
            elif path.is_dir():
                for item in sorted(path.rglob("*")):
                    if item.is_dir() or item.name == ".keep" or "__pycache__" in item.parts:
                        continue
                    if item.suffix.lower() in (".aux", ".log", ".out", ".toc", ".synctex", ".gz", ".tmp"):
                        continue
                    rel = item.relative_to(root).as_posix()
                    zf.write(item, rel)
                    manifest["files"][rel] = hashlib.sha256(item.read_bytes()).hexdigest()
        validate = _validator(slug)
        if validate is not None and validate.suffix.lower() == ".py" and "input_validators/validate" not in manifest["files"]:
            data = validate.read_bytes()
            if not data.startswith(b"#!"):
                data = b"#!/usr/bin/env python3\n" + data
            info = zipfile.ZipInfo("input_validators/validate", time.localtime()[:6])
            info.external_attr = 0o755 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
            manifest["files"]["input_validators/validate"] = hashlib.sha256(data).hexdigest()
        zf.writestr("problem_statement/manifest.json", json.dumps(manifest, indent=2))
    return {
        "path": target.relative_to(root).as_posix(),
        "absolute": str(target),
        "size": target.stat().st_size,
        "files": len(manifest["files"]),
        "verifiedAt": report.get("at"),
    }
