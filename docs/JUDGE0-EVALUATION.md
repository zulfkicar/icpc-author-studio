# Judge0 evaluation

Question: should Judge0 be self-hosted and embedded as the execution/IDE backend?

## Verdict

**Live and embedded as a quick-run/IDE backend — not as the verification
authority.** A real Judge0 CE 1.13.1 stack is running in this Docker project
(server, worker, PostgreSQL, Redis), and the app can call it. The deterministic
verifier continues to use the Isolate worker / bwrap executor because Judge0
does not orchestrate the ICPC package contracts.

## Live stack

```bash
docker compose -f docker-compose.judge0.yml up -d
curl http://127.0.0.1:2358/about
```

Services:

- `judge0-server` — `judge0/judge0:1.13.1`, port `127.0.0.1:2358`.
- `judge0-worker` — privileged worker with Isolate 1.8.1 and the compiler set.
- `judge0-db` — PostgreSQL 13.
- `judge0-redis` — Redis 6.

The server and worker share `/box` and `/var/local/lib/isolate`. The server is
privileged because this Judge0 release also processes jobs in the web process;
the worker remains privileged. Judge0 CE 1.13.1 targets cgroup v1, so the
adapter sets `enable_per_process_and_thread_time_limit` and
`enable_per_process_and_thread_memory_limit`, which makes Isolate use its
rlimit path and works on the cgroup v2 host here.

A live C++ submission returns:

```text
status=Accepted, stdout=judge0-live, time=0.004, memory=3192
```

## Why Judge0 is not the verifier

The ICPC Problem Package Format requires:

- `input_validators/` to exit **42** on valid input.
- custom output validators to be invoked as
  `<validator> input answer feedback_dir [flags]` with team output on **stdin**
  and exit **42** (accepted) / **43** (wrong answer).
- interactive problems to run an interactor that talks to the submission over
  stdin/stdout and reports the verdict.
- `.interaction` transcripts and per-test feedback files.

Judge0's submission API runs one program against one stdin and compares stdout
or returns the raw streams. Community Edition does not orchestrate testlib
interactors, output-validator feedback directories, or package validator flags.
Putting Judge0 behind the verifier would require a second orchestration layer and
would make two execution authorities disagree.

## Where Judge0 fits

Use it as an IDE quick-run service. Add the URL in **Settings → Judge0 URL** and
a **Judge0** button appears in the Run panel for runnable files. It posts to
`/api/workspaces/<slug>/judge0/run`, which reads the workspace source and calls
the adapter. It never writes a verifier report or export gate.

Programmatically:

```python
from judge0_adapter import quick_run
result = quick_run(source, "cpp", stdin="2 3", base_url="http://judge0-server:2358")
```

The adapter normalises `status`, `stdout`, `stderr`, `compileOutput`, `time`,
`memory`, and marks every result `verificationAuthority: False`.

## Evidence

- `qa/test_judge0_adapter.py` — fake-server adapter contract.
- `qa/test_live_judge0.py` — live stack: C++ accepted and workspace file run.
- `qa/test_ui_contracts.py` — Run-panel button and `runJudge0` wiring.
- CDP: `judge0Visible=true`.

Live app route:

```text
POST /api/settings {judge0Url: http://judge0-server:2358}
POST /api/workspaces/sum-test/judge0/run
  {path: submissions/accepted/ref.cpp, stdin: "2 3"}
  -> ok=true, stdout=5, status=Accepted, verificationAuthority=false
```
