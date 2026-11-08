# Isolate backend

A real Isolate worker is running alongside the app. It is not a simulation and
it is not bwrap: it uses Isolate 1.8.1 from the Judge0 CE image.

## Service

`docker-compose.yml`:

```yaml
isolate-worker:
  image: judge0/judge0:1.13.1
  user: "1000:999"
  command: ["/usr/local/python-3.8.1/bin/python3", "/app/isolate_worker.py"]
  privileged: true
  security_opt: [seccomp=unconfined, apparmor=unconfined]
  networks: [sandbox, default]
  volumes:
    - ./isolate_worker.py:/app/isolate_worker.py:ro
    - isolate-box:/var/local/lib/isolate
```

`/app/isolate_worker.py` exposes:

```text
GET  /health
POST /isolate/run     # source-run API
POST /run             # executor-compatible argv/workspace API
POST /interact        # two-process interactive harness

POST /run
  {"argv": ["g++", "-O2", "-o", "/app/workspaces/p/.agent/build/a.exe", "a.cpp"],
   "cwd": "/app/workspaces/p", "stdin": "", "timeout": 10, "measure": true}
  -> {"ok": true, "returncode": 0, "stdout": "...", "stderr": "",
      "ms": 12, "peakRssBytes": 3200000}
```

The worker copies the selected workspace into an Isolate box, rewrites workspace
paths to `/box/...`, runs the command under Isolate, then syncs compiled
artifacts and test outputs back. `/interact` runs a small Python harness inside
the box that connects the validator and solution pipes, records the transcript,
and enforces the wall-clock timeout.

The app calls it through `isolate_client.py` and the Run-panel **Isolate**
button (`/api/workspaces/<slug>/isolate/run`). The app container is on the
internal `sandbox` network, so the worker has no external network.

The default `AUTHOR_AGENT_EXECUTOR_URL` is `http://isolate-worker:8790`, so the
same worker receives the verifier's `argv`/workspace runs on `/run` and the
interactive harness on `/interact`. The bwrap executor remains at
`AUTHOR_AGENT_BWRAP_EXECUTOR_URL` for the LaTeX statement PDF and as a
fallback.

## Limits and isolation

- Isolate box per request (`--box-id`), cleaned up after each run.
- CPU time (`-t`), wall time (`-w`), address space (`-m`), file size (`-f`),
  stack (`-k`) and processes (`-p120`).
- Read-only system root; only the box is writable.
- No network namespace sharing (`--share-net` is not used).
- `seccomp=unconfined` and `apparmor=unconfined` are required for Isolate's
  mount namespace and `pivot_root` in this Docker/WSL environment, just as
  `SYS_ADMIN` is required by the bwrap executor.
- The worker runs as UID 1000 and has no provider key or app source.

## Live evidence

`qa/test_isolate_worker.py` passes:

```text
PASS isolate health
PASS isolate cpp accepted
PASS isolate metadata
PASS isolate not authority
PASS isolate compile error
PASS isolate wall time
PASS isolate memory limit
PASS isolate network blocked
PASS isolate root read-only
PASS isolate file-size limit
ISOLATE WORKER TESTS PASSED
```

App route:

```text
POST /api/workspaces/sum-test/isolate/run
  {path: submissions/accepted/ref.cpp, stdin: "2 3"}
  -> ok=true, stdout=5, status=OK,
     isolate=The process isolator 1.8.1, memory=3244,
     verificationAuthority=false
```

Verifier evidence through the Isolate `/run` and `/interact` endpoints:

```text
standard sum-test -> status=verified
testlib checker/interactor -> TESTLIB FIXTURE TESTS PASSED
interactive transcript -> INTERACTIVE TESTS PASSED
executor limits -> EXECUTOR LIMIT TESTS PASSED
```

The app's default `AUTHOR_AGENT_EXECUTOR_URL` points at the Isolate worker, so the
deterministic verifier, checkers, interactors and quick runs execute through
Isolate. The bwrap executor remains the `AUTHOR_AGENT_BWRAP_EXECUTOR_URL` target
for the statement PDF/LaTeX step (it has TeX Live) and as a fallback.
