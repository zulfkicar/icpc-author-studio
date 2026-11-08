# Judge0 evaluation

Question: should Judge0 be self-hosted and embedded as the execution/IDE backend?

## Verdict

**Not as the verification authority.** Judge0 is a good fit for *quick-run* only,
and it is now available as an optional adapter (`judge0_adapter.py`) behind
`AUTHOR_AGENT_JUDGE0_URL`. The deterministic verifier continues to use the
Isolate-style bwrap worker.

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

Judge0 also adds PostgreSQL, Redis, a server and one or more workers. That is a
large operational surface for a local authoring tool whose current worker already
enforces:

- read-only system root,
- no network namespace,
- hidden `/app/workspaces`,
- CPU / wall-time / address-space / stack / file-size / open-file / process caps,
- no provider key.

## Where Judge0 fits

Use it as an optional IDE quick-run service. Add the URL in **Settings ? Judge0
URL** and a **Judge0** button appears in the Run panel for runnable files. It
posts to `/api/workspaces/<slug>/judge0/run`, which reads the workspace source
and calls the adapter. It never writes a verifier report or export gate.

Programmatically:

```python
from judge0_adapter import quick_run
result = quick_run(source, "cpp", stdin="2 3", base_url="http://127.0.0.1:2358")
```

The adapter normalises `status`, `stdout`, `stderr`, `compileOutput`, `time`,
`memory`, and marks every result `verificationAuthority: False`.

## Optional self-hosting

The official Judge0 deployment uses PostgreSQL, Redis, `judge0/judge0` server
and workers. A minimal compose file is provided in
`docker-compose.judge0.yml`; it is **not** part of the default `docker compose up`
and is not used by verification. Start it explicitly:

```bash
docker compose -f docker-compose.judge0.yml up -d
```

Then set `AUTHOR_AGENT_JUDGE0_URL=http://127.0.0.1:2358` for the app.

## Evidence

`qa/test_judge0_adapter.py` runs the adapter and `run_file` against a local fake
Judge0 server and checks accepted output, compilation errors, metadata
normalisation, the workspace file path and the `verificationAuthority: False`
contract. `qa/test_ui_contracts.py` checks that the Run-panel button and
`runJudge0` wiring are present. The UI button is only shown when a Judge0 URL is
configured.

End-to-end route evidence (fake Judge0 on the executor network):

```text
POST /api/settings {judge0Url: http://executor:2358}
POST /api/workspaces/sum-test/judge0/run {path: submissions/accepted/ref.cpp}
  ok=true, stdout=judge0-route-ok, status=Accepted,
  verificationAuthority=false
```
