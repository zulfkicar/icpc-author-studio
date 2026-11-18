# V0–V3 run results

Latest deterministic run: **`evidence/20261115-133719`** (`LATEST.json`).
Host: Windows, Python 3.13.7, LangGraph 1.2.20, LangChain 1.4.9, SQLite
application/checkpoint databases. No live provider or isolate endpoint was used.

## Required command

```powershell
python scripts/run_v0_v3_suite.py
```

Exit code **0**. Recorded results:

| Item | Command | Exit | Evidence |
|---|---|---:|---|
| Deterministic engine suite | `python -m pytest qa/engine_contracts -q` | 0 | `pytest.txt`: **199 passed** |
| Reproducible demo | `python scripts/demo_v0_v3.py --json` | 0 | `demo.json` |
| Identity snapshot | `python scripts/capture_engine_identity.py --json` | 0 | `identity.json` |
| Rendered browser | headless Chrome + CDP, `browser_smoke.mjs` | 0 | `browser.json`, `ui-collab.png` |
| Legacy regressions | skills/spec/UI/manifest/hunks scripts | 0 | `legacy.txt` |

The browser run created a real run through the panel, saw the disclosure,
answered the endpoint card, rendered the 13-vs-12 witness, sent a steering input
(`I meant closed intervals.`) and observed it **applied**, saw the old
explanation fenced (“No current explanation”), and clicked **Export**; the
receipt read “Export refused with no effects”. `ui-collab.png` is the rendered
panel at that point.

## Failed attempts retained

`evidence/20261114-192107` is the first full-suite attempt. `ok: false` because
one HTTP test read the transient `idle` status before the background owner
committed `waiting_human`. The test now waits for the settled decision state;
the product code was not weakened.

`evidence/20261114-193652` failed during teardown with a Windows access
violation in the LangGraph SQLite saver. Root cause: the test fixture closed the
service/saver while a background owner pump was still checkpointing. The service
now joins its owner threads before closing the saver; both the API file and the
full suite were rerun and passed. This failed run is retained.

`evidence/20261114-192556` and `evidence/20261114-193006` are earlier green
runs retained for comparison.

## Independent-review repair

The five IR01–IR05 findings are repaired and revalidated. The repair report,
before/after raw logs and source identities are in
`repairs/20261114-205945/README.md`.
The independent review and its original probes were preserved unchanged.

## IR01 authorization follow-up

The two remaining IR01 failures (apostrophe/contraction lexing and embedded
action verbs in explanation requests) are repaired. See
`repairs/20261115-133719/README.md`.
The original independent reviews and the prior repair report are preserved.

## Conversation-first authoring (CN01–CN15)

One conversation now drives the whole stage from empty storage: the internal
run, specification, editorial, candidate solution, validator, test plan, proofs,
decisions and evidence are created and maintained automatically. The chat layer
uses the existing graph/ledger/authority implementation rather than a second
authority. CN01–CN15 have deterministic tests (`qa/engine_contracts/test_chat_native.py`),
HTTP route coverage and a rendered-browser journey including reload/resume. See
`repairs/20261115-chat-native/README.md`.
Model output remains a scripted fake and worker output remains simulated.

## Chat-native repairs CN-R01–CN-R04 and decision layer

The independent review findings are repaired: refusals/explanations cannot grant
contextual edits, uncertain semantic answers cannot commit, proof questions are
requests rather than authored lemmas, and semantic corrections mark dependent
proof/test/plan support stale while preserving source material. Chat
interpretation now goes through a durable structured decision service with host
admission (`engine/decisions.py`), a configured decision-model role and an
unavailable/ambiguous fallback that keeps the turn inert. See
`repairs/20261115-chat-repair/README.md`.
A versioned offline evaluation set and the two rendered-browser journeys are in
that directory. No live model/worker qualification is claimed.

## Decision-layer repairs DR01–DR03

The independent decision review findings are repaired. Effect admission validates
verbatim source provenance and the existing denial/information contract before
any grant; chat registers a durable barrier input before interpretation and
publication rechecks it at the commit point; decision-model calls use durable
reservations, attempts, usage and active-time budgets with replay-safe recovery.
See `repairs/20261116-decision-layer/README.md`.

## DR02 atomicity and failed-turn recovery

The remaining DR02 boundaries are repaired. `append_chat_turn` atomically
commits the author turn, input identity, barrier, link, wake and idempotency;
`publish_revision` guards canonical revision/publication writes against active
barriers, generation, base revision, live authority and proposal identity in the
same transaction. Failed interpretations now carry a bound recovery card; an
explicit Retry/recovery action settles the old barrier only after the replacement
has a safe disposition. See
`repairs/20261117-dr02-atomic-recovery/README.md`.

## Evidence classes

| Class | Status | Notes |
|---|---|---|
| Document-contract coverage | complete | C2 contracts mapped in `README.md` |
| Deterministic fake-model/fake-worker | pass | 286 tests; workflow mechanics only |
| CN01–CN15 conversation journeys | pass | deterministic + HTTP + rendered browser |
| CN-R01–CN-R04 repairs | pass | deterministic + HTTP + rendered browser |
| Structured decision layer | pass | scripted demo + malformed/unavailable/replay admission tests |
| Rendered browser (headless Chrome, Windows) | pass | transcript, cards, artifacts, correction, reload/resume, refusal, decision/stale status |
| Real worker/isolate | **pending** | no `AUTHOR_AGENT_ISOLATE_URL`; code fails closed |
| Real model / decision model | **pending** | no provider call authorized or made |
| Independent human/author study | deferred | V6 |
| Large 432-attempt evaluation | deferred | V6 |

## Identity excerpt (see `identity.json` for all hashes)

- baseline Git HEAD: `9074dc3e2347526702ea85fc63df30b19d1460fa`
- prompt bundle hash: `f02110d71d07fca678e102fef5c1d9c0621ab25871e0fa501f57bc7e6eb3f786`
- skill manifest hash: `c28d4b03fcf4efbda3c12393166701e18a071b7f92385389e4952aac7a628643`
- application schema version: 1
- engine source and fixture SHA-256 entries are listed individually.

Historical `docs/research/agentic-engine-portfolio/evidence/**` files and old
inventories were not modified; their hashes remain historical baselines.

## Commands for a human reviewer

```powershell
# one-command suite + dated evidence
python scripts/run_v0_v3_suite.py

# readable demo (fake model/worker, clearly disclosed)
python scripts/demo_v0_v3.py

# local UI
python server.py --port 8787
# open http://127.0.0.1:8787/ -> Authoring desk
# engine panel demo model/worker (explicit):
#   $env:AUTHOR_AGENT_ENGINE_DEMO="1"; python server.py --port 8787
# without it (and without a configured model) the panel explains the missing model

# conversation-first acceptance file
python -m pytest qa/engine_contracts/test_chat_native.py -q

# direct acceptance file
python -m pytest qa/engine_contracts/test_v3_acceptance.py -q
```

## Known checks that cannot be claimed

- No compiled candidate was executed and no containment property is proven.
- No real model produced any explanation or decision.
- Linux/WSL SQLite/lock behaviour, OS process-kill crash recovery, and
  cross-browser/screen-reader UI behaviour remain unqualified.
- The finite schedules are test cases, not a concurrency proof.

