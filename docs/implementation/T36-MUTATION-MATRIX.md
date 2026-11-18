# Test-by-mutant matrix

Open a current weighted scheduling campaign in Studio chat and choose
**Run mutation matrix**. The matrix uses the campaign's saved inputs and
endpoint rule. It includes a correct scheduling solution as a control and three
built-in mutants covering the touching rule, earliest-finish greedy, and a
31-bit reward total. You can also select up to two current C++ artifacts from
the conversation to test as mutants.

Each row gives the saved test and independently checked expected answer. The
candidate columns show observed answers or the reason execution could not be
scored. The report opens from chat and stays available after reload.

## How to read the results

| Result | What the check established |
| --- | --- |
| Caught | At least one legal test produced a complete integer result that disagreed with the independent answer. The report identifies the exact test IDs. |
| Survived | The candidate agreed on every test in the saved campaign input set. A surviving candidate may be correct, or the suite may lack a case that exposes its defect. |
| Compile error | The candidate failed to build. This is recorded separately from the kill count. |
| Unresolved | At least one required comparison is missing or unscorable. Cells distinguish worker failures, runtime or resource errors, invalid output and tests that did not run. |

The host validates each selected input and recomputes its expected answer with
the subset oracle. The control runs first. Any control discrepancy or failed
control execution stops mutant scoring for that matrix. The matrix report
records source hashes, the original manifest, the worker, and the outcome of
each column.

The default limits reserve up to 32 candidate-test executions and 20 seconds,
with a separate oracle limit of 16,384 subsets. A smaller limit may omit a
suffix of the saved suite. Those rows remain visible as **Not run**, and a
candidate with unchecked rows has unresolved survival. A completed numeric
mismatch can still establish a kill within a partially checked suite.

## Verification

```powershell
python -m pytest qa/engine_contracts/test_t36_mutation_matrix.py -q
$env:AUTHOR_AGENT_T36_TEST_ISOLATE_URL = 'http://127.0.0.1:8790'
$env:AUTHOR_AGENT_T36_TEST_BROWSER = '1'
python -m pytest qa/engine_contracts/test_t36_mutation_matrix.py -q
```

The opt-in worker checks compile the control, mutants and authored fixtures in
local Isolate. The Chrome check starts the matrix in chat and checks that the
table and survivor verdict are available after reload. The campaign planner is
scripted, and the matrix uses the saved inputs directly.

The local T36 run passed all eight checks. Real C++ runs exercised both
endpoint rules. The touching and nested cases caught the reversed endpoint
rule, and the wide-reward case caught the narrow total. An authored correct
alternative survived and a separate authored compile failure recorded zero
kills. Chrome also verified that the table scrolls within the chat card at
390 px.
