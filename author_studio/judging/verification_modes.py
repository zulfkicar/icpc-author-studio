"""Checker/output-validator self-tests and interactive verification.

The deterministic harness owns every verdict here. Agents may propose test data,
but these checks decide whether a checker or interactor can be trusted.

Two validator contracts are supported:

* ``spec`` — the ICPC Problem Package Format contract. The validator is called
  as ``<validator> input answer feedback_dir [flags]`` with the team output on
  stdin and must exit 42 (accepted) or 43 (wrong answer).
* ``testlib`` — ``registerTestlibCmd(argc, argv)`` with
  ``<validator> input team_output answer`` and exit 0/1/2/3.

The contract is detected from the source and returned by
``package_model.Program.contract``.
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import sys

from author_studio import config
from author_studio.packages import package_model
from author_studio import winutil
from author_studio.packages import workspace

OUTPUT_CAP = 200_000
SPEC_AC = 42
SPEC_WA = 43


def _testlib_header() -> pathlib.Path | None:
    path = config.TEMPLATES / "testlib.h"
    return path if path.is_file() else None


def _build_program(slug: str, rel: str, build: pathlib.Path, *, program: package_model.Program | None = None) -> dict:
    root = workspace.ws_path(slug)
    source = root / rel
    if not source.is_file():
        return {"ok": False, "error": f"missing {rel}"}
    if program is not None and program.build_script is not None:
        build_script = program.build_script
        try:
            build_script.chmod(0o755)
        except OSError:
            pass
        result = winutil.run_captured([str(build_script)], cwd=program.directory, timeout=90)
        if result["returncode"] != 0:
            return {"ok": False, "error": result["stderr"].decode("utf-8", "replace")[-3000:]}
        source = program.run_script if program.run_script and program.run_script.is_file() else source
    suffix = source.suffix.lower()
    if suffix == ".py":
        return {"ok": True, "argv": [sys.executable, str(source)]}
    if source.name == "run" and not suffix:
        try:
            source.chmod(0o755)
        except OSError:
            pass
        return {"ok": True, "argv": [str(source)]}
    if suffix in (".cpp", ".cc", ".cxx", ".c", ".h", ".hpp"):
        compiler = shutil.which("g++" if suffix != ".c" else "gcc")
        if not compiler:
            return {"ok": False, "error": "compiler not found"}
        header = _testlib_header()
        include_args: list[str] = []
        if header is not None:
            target_header = build / "testlib.h"
            if not target_header.is_file() or target_header.stat().st_size != header.stat().st_size:
                shutil.copyfile(header, target_header)
            include_args = ["-I", str(build)]
        exe = build / (re.sub(r"[^A-Za-z0-9_]", "_", source.stem) + ".exe")
        std = "-std=gnu++20" if suffix != ".c" else "-std=gnu11"
        result = winutil.run_captured(
            [compiler, "-O2", std, "-pipe", *include_args, "-o", str(exe), str(source)],
            cwd=build, timeout=90,
        )
        if result["returncode"] != 0:
            return {"ok": False, "error": result["stderr"].decode("utf-8", "replace")[-3000:]}
        return {"ok": True, "argv": [str(exe)]}
    return {"ok": False, "error": f"unsupported validator language: {suffix or source.name}"}


def _verdict_from_code(contract: str, code: int | None, timed_out: bool) -> str:
    if timed_out:
        return "TIMEOUT"
    if contract == "testlib":
        return {0: "AC", 1: "WA", 2: "WA", 3: "FAIL"}.get(code, "ERROR")
    return "AC" if code == SPEC_AC else "WA" if code == SPEC_WA else "ERROR"


def _run_checker(
    argv: list[str],
    contract: str,
    input_path: pathlib.Path,
    answer_path: pathlib.Path,
    team_output: bytes,
    cwd: pathlib.Path,
    timeout: float = 20.0,
    flags: list[str] | None = None,
) -> dict:
    feedback = cwd / "feedback"
    feedback.mkdir(parents=True, exist_ok=True)
    flags = list(flags or [])
    if contract == "testlib":
        output_path = cwd / "team.out"
        output_path.write_bytes(team_output)
        args = argv + [str(input_path), str(output_path), str(answer_path)]
        result = winutil.run_captured(args, cwd=cwd, timeout=timeout)
    else:
        args = argv + [str(input_path), str(answer_path), str(feedback) + os.sep] + flags
        result = winutil.run_captured(args, cwd=cwd, data=team_output, timeout=timeout)
    verdict = _verdict_from_code(contract, result["returncode"], result["timedOut"])
    message = ""
    for name in ("judgemessage.txt", "teammessage.txt", "score.txt"):
        path = feedback / name
        if path.is_file():
            message += path.read_text("utf-8", errors="replace")[:500]
    if not message:
        message = (result["stdout"] or result["stderr"])[:500].decode("utf-8", "replace")
    return {
        "ok": verdict == "AC",
        "verdict": verdict,
        "exitCode": result["returncode"],
        "timedOut": result["timedOut"],
        "stdout": result["stdout"][:OUTPUT_CAP].decode("utf-8", "replace"),
        "stderr": result["stderr"][:OUTPUT_CAP].decode("utf-8", "replace"),
        "message": message,
    }


def checker_selftest(slug: str) -> dict:
    """Run the required checker matrix. Any failure blocks verification."""
    package = package_model.load(slug)
    program = package.output_validator_program
    if program is None:
        return {"status": "skipped", "detail": "no output_validators/ or output_validator/", "cases": []}
    build = workspace.ws_path(slug) / ".agent" / "build" / "checker-selftest"
    shutil.rmtree(build, ignore_errors=True)
    build.mkdir(parents=True, exist_ok=True)
    cases = []
    try:
        rel = program.path.relative_to(package.root).as_posix()
        compiled = _build_program(slug, rel, build, program=program)
        if not compiled["ok"]:
            return {"status": "fail", "detail": compiled["error"], "cases": []}
        argv = compiled["argv"]
        contract = program.contract
        flags = program.flags

        def record(name: str, expected: str, actual: dict) -> None:
            cases.append({
                "name": name,
                "expected": expected,
                "actual": actual["verdict"],
                "pass": actual["verdict"] == expected,
                "message": actual.get("message", "")[:500],
                "exitCode": actual.get("exitCode"),
            })

        def run(input_path, answer_path, output: bytes) -> dict:
            return _run_checker(argv, contract, input_path, answer_path, output, build, flags=flags)

        tests = [test for test in package.tests if test.answer is not None]
        if not tests:
            return {"status": "fail", "detail": "checker selftest needs at least one .ans file", "cases": []}
        test = tests[0]
        answer = test.answer.read_bytes()
        record("reference accepted", "AC", run(test.input, test.answer, answer))

        record("wrong rejected", "WA", run(test.input, test.answer, b"__definitely_wrong__ 987654321\n"))

        result = run(test.input, test.answer, b"\x00\xff\xfe not valid\n")
        cases.append({
            "name": "malformed rejected without crash",
            "expected": "reject",
            "actual": "crash" if result["verdict"] == "ERROR" else result["verdict"],
            "pass": result["verdict"] in ("WA", "FAIL") and not result["timedOut"],
            "message": result.get("message", "")[:500],
        })

        record("empty output rejected", "WA", run(test.input, test.answer, b""))
        record("extra output rejected", "WA", run(test.input, test.answer, answer + b"\nEXTRA TOKENS THAT SHOULD NOT BE ACCEPTED\n"))

        for valid in sorted((package.root / "data" / "valid_output").glob("*.out")):
            record(f"valid_output/{valid.name} accepted", "AC", run(test.input, test.answer, valid.read_bytes()))
        for invalid in sorted((package.root / "data" / "invalid_output").glob("*.out")):
            record(f"invalid_output/{invalid.name} rejected", "WA", run(test.input, test.answer, invalid.read_bytes()))

        checker_stats = {
            "name": program.name,
            "contract": contract,
            "flags": flags,
            "source": rel,
            "cases": len(cases),
        }
    finally:
        shutil.rmtree(build, ignore_errors=True)
    failed = [case for case in cases if not case["pass"]]
    return {
        "status": "pass" if cases and not failed else "fail",
        "detail": f"{len(cases) - len(failed)}/{len(cases)} checker self-tests passed",
        "cases": cases,
        "program": checker_stats,
    }


def _transcript_text(result: dict) -> str:
    return "\n".join(
        f"{'>' if item.get('direction') == 'solution' else '<'} {item.get('text', '')}"
        for item in (result.get("transcript") or [])
    ) + "\n"


def interactive_selftest(slug: str) -> dict:
    """Run reference and wrong solutions against the interactor."""
    package = package_model.load(slug)
    if not package.is_interactive:
        return {"status": "skipped", "detail": "not an interactive problem", "cases": []}
    program = package.output_validator_program
    if program is None:
        return {"status": "fail", "detail": "interactive problems need output_validators/ (interactor)", "cases": []}
    build = workspace.ws_path(slug) / ".agent" / "build" / "interactive-selftest"
    shutil.rmtree(build, ignore_errors=True)
    build.mkdir(parents=True, exist_ok=True)
    cases = []
    try:
        compiled_interactor = _build_program(slug, program.path.relative_to(package.root).as_posix(), build, program=program)
        if not compiled_interactor["ok"]:
            return {"status": "fail", "detail": compiled_interactor["error"], "cases": []}
        from author_studio.judging.verify import _solutions, _compile  # local import avoids a module cycle

        accepted = [s for s in _solutions(slug) if s["kind"] == "accepted"]
        negative = [s for s in _solutions(slug) if s["kind"] == "negative"]
        if not accepted:
            return {"status": "fail", "detail": "interactive problems need an accepted reference", "cases": []}
        test = next((item for item in package.tests if item.kind == "secret"), None) or (package.tests[0] if package.tests else None)
        if test is None:
            return {"status": "fail", "detail": "interactive problems need at least one test", "cases": []}
        testlib = program.contract == "testlib-interactive"
        accepted_codes = [0] if testlib else [SPEC_AC]
        answer_path = test.answer if test.answer is not None else build / "empty.ans"
        if not answer_path.is_file():
            answer_path.write_text("", "utf-8")
        transcript_program = package.transcript_checker_program
        transcript_argv = None
        if transcript_program is not None:
            compiled_transcript = _build_program(
                slug, transcript_program.path.relative_to(package.root).as_posix(), build, program=transcript_program
            )
            if compiled_transcript.get("ok"):
                transcript_argv = compiled_transcript["argv"]
            else:
                cases.append({
                    "name": "transcript checker", "expected": "compiled", "actual": "CE", "pass": False,
                    "message": compiled_transcript.get("error", "")[:500],
                })

        def run_case(solution: dict, expected: str) -> None:
            compiled = _compile(slug, solution, build)
            if not compiled["ok"]:
                cases.append({"name": f"{expected} {solution['path']}", "expected": expected, "actual": "CE", "pass": False, "message": compiled.get("error", "")[:500]})
                return
            transcript_path = build / f"transcript-{solution['path'].replace('/', '_')}.log"
            if testlib:
                validator_argv = compiled_interactor["argv"] + [str(test.input), str(transcript_path)]
            else:
                feedback = build / "feedback"
                feedback.mkdir(exist_ok=True)
                validator_argv = compiled_interactor["argv"] + [str(test.input), str(answer_path), str(feedback) + os.sep]
            result = winutil.run_interactive(
                compiled["argv"], validator_argv, cwd=workspace.ws_path(slug), timeout=20,
                accepted_exit_codes=accepted_codes,
            )
            transcript = _transcript_text(result)
            if transcript.strip() and not transcript_path.is_file():
                transcript_path.write_text(transcript, "utf-8")
            actual = "AC" if result["ok"] else ("TIMEOUT" if result["timedOut"] else "WA")
            cases.append({
                "name": f"{expected} {solution['path']}",
                "expected": "AC" if expected == "reference" else "rejected",
                "actual": actual,
                "pass": result["ok"] if expected == "reference" else not result["ok"],
                "message": "",
                "transcript": result["transcript"][:200],
                "validatorReturncode": result.get("validatorReturncode"),
            })
            if transcript_argv is not None:
                run_checker = _run_checker(
                    transcript_argv, transcript_program.contract, test.input, answer_path,
                    transcript.encode("utf-8"), build, flags=transcript_program.flags,
                )
                checker_expected = "AC" if expected == "reference" else "WA"
                cases.append({
                    "name": f"transcript checker {expected} {solution['path']}",
                    "expected": checker_expected,
                    "actual": run_checker["verdict"],
                    "pass": run_checker["verdict"] == checker_expected,
                    "message": run_checker.get("message", "")[:500],
                })

        for solution in accepted:
            run_case(solution, "reference")
        for solution in negative:
            run_case(solution, "negative")
        if transcript_program is not None:
            # A forged transcript must be rejected by the transcript checker.
            if transcript_argv is not None and accepted:
                compiled = _compile(slug, accepted[0], build)
                if compiled["ok"]:
                    forged = "> forged\n< forged\n"
                    result = _run_checker(
                        transcript_argv, transcript_program.contract, test.input, answer_path,
                        forged.encode("utf-8"), build, flags=transcript_program.flags,
                    )
                    cases.append({
                        "name": "transcript checker rejects forged transcript",
                        "expected": "WA",
                        "actual": result["verdict"],
                        "pass": result["verdict"] == "WA",
                        "message": result.get("message", "")[:500],
                    })
    finally:
        shutil.rmtree(build, ignore_errors=True)
    failed = [case for case in cases if not case["pass"]]
    return {
        "status": "pass" if cases and not failed else "fail",
        "detail": f"{len(cases) - len(failed)}/{len(cases)} interactive self-tests passed",
        "cases": cases,
        "program": {
            "name": program.name,
            "contract": program.contract,
            "transcriptChecker": transcript_program.name if transcript_program else "",
        },
    }
