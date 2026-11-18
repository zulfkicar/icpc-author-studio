# T34 weighted scheduling campaigns

In a weighted interval scheduling conversation, settle whether intervals may
touch and paste the C++ solution into chat. Ask the agent to run a weighted
scheduling campaign against that solution. You can specify the seed, case
count and time budget. A campaign card links to the result and the exact inputs
it used. Configure a chat provider and the local Isolate worker for normal use.
[Local setup](../SETUP.md) · [Isolate backend](../ISOLATE-BACKEND.md)

## What the campaign checks

| Mode | Declared scope |
| --- | --- |
| Seeded | A reproducible sample of touching endpoints, nested and duplicate bookings, and rewards with a sum above the signed 32-bit limit. The default mixed family cycles through all three. |
| Exhaustive | Every ordered input over the registered six-job alphabet and requested lengths. Lengths 1 and 2 declare 42 inputs. A case or oracle cap may stop the run before it completes that grid. |

The host validates each generated input using the scheduling parser and
checks the oracle against hand-derived controls. The oracle enumerates
labelled subsets and checks pairwise compatibility. The candidate receives
only the input and cannot supply the expected answer. A mismatch receipt
records the input, its hash, expected and actual integers, source reference
and hash, and the selected endpoint rule. Agreement describes the checked
sample or finite grid.

## Limits and replay

- A plan declares `cases` (1–50), `wall_ms` (1,000–60,000), and
  `oracle_subsets` (1–65,536, including the oracle controls). The host applies
  any lower applicable worker, delegation and run limits before dispatch.
- The ledger reserves the selected cases and allocated execution time once
  per operation. The run has a default cumulative 60,000 ms campaign allowance.
  The adapter stops sending cases when its batch clock runs out. A timed-out
  transport can leave the last remote execution outcome unknown.
- The report distinguishes a counterexample, agreement, a limit, malformed
  output or worker failure. Invalid inputs and a failed oracle control stop
  before dispatch. The app fences results superseded by author steering.
- `GET /api/engine/runs/<run-id>/campaigns/<evidence-id>` returns the frozen
  manifest and result. The manifest includes the generator version, seed,
  endpoint rule, oracle controls, costs, and exact input text and hashes.
  Replay from the recorded inputs to preserve the same bytes.

## Verification

```powershell
python -m pytest qa/engine_contracts/test_t34_campaign.py -q
$env:AUTHOR_AGENT_T34_TEST_ISOLATE_URL = 'http://127.0.0.1:8790'
python -m pytest qa/engine_contracts/test_t34_campaign.py -q
```

The second run also compiles trusted C++ fixtures through local Isolate.
The end-to-end tests use scripted planning to control the candidate and
campaign scope. Held-out test seeds and expected results stay out of the
public sample. Provider quality and independent curator and author studies
are separate milestones on the [engine roadmap](../research/agentic-engine-portfolio/07-ROADMAP-AND-PORTFOLIO.md).

The 18 November 2026 local run passed all 20 campaign tests, including
three compiled HTTP journeys with Isolate 1.8.1. The strict predecessor
solution produced a touching-interval counterexample under the half-open
rule and agreed under the closed rule. The sweep-line solution agreed on
the half-open sample. Each journey started with the author's endpoint
choice and pasted code, then reopened the durable report from the chat.
The standard engine suite passed 342 tests and skipped the three opt-in
Isolate journeys covered by the local run.
