"""Deterministic DOMjudge package checks.

The agent may *say* anything. This module is the part that actually compiles
solutions, runs the input validator, compares reference output with answers,
tests negative solutions and builds the statement. Its report is the evidence
the UI shows before export is allowed.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import pathlib
import re
import shutil
import sys
import time
import uuid
import zipfile

from author_studio.config import TEMPLATES
from author_studio.packages import icpc_spec
from author_studio.packages import package_model
from author_studio.judging import scoring
from author_studio.judging import verification_modes
from author_studio import winutil
from author_studio.packages import workspace

SOLUTION_EXT = {".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".c": "c", ".py": "py", ".java": "java"}
NEGATIVE_DIRS = ("wrong_answer", "time_limit_exceeded", "wrong_solutions")
OUTPUT_CAP = 8 * 1024 * 1024
VERIFY_BUDGET_SECONDS = 15 * 60


def _which(name: str) -> str | None:
    return shutil.which(name)


def _run(argv: list[str], cwd: pathlib.Path, data: bytes = b"", timeout: float = 10.0, env: dict | None = None, executor: str = "default") -> dict:
    run_env = winutil.python_env()
    if env:
        run_env.update(env)
    result = winutil.run_captured(argv, cwd, data=data, timeout=timeout, env=run_env, executor=executor)
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
        if key == "name":
            line = re.search(r"^name[ \t]*=[ \t]*([^\r\n]+)", ini_text, re.M)
            if line:
                try:
                    value = json.loads(line.group(1).strip())
                except ValueError:
                    pass
                else:
                    if isinstance(value, str):
                        return value
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


def _compare(actual: bytes, expected: bytes, tolerance: float | None = None) -> bool:
    if tolerance is None:
        return _tokens(actual) == _tokens(expected)
    try:
        left = [float(item) for item in _tokens(actual)]
        right = [float(item) for item in _tokens(expected)]
    except ValueError:
        return False
    if len(left) != len(right):
        return False
    return all(math.isfinite(a) and math.isfinite(b) and abs(a - b) <= tolerance for a, b in zip(left, right))


def _verdict(result: dict, expected: bytes | None, time_limit: float, compare=None) -> str:
    if result["timedOut"]:
        return "TLE"
    if not result["ok"]:
        return "RE"
    if result["returncode"] != 0:
        return "RE"
    if expected is None:
        return "NO_ANSWER"
    return "AC" if (compare(result["stdout"], expected) if compare else _compare(result["stdout"], expected)) else "WA"


def _tests(slug: str) -> list[dict]:
    package = package_model.load(slug)
    return [{
        "name": test.name,
        "kind": test.kind,
        "input": test.input,
        "answer": test.answer or test.input.with_suffix(".ans"),
        "group": test.group,
        "relative": test.relative,
    } for test in package.tests]


def _validator(slug: str) -> package_model.Program | None:
    return package_model.load(slug).input_validator_program


def _structure(slug: str, tests: list[dict], accepted: list[dict], negative: list[dict], validator: object | None) -> list[dict]:
    root = workspace.ws_path(slug)
    checks = []

    def check(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    required = ["problem.yaml"]
    if (root / "problem_statement/problem.en.tex").is_file():
        required.append("problem_statement/problem.en.tex")
    if (root / "statement/problem.en.tex").is_file():
        required.append("statement/problem.en.tex")
    if (root / "domjudge-problem.ini").is_file():
        required.append("domjudge-problem.ini")
    for rel in required:
        check(f"File {rel}", "pass", "present")
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
    tex = None
    for folder in ("problem_statement", "statement"):
        candidate = root / folder / "problem.en.tex"
        if candidate.is_file():
            tex = candidate
            break
    if tex is None:
        return {"status": "fail", "detail": "problem_statement/problem.en.tex or statement/problem.en.tex is missing"}
    pdflatex = _which("pdflatex")
    if not pdflatex:
        return {"status": "skip", "detail": "pdflatex was not found; statement compile was not checked"}
    env = {"TEXINPUTS": str(TEMPLATES) + os.pathsep + os.environ.get("TEXINPUTS", "")}
    first = _run([pdflatex, "-interaction=nonstopmode", "-halt-on-error", "problem.en.tex"], cwd=tex.parent, timeout=180, env=env, executor="bwrap")
    if not first["ok"] or first["returncode"] != 0:
        tail = first["stderr"].decode("utf-8", "replace")[-3000:]
        log = tex.parent / "problem.en.log"
        if log.is_file():
            tail = log.read_text("utf-8", errors="replace")[-3000:]
        return {"status": "fail", "detail": "pdflatex failed\n" + tail}
    second = _run([pdflatex, "-interaction=nonstopmode", "-halt-on-error", "problem.en.tex"], cwd=tex.parent, timeout=180, env=env, executor="bwrap")
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


def answer_plan(slug: str) -> dict:
    root = workspace.ws_path(slug)
    tests = _tests(slug)
    return {"counts": {kind: sum(1 for test in tests if test["kind"] == kind)
                       for kind in ("sample", "secret")},
            "references": [row["path"] for row in _solutions(slug) if row["kind"] == "accepted"],
            "outputs": [{"input": test["input"].relative_to(root).as_posix(),
                         "answer": test["answer"].relative_to(root).as_posix(), "kind": test["kind"],
                         "exists": test["answer"].is_file()} for test in tests]}


def _answer_source_path(slug: str, answer_path: str) -> pathlib.Path:
    key = hashlib.sha256(answer_path.encode()).hexdigest()
    return workspace._state_dir(slug) / "answer-sources" / f"{key}.json"


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
    references = [solution["path"] for solution in accepted]
    root = workspace.ws_path(slug)
    reference_hashes = {row["path"]: hashlib.sha256(row["absolute"].read_bytes()).hexdigest() for row in accepted}
    artifacts = []
    for test in tests:
        _check_cancel(cancelled, deadline)
        data = test["input"].read_bytes()
        outputs = []
        for solution in accepted:
            result = _run(compiled[solution["path"]]["argv"], cwd=workspace.ws_path(slug), data=data,
                          timeout=meta["timeLimitSeconds"] + 2.0)
            if result["timedOut"] or not result["ok"] or result["returncode"] != 0:
                return {"ok": False, "errors": [{"path": solution["path"], "error": "Reference failed on " + test["relative"]}],
                        "written": written, "references": references, "outputs": artifacts, "disagreements": reports}
            outputs.append((solution["path"], result["stdout"]))
        if len({tuple(_tokens(o)) for _, o in outputs}) > 1:
            reports.append({"test": test["relative"], "status": "reference_disagreement",
                            "solutions": [p for p, _ in outputs]})
            continue
        answer_path = test["answer"].relative_to(root).as_posix()
        workspace.write_text(slug, answer_path, outputs[0][1].decode("utf-8", "replace"), source="verify")
        written += 1
        workspace._write_json(_answer_source_path(slug, answer_path), {
            "hash": hashlib.sha256(test["answer"].read_bytes()).hexdigest(),
            "references": references, "referenceHashes": reference_hashes, "inputHash": hashlib.sha256(data).hexdigest(),
        })
        artifacts.append({"path": answer_path, "test": test["relative"], "kind": test["kind"]})
    return {"ok": not reports, "written": written, "tests": len(tests), "disagreements": reports,
            "references": references, "outputs": artifacts}


def _set_yaml_memory(text: str, memory_mb: int) -> str:
    if re.search(r"(?m)^\s*memory\s*:\s*\d+", text):
        return re.sub(r"(?m)^(\s*memory\s*:\s*)\d+", rf"\g<1>{memory_mb}", text, count=1)
    if re.search(r"(?m)^limits\s*:\s*$", text):
        return re.sub(r"(?m)^(limits\s*:\s*)$", rf"\1\n  memory: {memory_mb}", text, count=1)
    return text.rstrip() + f"\n\nlimits:\n  memory: {memory_mb}\n"


def _set_limits_in_files(slug: str, time_limit: float, memory_mb: int) -> None:
    root = workspace.ws_path(slug)
    yaml_path = root / "problem.yaml"
    if yaml_path.is_file():
        text = yaml_path.read_text("utf-8")
        workspace.write_text(slug, "problem.yaml", _set_yaml_memory(text, memory_mb), source="verify")
    ini_path = root / "domjudge-problem.ini"
    if ini_path.is_file():
        text = ini_path.read_text("utf-8")
        if re.search(r"(?m)^\s*timelimit\s*=", text):
            text = re.sub(r"(?m)^(\s*timelimit\s*=\s*)[^\r\n]+", rf"\g<1>{time_limit:g}", text, count=1)
        else:
            text = text.rstrip() + f"\ntimelimit = {time_limit:g}\n"
        workspace.write_text(slug, "domjudge-problem.ini", text, source="verify")
    for folder in ("problem_statement", "statement"):
        tex_path = root / folder / "problem.en.tex"
        if tex_path.is_file():
            text = tex_path.read_text("utf-8")
            text = re.sub(r"\\timelimit\{[^}]*\}", rf"\\timelimit{{{time_limit:g} seconds}}", text)
            text = re.sub(r"\\memlimit\{[^}]*\}", rf"\\memlimit{{{memory_mb} MiB}}", text)
            workspace.write_text(slug, f"{folder}/problem.en.tex", text, source="verify")


def run_source(slug: str, path: str, stdin: str | bytes = "") -> dict:
    """Compile and run an arbitrary code file in the workspace for the user's own testing."""
    target = workspace.resolve(slug, path)
    if not target.is_file():
        raise FileNotFoundError("Source file not found")
    language = SOLUTION_EXT.get(target.suffix.lower())
    if not language:
        raise ValueError("Run supports C, C++, Python and Java files")
    solution = {"path": path, "absolute": target, "language": language, "kind": "accepted"}
    build_root = _new_build_dir(slug)
    compiled = _compile(slug, solution, build_root)
    if not compiled["ok"]:
        return {
            "ok": False, "stage": "compile", "path": path, "language": language,
            "error": compiled.get("error", "Compilation failed"),
            "stderr": compiled.get("error", ""), "stdout": "", "exitCode": None,
            "timedOut": False, "ms": 0,
        }
    time_limit = max(5.0, float(_read_meta(slug)["timeLimitSeconds"]) + 5.0)
    result = winutil.run_measured(
        compiled["argv"],
        cwd=workspace.ws_path(slug),
        data=stdin if isinstance(stdin, bytes) else str(stdin or "").encode("utf-8"),
        timeout=time_limit,
        env=winutil.python_env(),
    )
    stdout_bytes = result["stdout"][:OUTPUT_CAP]
    stdout = stdout_bytes.decode("utf-8", "replace")
    return {
        "ok": result["ok"],
        "stage": "run",
        "path": path,
        "language": language,
        "stdout": stdout,
        "stdoutComplete": len(result["stdout"]) < OUTPUT_CAP and stdout.encode() == stdout_bytes,
        "stderr": result["stderr"][:OUTPUT_CAP].decode("utf-8", "replace"),
        "exitCode": result["returncode"],
        "timedOut": result["timedOut"],
        "ms": round(result["ms"], 1),
        "diagnostic": winutil.diagnostic(result["returncode"]),
    }


def _source_diagnostics(slug: str, path: str, stderr: str) -> list[dict]:
    source = workspace.resolve(slug, path)
    diagnostics = []
    for match in re.finditer(r"(?m)^([^\r\n]+?):(\d+)(?::(\d+))?:\s*(?:fatal error|error|warning):|"
                             r'File "([^"\r\n]+)", line (\d+)', stderr):
        location = pathlib.Path(match[1] or match[4])
        resolved = location.resolve() if location.is_absolute() else (workspace.ws_path(slug) / location).resolve()
        if resolved == source:
            diagnostics.append({"path": path, "line": int(match[2] or match[5]), "column": int(match[3] or 1)})
            if len(diagnostics) == 12:
                break
    return diagnostics


def run_case(slug: str, rel: str, body: dict, snapshot: str) -> dict:
    source = workspace.resolve(slug, rel)
    if not source.is_file():
        raise FileNotFoundError("Source file not found")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if body.get("expectedHash", source_hash) != source_hash:
        raise workspace.SnapshotConflict("Saved source changed. Reopen the file before running it.")
    stdin = body.get("stdin", "")
    expected = body.get("expected")
    if not isinstance(stdin, str) or len(stdin.encode()) > 256 * 1024:
        raise ValueError("Standard input must be text of at most 256 KiB.")
    if expected is not None and (not isinstance(expected, str) or len(expected.encode()) > 16 * 1024):
        raise ValueError("Expected output must be text of at most 16 KiB.")
    case = body.get("casePath")
    run_input = stdin.encode()
    if case:
        root = workspace.ws_path(slug)
        test = next((row for row in _tests(slug) if row["input"].relative_to(root).as_posix() == case), None)
        if test is None or test["input"].read_text("utf-8", errors="replace") != stdin:
            raise workspace.SnapshotConflict("The saved case changed. Reload it before running.")
        run_input = test["input"].read_bytes()
        if len(run_input) > 256 * 1024:
            raise ValueError("Saved inputs may be at most 256 KiB for manual runs.")
        # This manual runner uses token comparison. A custom checker is exercised by Verify.
        expected = None
        if test["answer"].is_file() and test["answer"].stat().st_size <= 16 * 1024:
            try:
                expected = test["answer"].read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                pass
    result = run_source(slug, rel, run_input)
    workspace.require_snapshot(slug, snapshot)
    compared = expected is not None and result["ok"] and result.get("stdoutComplete")
    comparison = None if not compared else {
        "expected": expected, "matches": _compare(result["stdout"].encode(), expected.encode()),
        "source": "stored answer" if case else "attached expectation", "method": "token comparison",
    }
    return {**result, "snapshot": snapshot, "sourceHash": source_hash,
            "diagnostics": _source_diagnostics(slug, rel, result["stderr"]),
            "evidenceSource": "local process", "casePath": case, "stdinHash": hashlib.sha256(run_input).hexdigest(),
            "comparison": comparison}


def measure_limits(slug: str, cancelled=None) -> dict:
    winutil.prepare()
    deadline = time.monotonic() + VERIFY_BUDGET_SECONDS
    _check_cancel(cancelled, deadline)
    tests = _tests(slug)
    accepted = [s for s in _solutions(slug) if s["kind"] == "accepted"]
    if not tests:
        raise ValueError("Add sample or secret tests before measuring limits")
    if not accepted:
        raise ValueError("Add an accepted reference solution before measuring limits")
    build_root = _new_build_dir(slug)
    compiled = {}
    for solution in accepted:
        _check_cancel(cancelled, deadline)
        comp = _compile(slug, solution, build_root)
        if not comp["ok"]:
            raise RuntimeError(f"Reference failed to compile: {solution['path']}: {comp.get('error', '')[-1000:]}")
        compiled[solution["path"]] = comp
    max_ms = 0.0
    max_rss = 0
    slowest = None
    worst_memory = None
    samples = []
    for solution in accepted:
        for test in tests:
            _check_cancel(cancelled, deadline)
            result = winutil.run_measured(
                compiled[solution["path"]]["argv"],
                cwd=workspace.ws_path(slug),
                data=test["input"].read_bytes(),
                timeout=max(30.0, float(_read_meta(slug)["timeLimitSeconds"]) * 5),
                env=winutil.python_env(),
            )
            if result["timedOut"] or not result["ok"]:
                raise RuntimeError(
                    f"Reference {solution['path']} failed on {test['relative']}"
                    + (" (timed out)" if result["timedOut"] else f" (exit {result['returncode']})")
                )
            ms = result["ms"]
            rss = int(result.get("peakRssBytes") or 0)
            if ms > max_ms:
                max_ms = ms
                slowest = test["relative"]
            if rss > max_rss:
                max_rss = rss
                worst_memory = test["relative"]
            samples.append({"path": solution["path"], "test": test["relative"], "ms": round(ms, 1), "rss": rss})
    runtime_s = max(0.001, max_ms / 1000.0)
    time_limit = max(1.0, min(10.0, math.ceil(runtime_s * 2.5 * 2) / 2))
    memory_mb = 256
    if max_rss > 0:
        measured_mb = max_rss / (1024 * 1024)
        memory_mb = max(256, min(1024, math.ceil(measured_mb * 1.5 / 64) * 64))
    _set_limits_in_files(slug, time_limit, memory_mb)
    details = {
        "maxRuntimeMs": round(max_ms, 1),
        "maxMemoryMb": round(max_rss / (1024 * 1024), 1) if max_rss else None,
        "slowestTest": slowest,
        "worstMemoryTest": worst_memory,
        "samples": samples,
        "measuredAt": workspace.now(),
    }
    workspace.set_limits(slug, time_limit, memory_mb, details)
    return {
        "ok": True,
        "timeLimitSeconds": time_limit,
        "memoryMb": memory_mb,
        "tests": len(tests),
        "solutions": [s["path"] for s in accepted],
        **details,
    }


def _verify_interactive(slug: str, package: package_model.Package, cancelled=None) -> dict:
    root = package.root
    tests = _tests(slug)
    solutions = _solutions(slug)
    accepted = [s for s in solutions if s["kind"] == "accepted"]
    negative = [s for s in solutions if s["kind"] == "negative"]
    validator = _validator(slug)
    checks = _structure(slug, tests, accepted, negative, validator)
    checks.append({
        "name": "Problem type",
        "status": "pass" if package.is_interactive else "fail",
        "detail": package.problem_type,
    })
    group_errors = package_model.group_errors(package)
    checks.append({
        "name": "Test groups",
        "status": "pass" if not group_errors else "fail",
        "detail": "; ".join(group_errors) if group_errors else "valid",
    })
    selftest = verification_modes.interactive_selftest(slug)
    checks.append({"name": "Interactive self-test", "status": selftest["status"], "detail": selftest["detail"]})
    spec = icpc_spec.audit(slug)
    checks.append({
        "name": "ICPC package spec",
        "status": spec["status"],
        "detail": f"{spec['counts']['pass']}/{spec['counts']['checks']} checks pass; {spec['counts']['warn']} warning(s)",
    })
    errors = [f"{item['name']}: {item['detail']}" for item in checks if item["status"] == "fail"]
    warnings = [f"{item['name']}: {item['detail']}" for item in checks if item["status"] in ("warn", "skipped")]
    warnings.extend(f"ICPC spec: {item}" for item in spec["warnings"])
    if not accepted:
        errors.append("Interactive problems need an accepted reference")
    return {
        "status": "verified" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "tests": [{"test": item["relative"], "kind": item["kind"], "group": item.get("group", ""), "interactive": True} for item in tests],
        "negative": [{"path": item["path"], "status": "proposal", "interactive": True} for item in negative],
        "counts": {"tests": len(tests), "accepted": len(accepted), "negative": len(negative), "groups": len(package.groups())},
        "limits": workspace.state(slug).get("measuredLimits") or {},
        "interactiveSelftest": selftest,
        "spec": spec,
        "at": workspace.now(),
    }


def verify(slug: str, write_answers: bool = False, cancelled=None) -> dict:
    winutil.prepare()
    deadline = time.monotonic() + VERIFY_BUDGET_SECONDS
    _check_cancel(cancelled, deadline)
    root = workspace.ws_path(slug)
    package = package_model.load(slug)
    if package.is_interactive:
        return _verify_interactive(slug, package, cancelled)
    built = {"ok": False, "written": 0, "errors": [], "disagreements": []}
    if write_answers and any(solution["kind"] == "accepted" for solution in _solutions(slug)):
        built = build_answers(slug, cancelled=cancelled)
    # The verifier itself may write these PDFs. Pin all other files across
    # compilation, then pin the complete deliverable for the remaining checks.
    statement_outputs = {"problem.pdf", "problem_statement/problem.en.pdf", "statement/problem.en.pdf"}

    def statement_inputs() -> str:
        return workspace.snapshot_hash(slug, entries=[
            entry for entry in workspace.tree(slug) if entry["path"] not in statement_outputs
        ])

    inputs = statement_inputs()
    statement = _statement(slug)
    snapshot = workspace.snapshot_hash(slug)
    if statement_inputs() != inputs:
        raise ValueError("The workspace changed during verification. Run Verify again.")
    package = package_model.load(slug)
    if package.is_interactive:
        raise ValueError("The package type changed during verification. Run Verify again.")
    meta = _read_meta(slug)
    tests = _tests(slug)
    solutions = _solutions(slug)
    accepted = [s for s in solutions if s["kind"] == "accepted"]
    negative = [s for s in solutions if s["kind"] == "negative"]
    validator = _validator(slug)
    checks = _structure(slug, tests, accepted, negative, validator)
    group_errors = package_model.group_errors(package)
    checks.append({
        "name": "Test groups",
        "status": "pass" if not group_errors else "fail",
        "detail": "; ".join(group_errors) if group_errors else "valid",
    })
    checker_selftest = verification_modes.checker_selftest(slug)
    if checker_selftest["status"] != "skipped":
        checks.append({
            "name": "Checker self-test",
            "status": "pass" if checker_selftest["status"] == "pass" else "fail",
            "detail": checker_selftest["detail"],
        })
    limit_state = workspace.state(slug)
    limits_measured = bool(limit_state.get("limitsMeasured"))
    measured = limit_state.get("measuredLimits") or {}
    checks.append({
        "name": "Limits measured",
        "status": "pass" if limits_measured else "fail",
        "detail": (
            f"{measured.get('timeLimitSeconds', meta.get('timeLimitSeconds'))} s / "
            f"{measured.get('memoryMb', meta.get('memoryMb'))} MiB from {measured.get('slowestTest', 'reference runs')}"
            if limits_measured else "run Measure limits after the reference and tests are ready"
        ),
    })
    errors: list[str] = []
    warnings: list[str] = []

    for check in checks:
        if check["status"] == "fail":
            errors.append(f"{check['name']}: {check['detail']}")
        elif check["status"] == "warn":
            warnings.append(f"{check['name']}: {check['detail']}")
    if not limits_measured:
        errors.append("Limits have not been measured from the reference solutions. Run Measure limits.")

    if accepted and write_answers:
        if not built["ok"]:
            errors.append("Answer generation failed")
            warnings.extend(str(e) for e in built.get("errors", []))
            warnings.extend(f"Reference disagreement on {d['test']}" for d in built.get("disagreements", []))

    compiled = {}
    build_root = _new_build_dir(slug)
    checker_program = package.output_validator_program
    checker_argv = None
    if checker_program is not None:
        compiled_checker = verification_modes._build_program(
            slug, checker_program.path.relative_to(package.root).as_posix(), build_root, program=checker_program
        )
        if compiled_checker.get("ok"):
            checker_argv = compiled_checker["argv"]
        else:
            errors.append("Checker failed to compile: " + str(compiled_checker.get("error", ""))[-1000:])

    def compare(actual: bytes, expected: bytes, test: dict) -> bool:
        if checker_argv is not None:
            result = verification_modes._run_checker(
                checker_argv, checker_program.contract, test["input"], test["answer"],
                actual, build_root, flags=checker_program.flags,
            )
            return bool(result["ok"])
        return _compare(actual, expected, package.float_tolerance())

    for solution in accepted + negative:
        _check_cancel(cancelled, deadline)
        compiled[solution["path"]] = _compile(slug, solution, build_root)

    validator_results = []
    validator_build = None
    if validator:
        validator_build = verification_modes._build_program(
            slug, validator.path.relative_to(root).as_posix(), build_root, program=validator
        )
        if not validator_build.get("ok"):
            errors.append("Input validator failed to build: " + str(validator_build.get("error", ""))[-1000:])
        for test in tests:
            _check_cancel(cancelled, deadline)
            if not validator_build.get("ok"):
                validator_results.append({"test": test["relative"], "valid": False, "exitCode": None, "stderr": "validator did not build"})
                continue
            result = winutil.run_captured(validator_build["argv"], cwd=root, data=test["input"].read_bytes(), timeout=15)
            # ICPC spec: input validators must exit 42 on success.
            valid = result["ok"] and result["returncode"] == 42
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
    validation = {row["test"]: row["valid"] for row in validator_results}
    source_hashes = {row["path"]: hashlib.sha256(row["absolute"].read_bytes()).hexdigest() for row in accepted + negative}
    diagnostics = {path: _source_diagnostics(slug, path, item.get("error") or "")
                   for path, item in compiled.items() if not item["ok"]}
    answer_mismatch = []
    missing_answer = []
    for test in tests:
        _check_cancel(cancelled, deadline)
        expected = test["answer"].read_bytes() if test["answer"].is_file() else None
        data = test["input"].read_bytes()
        if expected is None:
            missing_answer.append(test["relative"])
        case_path = test["input"].relative_to(root).as_posix()
        answer_path = test["answer"].relative_to(root).as_posix()
        source_receipt = workspace._read_json(_answer_source_path(slug, answer_path), {})
        known_source = expected is not None and source_receipt.get("hash") == hashlib.sha256(expected).hexdigest()
        row = {"test": test["relative"], "kind": test["kind"], "group": test["group"], "path": case_path,
               "validatorPassed": validation.get(test["relative"]), "solutions": [],
               "expectedAnswer": {"path": answer_path, "present": expected is not None,
                                  "references": source_receipt["references"] if known_source else [],
                                  "referenceHashes": source_receipt.get("referenceHashes", {}) if known_source else {},
                                  "inputMatchesBuild": known_source and source_receipt.get("inputHash") ==
                                                       hashlib.sha256(data).hexdigest()}}
        for solution in accepted:
            comp = compiled[solution["path"]]
            if not comp["ok"]:
                row["solutions"].append({"path": solution["path"], "verdict": "CE", "error": comp.get("error", "")[-1000:]})
                continue
            result = _run(comp["argv"], cwd=root, data=data,
                          timeout=meta["timeLimitSeconds"] + 0.5)
            verdict = _verdict(result, expected, meta["timeLimitSeconds"], compare=lambda a, e: compare(a, e, test))
            row["solutions"].append({
                "path": solution["path"], "verdict": verdict, "ms": round(result["ms"], 1),
                "stderr": result["stderr"].decode("utf-8", "replace")[-500:] if verdict != "AC" else "",
            })
            if verdict not in ("AC",):
                answer_mismatch.append({"test": test["relative"], "path": solution["path"], "verdict": verdict})
                if verdict == "WA":
                    row["solutions"][-1]["actualPreview"] = result["stdout"][:1200].decode("utf-8", "replace")
                    row["solutions"][-1]["expectedPreview"] = (expected or b"")[:1200].decode("utf-8", "replace")
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
            verdict = _verdict(result, expected, meta["timeLimitSeconds"], compare=lambda a, e: compare(a, e, test))
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

    verdicts = {}
    if test_results and accepted:
        first = accepted[0]["path"]
        for row in test_results:
            for solution in row["solutions"]:
                if solution["path"] == first:
                    verdicts[row["test"]] = solution["verdict"]
    group_score = scoring.evaluate(package, verdicts)
    if package.groups():
        checks.append({
            "name": "Group scoring",
            "status": "pass" if group_score["groups"] else "fail",
            "detail": (
                f"{group_score['score']:g}/{group_score['maxScore']:g} points; "
                + ", ".join(f"{item['name']}={'pass' if item['passed'] else 'blocked'}" for item in group_score["groups"])
            ),
        })

    checks.append({"name": "Statement PDF", "status": statement["status"], "detail": statement["detail"]})
    if statement["status"] == "fail":
        errors.append("Statement PDF: " + statement["detail"].splitlines()[0])
    elif statement["status"] == "skip":
        warnings.append("Statement PDF: " + statement["detail"])

    for solution in accepted:
        comp = compiled[solution["path"]]
        if not comp["ok"]:
            errors.append(f"Reference solution failed to compile: {solution['path']}")

    spec = icpc_spec.audit(slug)
    checks.append({
        "name": "ICPC package spec",
        "status": spec["status"],
        "detail": f"{spec['counts']['pass']}/{spec['counts']['checks']} checks pass; {spec['counts']['warn']} warning(s)",
    })
    errors.extend(f"ICPC spec: {item}" for item in spec["errors"])
    warnings.extend(f"ICPC spec: {item}" for item in spec["warnings"])

    if checker_program is None:
        warnings.append("Output comparison is token-based; no custom output validator is configured")
    else:
        warnings.append(f"Output validator contract: {checker_program.contract}; see the checker self-test evidence")
    warnings.append("Memory limit is recorded; the executor enforces it for isolated runs")

    _check_cancel(cancelled, deadline)
    if workspace.snapshot_hash(slug) != snapshot:
        raise ValueError("The workspace changed during verification. Run Verify again.")
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
        "sourceHashes": source_hashes,
        "sourceDiagnostics": diagnostics,
        "negative": negative_results,
        "groups": group_score,
        "spec": spec,
        "answers": built,
        "counts": {
            "tests": len(tests),
            "sample": sum(1 for t in tests if t["kind"] == "sample"),
            "secret": sum(1 for t in tests if t["kind"] == "secret"),
            "accepted": len(accepted),
            "negative": len(negative),
        },
        "limits": {"timeSeconds": meta["timeLimitSeconds"], "memoryMb": meta["memoryMb"]},
        "snapshot": snapshot,
    }
    workspace.set_report(slug, report)
    return report


def export_package(slug: str) -> dict:
    info = workspace.summary(slug)
    workflow = info["workflow"]
    if not workflow["canExport"]:
        raise ValueError(workflow["blocker"])
    report = info["lastReport"]
    root = workspace.ws_path(slug)
    out_dir = root / ".agent" / "export"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / workspace.export_filename(slug)
    staged = out_dir / f".{target.name}.{uuid.uuid4().hex}.tmp"
    manifest = {
        "problem": info["meta"],
        "verifiedAt": report.get("at"),
        "createdAt": workspace.now(),
        "snapshot": report.get("snapshot"),
        "counts": report.get("counts"),
        "files": {},
    }
    include_roots = [
        "problem.yaml", "domjudge-problem.ini", "problem.pdf", "NOTES.md",
        "problem_statement", "statement", "data", "submissions", "attachments",
        "input_validators", "input_format_validators", "output_validators", "output_validator",
        "test_group.yaml", "testdata.yaml", "include", "generators",
    ]
    def zip_payload(path: pathlib.Path) -> bytes:
        """Normalize text test data to LF so DOMjudge import is warning-free."""
        data = path.read_bytes()
        if path.suffix.lower() in (".in", ".ans", ".out", ".interaction", ".py"):
            data = data.replace(b"\r\n", b"\n")
        return data

    with zipfile.ZipFile(staged, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in include_roots:
            path = root / name
            if path.is_file():
                data = zip_payload(path)
                info = zipfile.ZipInfo(name, time.localtime()[:6])
                info.external_attr = (path.stat().st_mode & 0xFFFF) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, data)
                manifest["files"][name] = hashlib.sha256(data).hexdigest()
            elif path.is_dir():
                for item in sorted(path.rglob("*")):
                    rel = item.relative_to(root).as_posix()
                    if item.is_dir() or item.name == ".keep" or workspace.SKIP_DIRS.intersection(rel.split("/")):
                        continue
                    if item.suffix.lower() in (".aux", ".log", ".out", ".toc", ".synctex", ".gz", ".tmp"):
                        continue
                    data = zip_payload(item)
                    info = zipfile.ZipInfo(rel, time.localtime()[:6])
                    info.external_attr = (item.stat().st_mode & 0xFFFF) << 16
                    info.compress_type = zipfile.ZIP_DEFLATED
                    zf.writestr(info, data)
                    manifest["files"][rel] = hashlib.sha256(data).hexdigest()
        validate = _validator(slug)
        validate_path = validate.path if validate is not None else None
        if validate_path is not None and validate_path.suffix.lower() == ".py" and "input_validators/validate" not in manifest["files"]:
            data = validate_path.read_bytes()
            data = data.replace(b"\r\n", b"\n")
            if not data.startswith(b"#!"):
                data = b"#!/usr/bin/env python3\n" + data
            info = zipfile.ZipInfo("input_validators/validate", time.localtime()[:6])
            info.external_attr = 0o755 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
            manifest["files"]["input_validators/validate"] = hashlib.sha256(data).hexdigest()
        zf.writestr("problem_statement/manifest.json", json.dumps(manifest, indent=2))
    latest = workspace.summary(slug)["workflow"]
    if latest["snapshot"] != workflow["snapshot"] or not latest["canExport"]:
        raise ValueError("The saved package or its approval changed during export. Review the current revision.")
    staged.replace(target)
    return {
        "path": target.relative_to(root).as_posix(),
        "absolute": str(target),
        "size": target.stat().st_size,
        "files": len(manifest["files"]),
        "verifiedAt": report.get("at"),
        "snapshot": workflow["snapshot"],
    }
