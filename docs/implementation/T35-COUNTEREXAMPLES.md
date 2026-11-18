# Counterexample replay and reduction

Open a current weighted scheduling campaign counterexample in Studio chat.
Choose **Replay original** to run the saved input again against the recorded
C++ source and endpoint rule. Choose **Replay and reduce** to check the
original mismatch first, then try smaller inputs. Its report keeps both the
original and the best smaller case. You can copy either input after reopening
the conversation.

## What counts as the same failure

- Exact replay independently recomputes the original expected answer and
  checks that the candidate returns the same recorded wrong answer.
- If the recorded wrong answer matches the optimum under the other endpoint
  rule, a smaller case must preserve that relationship and the direction of
  the mismatch. The receipt records this observed behavior.
- For other numeric mismatches, the reducer preserves the exact expected and
  actual pair. Each proposal must pass the same scheduling input validator.

The reducer tries removing jobs, compacting coordinates without changing their
relative order, and simplifying rewards. The result is the smallest case this
search confirmed within its budget. The report gives the termination reason
and the list of attempted checks.

## Limits and source changes

Replay reserves one case and five seconds by default. Reduction reserves up to
16 cases and 15 seconds. Each action allows 4,096 oracle subsets including
oracle controls. Remaining run limits can lower the execution allowance. The
same request ID returns the saved result without another execution.

When the candidate or rule changes, run a fresh campaign for the new version.
An earlier result remains visible with its historical status. A changed
answer, failed oracle check, or incomplete execution leaves the original
record available. The worker and its execution mode are recorded with the new
result.

## Verification

```powershell
python -m pytest qa/engine_contracts/test_t35_counterexamples.py -q
$env:AUTHOR_AGENT_T35_TEST_ISOLATE_URL = 'http://127.0.0.1:8790'
$env:AUTHOR_AGENT_T35_TEST_BROWSER = '1'
python -m pytest qa/engine_contracts/test_t35_counterexamples.py -q
```

The optional checks use a local Isolate worker for compiled C++ and the
repository's headless Chrome harness for chat actions and reload. The campaign
planner is scripted. Replay and reduction work directly from saved evidence.

The local verification passed all seven T35 tests. The compiled flow reduced a
four-booking endpoint counterexample to two bookings. The Chrome check used
both chat buttons and confirmed the two saved inputs after a reload.
