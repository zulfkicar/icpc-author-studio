"""Reference behaviors used by the *fake worker* only.

These Python implementations simulate what a compiled candidate would do on a
bounded domain.  They are not executed as part of the production diagnostic and
they establish fake-worker mechanics, not containment or C++ correctness.
"""
from __future__ import annotations

import bisect

from . import Instance


class CandidateFailure(RuntimeError):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


def earliest_finish_greedy(instance: Instance, *, touching: bool = True) -> int:
    """Pick the earliest-finishing compatible job repeatedly.

    Correct for unweighted cardinality, not for maximum reward.
    """
    jobs = sorted(instance.jobs, key=lambda job: (job.finish, job.start))
    total = 0
    last_finish = None
    for job in jobs:
        if last_finish is None or job.start > last_finish or (touching and job.start == last_finish):
            total += job.reward
            last_finish = job.finish
    return total


def dp_strict(instance: Instance) -> int:
    """DP whose predecessor search uses ``finish < start`` (the endpoint defect)."""
    jobs = sorted(instance.jobs, key=lambda job: (job.finish, job.start, job.reward))
    finishes = [job.finish for job in jobs]
    dp = [0] * (len(jobs) + 1)
    for index, job in enumerate(jobs, start=1):
        p = bisect.bisect_left(finishes, job.start, 0, index - 1)
        dp[index] = max(dp[index - 1], job.reward + dp[p])
    return dp[-1]


def dp_correct(instance: Instance) -> int:
    jobs = sorted(instance.jobs, key=lambda job: (job.finish, job.start, job.reward))
    finishes = [job.finish for job in jobs]
    dp = [0] * (len(jobs) + 1)
    for index, job in enumerate(jobs, start=1):
        p = bisect.bisect_right(finishes, job.start, 0, index - 1)
        dp[index] = max(dp[index - 1], job.reward + dp[p])
    return dp[-1]


def dp_base_error(instance: Instance) -> int:
    """Actual base/indexing error: predecessor index is shifted by one."""
    jobs = sorted(instance.jobs, key=lambda job: (job.finish, job.start, job.reward))
    finishes = [job.finish for job in jobs]
    dp = [0] * (len(jobs) + 1)
    for index, job in enumerate(jobs, start=1):
        p = bisect.bisect_right(finishes, job.start, 0, index - 1)
        # BUG: p+1 reads a different prefix, not the compatible prefix.
        dp[index] = max(dp[index - 1], job.reward + dp[min(p + 1, index - 1)])
    return dp[-1]


def sweep_line_correct(instance: Instance) -> int:
    """A correct, unconventional coordinate sweep rather than binary search."""
    coordinates = sorted({0, *(job.start for job in instance.jobs), *(job.finish for job in instance.jobs)})
    index_of = {value: i for i, value in enumerate(coordinates)}
    ending: dict[int, list] = {}
    for job in instance.jobs:
        ending.setdefault(index_of[job.finish], []).append(job)
    best = [0] * len(coordinates)
    for i in range(1, len(coordinates)):
        best[i] = best[i - 1]
        for job in ending.get(i, []):
            candidate = job.reward + best[index_of[job.start]]
            best[i] = max(best[i], candidate)
    return best[-1]


def compile_error(instance: Instance) -> int:
    raise CandidateFailure("compile_error", "simulated compiler failure")


def runtime_error(instance: Instance) -> int:
    raise CandidateFailure("candidate_runtime_error", "simulated candidate crash")


BEHAVIORS = {
    "earliest_finish_greedy": earliest_finish_greedy,
    "greedy_closed": lambda instance: earliest_finish_greedy(instance, touching=False),
    "dp_strict": dp_strict,
    "dp_correct": dp_correct,
    "dp_base_error": dp_base_error,
    "sweep_line_correct": sweep_line_correct,
    "narrow_half_open": lambda instance: dp_correct(instance) % (1 << 31),
    "narrow_closed": lambda instance: dp_strict(instance) % (1 << 31),
    "compile_error": compile_error,
    "runtime_error": runtime_error,
}
