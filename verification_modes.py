"""Checker/output-validator self-tests and interactive verification.

The deterministic harness owns every verdict here. Agents may propose test data,
but these checks decide whether a checker or interactor can be trusted.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import sys

import package_model
import winutil
import workspace

OUTPUT_CAP = 200_000


def _build_program(slug: str, rel: str, build: pathlib.Path) -> dict:
    root = workspace.ws_path(slug)
    source = root / rel
    if not source.is_file():
        return {"ok": False, "error": f"missing {rel}"}
    suffix = source.suffix.lower()
    if suffix == ".py":
        return {"ok": True, "argv": [sys.executable, str(source)]}
    if suffix in (".cpp", ".cc", ".cxx", ".c"):
        compiler = shutil.which("g++" if suffix != ".c" else "gcc")
        if not compiler:
            return {"ok": False, "error": "compiler not found"}
        exe = build / (re.sub(r"[^A-Za-z0-9_]", "_", source.stem) + ".exe")
        std = "-std=gnu++20" if suffix != ".c" else "-std=gnu11"
        result = winutil.run_captured([compiler, "-O2", std, "-o", str(exe), str(source)], cwd=build, timeout=90)
        if result["returncode"] != 0:
            return {"ok": False, "error": result["stderr"].decode("utf-8", "replace")[-3000:]}
        return {"ok": True, "argv": [str(exe)]}
    return {"ok": False, "error": f"unsupported checker language: {suffix}"}


def _run_checker(argv: list[str], input_path: pathlib.Path, output_path: pathlib.Path,
                 answer_path: pathlib.Path, cwd: pathlib.Path, timeout: float = 20.0) -> dict:
    result = winutil.run_captured(
        argv + [str(input_path), str(output_path), str(answer_path)],
        cwd=cwd, timeout=timeout,
    )
    code = result["returncode"]
    verdict = "AC" if code == 0 else "WA" if code in (1, 2) else "FAIL" if code == 3 else "ERROR"
    if result["timedOut"]:
        verdict = "TIMEOUT"
    return {
        "ok": verdict == "AC",
        "verdict": verdict,
        "exitCode": code,
        "timedOut": result["timedOut"],
        "stdout": result["stdout"][:OUTPUT_CAP].decode("utf-8", "replace"),
        "stderr": result["stderr"][:OUTPUT_CAP].decode("utf-8", "replace"),
    }


def checker_selftest(slug: str) -> dict:
    """Run the required checker matrix. Any failure blocks verification."""
    package = package_model.load(slug)
    checker = package.output_validator
    if checker is None:
        return {"status": "skipped", "detail": "no output_validator", "cases": []}
    build = workspace.ws_path(slug) / ".agent" / "build" / "checker-selftest"
    shutil.rmtree(build, ignore_errors=True)
    build.mkdir(parents=True, exist_ok=True)
    cases = []
    try:
        rel = checker.relative_to(package.root).as_posix()
        compiled = _build_program(slug, rel, build)
        if not compiled["ok"]:
            return {"status": "fail", "detail": compiled["error"], "cases": []}
        argv = compiled["argv"]

        def record(name: str, expected: str, actual: dict) -> None:
            cases.append({
                "name": name,
                "expected": expected,
                "actual": actual["verdict"],
                "pass": actual["verdict"] == expected,
                "message": (actual["stdout"] or actual["stderr"])[:500],
            })

        tests = [test for test in package.tests if test.answer is not None]
        if not tests:
            return {"status": "fail", "detail": "checker selftest needs at least one .ans file", "cases": []}
        test = tests[0]
        answer = test.answer.read_bytes()
        reference = build / "reference.out"
        reference.write_bytes(answer)
        record("reference accepted", "AC", _run_checker(argv, test.input, reference, test.answer, build))

        wrong = build / "wrong.out"
        wrong.write_text("__definitely_wrong__ 987654321\n", "utf-8")
        record("wrong rejected", "WA", _run_checker(argv, test.input, wrong, test.answer, build))

        malformed = build / "malformed.out"
        malformed.write_bytes(b"\x00\xff\xfe not valid\n")
        result = _run_checker(argv, test.input, malformed, test.answer, build)
        cases.append({
            "name": "malformed rejected without crash",
            "expected": "reject",
            "actual": "crash" if result["verdict"] == "ERROR" else result["verdict"],
            "pass": result["verdict"] in ("WA", "FAIL") and not result["timedOut"],
            "message": (result["stdout"] or result["stderr"])[:500],
        })

        missing = build / "missing.out"
        missing.write_text("", "utf-8")
        record("empty output rejected", "WA", _run_checker(argv, test.input, missing, test.answer, build))

        extra = build / "extra.out"
        extra.write_bytes(answer + b"\nEXTRA TOKENS THAT SHOULD NOT BE ACCEPTED\n")
        record("extra output rejected", "WA", _run_checker(argv, test.input, extra, test.answer, build))

        for valid in sorted((package.root / "data" / "valid_output").glob("*.out")):
            record(f"valid_output/{valid.name} accepted", "AC", _run_checker(argv, test.input, valid, test.answer, build))
        for invalid in sorted((package.root / "data" / "invalid_output").glob("*.out")):
            record(f"invalid_output/{invalid.name} rejected", "WA", _run_checker(argv, test.input, invalid, test.answer, build))
    finally:
        shutil.rmtree(build, ignore_errors=True)
    failed = [case for case in cases if not case["pass"]]
    return {
        "status": "pass" if not failed else "fail",
        "detail": f"{len(cases) - len(failed)}/{len(cases)} checker self-tests passed",
        "cases": cases,
    }


def interactive_selftest(slug: str) -> dict:
    """Run the reference and wrong solutions against the interactor."""
    package = package_model.load(slug)
    if not package.is_interactive:
        return {"status": "skipped", "detail": "not an interactive problem", "cases": []}
    interactor = package.output_validator
    if interactor is None:
        return {"status": "fail", "detail": "interactive problems need output_validator (interactor)", "cases": []}
    build = workspace.ws_path(slug) / ".agent" / "build" / "interactive-selftest"
    shutil.rmtree(build, ignore_errors=True)
    build.mkdir(parents=True, exist_ok=True)
    cases = []
    try:
        compiled_interactor = _build_program(slug, interactor.relative_to(package.root).as_posix(), build)
        if not compiled_interactor["ok"]:
            return {"status": "fail", "detail": compiled_interactor["error"], "cases": []}
        from verify import _solutions, _compile  # local import avoids a module cycle

        accepted = [s for s in _solutions(slug) if s["kind"] == "accepted"]
        negative = [s for s in _solutions(slug) if s["kind"] == "negative"]
        if not accepted:
            return {"status": "fail", "detail": "interactive problems need an accepted reference", "cases": []}
        test = next((item for item in package.tests if item.kind == "secret"), None) or (package.tests[0] if package.tests else None)
        if test is None:
            return {"status": "fail", "detail": "interactive problems need at least one test", "cases": []}
        for solution in accepted:
            compiled = _compile(slug, solution, build)
            if not compiled["ok"]:
                cases.append({"name": f"reference {solution['path']}", "expected": "AC", "actual": "CE", "pass": False, "message": compiled.get("error", "")[:500]})
                continue
            transcript_path = build / f"transcript-{solution['path'].replace('/', '_')}.log"
            validator_argv = compiled_interactor["argv"] + [
                str(test.input), str(transcript_path), str(test.answer or ""),
            ]
            result = winutil.run_interactive(compiled["argv"], validator_argv, cwd=workspace.ws_path(slug), timeout=20)
            cases.append({
                "name": f"reference {solution['path']}",
                "expected": "AC",
                "actual": "AC" if result["ok"] else ("TIMEOUT" if result["timedOut"] else "WA"),
                "pass": result["ok"],
                "message": "",
                "transcript": result["transcript"][:200],
            })
        for solution in negative:
            compiled = _compile(slug, solution, build)
            if not compiled["ok"]:
                cases.append({"name": f"negative {solution['path']}", "expected": "rejected", "actual": "CE", "pass": False, "message": compiled.get("error", "")[:500]})
                continue
            transcript_path = build / f"transcript-{solution['path'].replace('/', '_')}.log"
            validator_argv = compiled_interactor["argv"] + [
                str(test.input), str(transcript_path), str(test.answer or ""),
            ]
            result = winutil.run_interactive(compiled["argv"], validator_argv, cwd=workspace.ws_path(slug), timeout=20)
            cases.append({
                "name": f"negative {solution['path']}",
                "expected": "rejected",
                "actual": "AC" if result["ok"] else "rejected",
                "pass": not result["ok"],
                "message": "",
                "transcript": result["transcript"][:200],
            })
    finally:
        shutil.rmtree(build, ignore_errors=True)
    failed = [case for case in cases if not case["pass"]]
    return {
        "status": "pass" if cases and not failed else "fail",
        "detail": f"{len(cases) - len(failed)}/{len(cases)} interactive self-tests passed",
        "cases": cases,
    }
