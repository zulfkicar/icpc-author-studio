"""ICPC test-group scoring and dependency evaluation.

Groups are declared in ``test_group.yaml`` (or a map-of-maps ``testdata.yaml``)::

    easy:
      points: 40
    hard:
      points: 60
      depends: [easy]

A group is awarded its points only when every test in the group passes and
every dependency group passes. This is the usual ICPC subtask semantics.
"""
from __future__ import annotations

from dataclasses import dataclass

from author_studio.packages import package_model


@dataclass
class GroupResult:
    name: str
    points: float
    passed: bool
    blocked_by: list[str]
    depends: list[str]
    tests: int
    passed_tests: int

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "points": self.points,
            "passed": self.passed,
            "blockedBy": self.blocked_by,
            "depends": self.depends,
            "tests": self.tests,
            "passedTests": self.passed_tests,
        }


def _points(config: dict) -> float:
    try:
        return float(config.get("points", 1.0))
    except (TypeError, ValueError):
        return 0.0


def _depends(config: dict) -> list[str]:
    raw = config.get("depends", config.get("dependencies", []))
    if isinstance(raw, str):
        raw = [raw]
    return [str(item) for item in (raw or [])]


def evaluate(package: package_model.Package, verdicts: dict[str, str]) -> dict:
    """Score one solution.

    ``verdicts`` maps test relative paths (``data/secret/x.in``) to verdicts.
    """
    groups = package.groups()
    if not groups:
        secret = [test for test in package.tests if test.kind == "secret"]
        passed = sum(1 for test in secret if verdicts.get(test.relative) == "AC")
        all_passed = bool(secret) and passed == len(secret)
        return {
            "score": 1.0 if all_passed else 0.0,
            "maxScore": 1.0,
            "allPassed": all_passed,
            "groups": [],
            "mode": "pass-fail",
        }

    by_group: dict[str, list[package_model.TestCase]] = {}
    for test in package.tests:
        if test.kind != "secret":
            continue
        by_group.setdefault(test.group, []).append(test)

    results: dict[str, GroupResult] = {}

    def resolve(name: str, stack: tuple[str, ...] = ()) -> GroupResult:
        if name in results:
            return results[name]
        config = groups.get(name) if isinstance(groups.get(name), dict) else {}
        depends = _depends(config)
        tests = by_group.get(name, [])
        passed_tests = sum(1 for test in tests if verdicts.get(test.relative) == "AC")
        own_pass = bool(tests) and passed_tests == len(tests)
        blocked: list[str] = []
        for dep in depends:
            if dep in stack:
                blocked.append(dep)
                continue
            dep_result = resolve(dep, stack + (name,))
            if not dep_result.passed:
                blocked.append(dep)
        passed = own_pass and not blocked
        result = GroupResult(
            name=name,
            points=_points(config),
            passed=passed,
            blocked_by=blocked,
            depends=depends,
            tests=len(tests),
            passed_tests=passed_tests,
        )
        results[name] = result
        return result

    for name in groups:
        resolve(name)

    ordered = [results[name] for name in groups]
    score = sum(item.points for item in ordered if item.passed)
    max_score = sum(item.points for item in ordered)
    return {
        "score": score,
        "maxScore": max_score,
        "allPassed": all(item.passed for item in ordered) if ordered else False,
        "groups": [item.to_dict() for item in ordered],
        "mode": "groups",
    }
