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
POST /isolate/run
  {"source": "...", "language": "cpp", "stdin": "...", "time": 2,
   "wallTime": 5, "memoryMb": 256, "fsizeMb": 4}

  -> {"ok": true, "status": "OK", "exit": 0, "stdout": "...",
      "stderr": "", "compileOutput": "", "time": 0.003,
      "wallTime": 0.005, "memory": 3128,
      "isolate": "The process isolator 1.8.1"}
```

The app calls it through `isolate_client.py` and the Run-panel **Isolate**
button (`/api/workspaces/<slug>/isolate/run`). The app container is on the
internal `sandbox` network, so the worker has no external network.

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

The deterministic verifier still uses the bwrap executor as its authority. The
Isolate worker is the real execution backend for quick runs and is the drop-in
path for a future verifier backend that needs Isolate's cgroup/namespace model.
