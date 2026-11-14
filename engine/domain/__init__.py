"""Weighted interval scheduling: semantics, validator, independent oracle.

The oracle enumerates every labelled subset and rejects overlaps by checking
selected pairs directly under the declared endpoint convention.  It never reuses
the DP recurrence or its predecessor search, so a DP predecessor defect cannot
silently agree with it.

The profile is exact-integer batch, ``1 <= n <= 200000``, integer
``0 <= start < finish <= 10^9``, ``1 <= reward <= 10^9``, labelled jobs,
duplicates allowed, half-open occupancy, empty selection allowed.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Iterable, Literal

MAX_N = 200_000
MAX_COORD = 10 ** 9
MAX_REWARD = 10 ** 9
MAX_SUM = 2 * 10 ** 14

Semantics = Literal["half_open", "closed"]


class InvalidInput(ValueError):
    pass


@dataclass(frozen=True)
class Job:
    start: int
    finish: int
    reward: int
    label: int


@dataclass(frozen=True)
class Instance:
    jobs: tuple[Job, ...] = field(default_factory=tuple)

    @property
    def n(self) -> int:
        return len(self.jobs)


def parse_instance(text: str) -> Instance:
    tokens = text.split()
    if not tokens:
        raise InvalidInput("empty input")
    try:
        n = int(tokens[0])
    except ValueError as exc:
        raise InvalidInput("n is not an integer") from exc
    if n < 1:
        raise InvalidInput("n must be >= 1")
    if n > MAX_N:
        raise InvalidInput(f"n exceeds {MAX_N}")
    if len(tokens) != 1 + 3 * n:
        raise InvalidInput(f"expected {1 + 3 * n} tokens, got {len(tokens)}")
    jobs: list[Job] = []
    cursor = 1
    for label in range(n):
        try:
            start, finish, reward = (int(tokens[cursor + k]) for k in range(3))
        except ValueError as exc:
            raise InvalidInput("job fields must be integers") from exc
        cursor += 3
        if not (0 <= start < finish <= MAX_COORD):
            raise InvalidInput("require 0 <= start < finish <= 1e9")
        if not (1 <= reward <= MAX_REWARD):
            raise InvalidInput("require 1 <= reward <= 1e9")
        jobs.append(Job(start, finish, reward, label))
    total = sum(job.reward for job in jobs)
    if total > MAX_SUM:
        raise InvalidInput("total reward exceeds the declared 2*10^14 envelope")
    return Instance(tuple(jobs))


def render_instance(instance: Instance) -> str:
    lines = [str(instance.n)]
    for job in instance.jobs:
        lines.append(f"{job.start} {job.finish} {job.reward}")
    return "\n".join(lines) + "\n"


def compatible(a: Job, b: Job, semantics: Semantics = "half_open") -> bool:
    if semantics == "half_open":
        return a.finish <= b.start or b.finish <= a.start
    if semantics == "closed":
        return a.finish < b.start or b.finish < a.start
    raise InvalidInput(f"unknown endpoint semantics {semantics!r}")


def oracle_subset(instance: Instance, *, semantics: Semantics = "half_open",
                  max_jobs: int = 22) -> dict:
    """Independently derive the optimum by enumerating labelled subsets.

    Pairwise overlap is checked directly; no finish sorting, recurrence or
    predecessor search is used.  Bounded because 2^n is only tractable on a
    small domain, which is exactly what the diagnostic claims.
    """
    n = instance.n
    if n > max_jobs:
        raise InvalidInput(f"oracle enumeration is bounded to {max_jobs} jobs, got {n}")
    best_value = 0
    best_mask = 0
    best_subset: list[int] = []
    enumerations = 0
    for mask in range(1 << n):
        enumerations += 1
        selected = [i for i in range(n) if mask & (1 << i)]
        feasible = True
        for i, j in itertools.combinations(selected, 2):
            if not compatible(instance.jobs[i], instance.jobs[j], semantics):
                feasible = False
                break
        if not feasible:
            continue
        value = sum(instance.jobs[i].reward for i in selected)
        if value > best_value:
            best_value = value
            best_mask = mask
            best_subset = selected
    return {
        "value": best_value,
        "best_subset": best_subset,
        "best_mask": best_mask,
        "enumerations": enumerations,
        "semantics": semantics,
        "producer": "subset-enumeration-v1",
    }


def dp_reference(instance: Instance) -> int:
    """A second, recurrence-based reference used only for cross-checks.

    Not the oracle.  Requires nonnegative rewards and half-open semantics.
    """
    import bisect

    jobs = sorted(instance.jobs, key=lambda job: (job.finish, job.start, job.reward))
    finishes = [job.finish for job in jobs]
    dp = [0] * (len(jobs) + 1)
    for index, job in enumerate(jobs, start=1):
        p = bisect.bisect_right(finishes, job.start, 0, index - 1)
        dp[index] = max(dp[index - 1], job.reward + dp[p])
    return dp[-1]


FINITE_TYPES: tuple[tuple[int, int, int], ...] = (
    (0, 1, 1),
    (1, 2, 1),
    (0, 2, 3),
    (0, 1, 3),
    (1, 2, 3),
    (0, 2, 1),
)


def finite_domain(types: Iterable[tuple[int, int, int]] = FINITE_TYPES,
                  lengths: Iterable[int] = (1, 2, 3, 4), *, limit: int | None = None) -> list[Instance]:
    """All ordered sequences with repetition of the declared job types.

    1..4 jobs over the six types yields 6 + 36 + 216 + 1296 = 1554 instances.
    This domain deliberately covers touching, nesting, duplicate labels, order
    and weight changes; it is not exhaustive over full input limits.
    """
    type_list = tuple(types)
    out: list[Instance] = []
    for length in lengths:
        for combination in itertools.product(type_list, repeat=length):
            if limit is not None and len(out) >= limit:
                return out
            out.append(Instance(tuple(Job(s, f, r, i) for i, (s, f, r) in enumerate(combination))))
    return out


def witness_two_touching() -> Instance:
    return Instance((Job(0, 1, 5, 0), Job(1, 2, 7, 1)))


def witness_weighted_greedy() -> Instance:
    """The hand-derived refutation of earliest-finish for weighted intervals."""
    return Instance((Job(0, 2, 6, 0), Job(2, 4, 6, 1), Job(0, 4, 13, 2)))


def witness_contained_pair() -> Instance:
    """A pair where one job is strictly contained in another."""
    return Instance((Job(0, 3, 5, 0), Job(1, 2, 4, 1), Job(0, 4, 9, 2)))


def witness_large_reward() -> Instance:
    return Instance((Job(0, 1, 10 ** 9, 0), Job(1, 2, 10 ** 9, 1), Job(2, 3, 10 ** 9, 2)))


def witness_duplicate_jobs() -> Instance:
    return Instance((Job(0, 2, 3, 0), Job(0, 2, 3, 1), Job(2, 3, 4, 2)))
