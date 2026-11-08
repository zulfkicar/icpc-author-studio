# Eval results

Real vendor provider: `configured-model` via
`https://api.example.invalid/v1`. Both fixtures were authored from the idea
only, then judged by the deterministic verifier. The eval rejects export
approvals, so a verified package is never published.

## Claim or Concede

Command:

```text
python eval/run_eval.py --fixture claim --turns 2 --timeout 1200 --max-rounds 32
```

Result (`docs/evidence/claim-verified.json`):

```text
reportStatus : verified
turnsUsed    : 2
rounds       : 64
toolCalls    : 108
wallSeconds  : 578.73
usage        : 3,119,413 input / 65,218 output
costUsd      : $1.267607
tests        : 38 (2 sample, 36 secret)
accepted     : 2
negative     : 4
limits       : 1 s / 256 MiB
errors       : []
```

The final agent text records **18/18 ICPC spec checks, 0 warnings**, both
accepted references AC on all 38 tests, all four negatives killed by secret
tests, and validator results 38/38 with exit code 42. It also found and fixed a
real answer-file CRLF bug instead of weakening the tests.

## Sum

Command:

```text
python eval/run_eval.py --fixture sum --turns 2 --timeout 600 --max-rounds 24
```

Result (`docs/evidence/sum-verified.json`):

```text
reportStatus : verified
turnsUsed    : 2
rounds       : 47
toolCalls    : 94
wallSeconds  : 295.03
usage        : 1,325,603 input / 31,515 output
costUsd      : $0.544374
tests        : 29 (3 sample, 26 secret)
accepted     : 1
negative     : 3
limits       : 1 s / 256 MiB
errors       : []
```

The workspaces are removed by the eval after verification. The JSON files here
are the evidence, not a claim that a live DOMjudge import was tested.

## Isolate verifier revalidation

After moving the deterministic verifier to the real Isolate worker, the
`eval-claim-or-concede-2` workspace (86 tests) was verified directly:

```text
job          : 6004dc1eb8e6
elapsed      : 650.8 s (under the 15-minute budget)
status       : failed
errors       : Limits measured: run Measure limits after the reference and tests are ready
tests        : 86 (3 sample, 83 secret)
accepted     : 2
negative     : 4
```

The verifier completed the full test matrix; the package failed only because
the eval fixture never ran the **Measure limits** step. The earlier
15-minute-budget failure was the Isolate copy regression (23 MB per run), now
fixed by demand-driven `data/` copying. This is a verifier performance result,
not a claim that the package is export-ready.

## Context probe

`qa/probe_long_context.py` (opt-in, real provider):

```text
input_tokens: 500045
output_tokens: 19
text: long-ok
```
