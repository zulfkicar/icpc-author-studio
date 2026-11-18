"""A separate, local sample conversation with real package files."""
import hashlib
import threading

import studio
import workspace
from engine.domain import render_instance, witness_weighted_greedy
from engine.service import SAMPLE_PROVIDER

TITLE = "Sample · Canal Bookings"
IDEA = "Help me develop profitable canal bookings with starting and ending times and a reward."
SOURCE = "submissions/accepted/reference.py"
GREEDY = """import sys

_, *rows = sys.stdin.read().splitlines()
jobs = sorted((tuple(map(int, row.split())) for row in rows), key=lambda job: (job[1], job[0]))
total, finish = 0, 0
for start, end, reward in jobs:
    if start >= finish:
        total, finish = total + reward, end
print(total)
"""
FIXED = """from bisect import bisect_right
import sys

_, *rows = sys.stdin.read().splitlines()
jobs = sorted((tuple(map(int, row.split())) for row in rows), key=lambda job: job[1])
ends = [job[1] for job in jobs]
best = [0]
for index, (start, _, reward) in enumerate(jobs):
    compatible = bisect_right(ends, start, 0, index)
    best.append(max(best[-1], reward + best[compatible]))
print(best[-1])
"""
VALIDATOR = """import sys

try:
    n, *values = map(int, sys.stdin.read().split())
except ValueError:
    sys.exit(1)
valid = 1 <= n <= 100000 and len(values) == n * 3
valid = valid and all(0 <= a < b <= 10**9 and 0 <= w <= 10**9
                      for a, b, w in zip(values[::3], values[1::3], values[2::3]))
sys.exit(42 if valid else 1)
"""
STATEMENT = r"""\documentclass{article}
\begin{document}
\section*{Canal Bookings}
Choose canal bookings to maximise the total reward. The canal can serve
one booking at a time. Two bookings may touch at their endpoints.
\subsection*{Input}
The first line gives $n$ ($1\le n\le10^5$). Each of the next $n$ lines
contains $a,b,w$ ($0\le a<b\le10^9$, $0\le w\le10^9$).
\subsection*{Output}
Print the maximum total reward, allowing an empty selection.
\end{document}
"""
_LOCK = threading.Lock()


def create(chat, key, workspace_lock):
    path = chat._start_path(key)  # validate the client-supplied identifier
    with _LOCK:
        started = chat.start(IDEA, client_request_id="sample-" + path.stem,
                             model_provider=SAMPLE_PROVIDER, title=TITLE)
        run_id = started["runId"]
        link = studio.package_link(chat.service, run_id)
        if not link["slug"]:
            slug = workspace.create(TITLE, IDEA, {"author": "Author Studio Sample", "shortName": "CB",
                                                 "source": "Synthetic teaching fixture"})["slug"]
            for rel, content in {
                SOURCE: GREEDY, "submissions/wrong_answer/earliest_finish.py": GREEDY,
                "data/sample/01.in": "2\n0 2 6\n2 4 6\n", "data/sample/01.ans": "12\n",
                "data/secret/weighted.in": render_instance(witness_weighted_greedy()),
                "problem_statement/problem.en.tex": STATEMENT, "input_validators/validate.py": VALIDATOR,
            }.items():
                workspace.write_text(slug, rel, content, source="sample setup")
            workspace._write_json(workspace._state_dir(slug) / "studio-sample.json", {"runId": run_id})
            link = studio.link_package(chat.service, run_id, {"slug": slug, "expectedSlug": None,
                                                               "syncTitle": False}, workspace_lock)
        return {"runId": run_id, "slug": link["slug"], "title": TITLE}


def fix(service, run_id):
    if service.store(run_id).get_run(run_id)["model_provider"] != SAMPLE_PROVIDER:
        raise FileNotFoundError("This problem has no sample fix.")
    slug = studio.package_link(service, run_id)["slug"]
    marker = workspace._read_json(workspace._state_dir(slug) / "studio-sample.json", {}) if slug else {}
    if marker.get("runId") != run_id:
        raise FileNotFoundError("The sample's original package is no longer linked.")
    return {"slug": slug, "path": SOURCE, "baseHash": hashlib.sha256(GREEDY.encode()).hexdigest(),
            "content": FIXED}
