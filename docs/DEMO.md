# Demo runbook

This is the presenter's guide for showing the ICPC Author Agent to one
technical person or a small panel. It is a local single-author workbench, not a
hosted service.

The demo has one job: show that the agent does real authoring work, but the
**deterministic verifier and the exported package are the authority** — and that
the package survives a real DOMjudge judgehost.

## The three claims to make

1. **The agent moves a problem through a real pipeline.** It writes the
   statement, validator, reference, tests and negative solutions, measures
   limits, and iterates against concrete compiler/runner output.
2. **The model cannot declare success.** `verify` compiles and runs the package;
   export is blocked until verification passes, the workspace is unchanged, and
   every write is reviewed.
3. **The output is not a mock.** A verified package imports into local DOMjudge
   9.0.1 and is judged by a real `judgehost` with **AC / WA / TLE**.

Say what is *not* claimed too: this is a local beta, not multi-user hosting,
not a hypervisor VM, and not battle-tested by many authors.

---

## What is on screen

Five regions, left to right, plus a status bar:

| Region | What to point at |
|---|---|
| Activity rail | Chats, Files, Changes, Run, Evidence, History |
| Navigator | Problem selector, conversation list, file tree, review queue |
| Editor group | Plan / File / Report / Diff / History / MCP tabs, Monaco editor |
| Agent panel | Timeline: narration, thinking, tool cards, approvals, composer |
| Status bar | Connection, executor health, limits, language, cursor, verification |

The demo workspace is **`sum-test`**: verified, not stale, zero unreviewed
changes. Do not use the eval workspaces for the live demo.

---

## Preflight (T-15 minutes)

Run this once before the audience arrives:

```powershell
cd C:\Projects\author-agent
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\demo-ready.ps1 -PrepareData -OpenBrowser
```

Expected final block:

```text
================ DEMO READY ================
App:        http://127.0.0.1:8787/
DOMjudge:   http://127.0.0.1:18080/
Admin:      admin
Password:   <generated; do not project this>
Provider:   configured-model  (hasKey=True)
Workspaces: ..., sum-test
Judgehost:  judgedaemon-0-0
DOMjudge:   demo contest / sum-test-qa with AC, WA, TLE submissions
============================================
```

`-PrepareData` re-runs the import and judging tests, so DOMjudge ends with a
known AC/WA/TLE set. The tests are idempotent for the problem import but add new
submissions each run; that is fine for a demo.

Then do these four checks:

1. In the app, select **Sum Test**. The status pill should say **verified** and
   **Export** should be enabled.
2. In DOMjudge, log in as `admin` **off-screen** and leave the tab on
   **Jury → Submissions** for contest `demo`. Do not project the password.
3. Open `qa/screenshots/01-overview.png` in a second window as the fallback.
4. Keep `docs/MODULE-CHEAT-SHEET.html` open in a second window for the
   deep dive; it prints to one page.

If `-PrepareData` fails, fix that before presenting. Do not debug in front of
the audience.

Minimal health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8787/api/health
Invoke-WebRequest http://127.0.0.1:18080/ -UseBasicParsing
```

Expected: `ok=True`, and HTTP 200.

---

## 5-minute version

Use this when the audience mainly wants the product story.

| Time | Do | Say |
|---|---|---|
| 0:00 | Title | “This is a local workbench that takes an ICPC idea to a verified DOMjudge package. The agent proposes; the verifier proves.” |
| 0:30 | Point at the five regions; select `sum-test` | “One problem per workspace. Chats, files, changes, editor, agent, evidence.” |
| 0:50 | Files → `submissions/accepted/ref.cpp` | “This is the reference solution the agent wrote and the verifier compiled.” |
| 1:10 | Open **Run**, backend **Isolate**, click **Run** | “Quick run is for the author's inner loop. It is not verification.” |
| 1:40 | Open **Report** | “Six tests: one sample, five secret. Validator accepted 6/6. The reference is AC on every test. The wrong solution is killed. The PDF compiled. The ICPC spec audit is 18/18.” |
| 2:30 | Open **Changes**; point at `0` unreviewed | “Every agent write is a reviewable diff. Export is a derived predicate: verified, not stale, zero unreviewed.” |
| 3:00 | Click **Export** | “The ZIP is the DOMjudge package. Export is blocked unless all three conditions hold.” |
| 3:20 | Switch to DOMjudge → Submissions | “The same package is imported here. Accepted is AC, wrong is WA, slow is TLE, judged by a real judgehost.” |
| 4:15 | Close | “That is the loop: idea → agent → deterministic verify → review → export → judge. The model never gets to mark its own homework.” |
| 4:40 | Questions | Use the Q&A bank in `TECHNICAL-DEEP-DIVE.md`. |

If the browser or provider is misbehaving, switch to the fallback at the end of
this document. Do not improvise a live agent turn in the 5-minute format.

---

## 15-minute version

Use this when there is time for one agent turn and a little architecture.

| Time | Do | Say |
|---|---|---|
| 0:00 | Title and claims | Same three claims as above. |
| 0:45 | Five regions; `sum-test`; status pill | “The workspace is the source of truth; the UI is an instrument, not a landing page.” |
| 1:30 | **Files** → `ref.cpp`; **Edit**; show Monaco | “The editor is a real Monaco surface with per-file tabs, dirty guards and a textarea fallback.” |
| 2:30 | **Run** → **Isolate** → **Run** | “The app never executes model code. It calls a separate Isolate worker with CPU/wall/memory/process limits.” |
| 3:30 | New chat in `sum-test`, send the read-only prompt below | “The agent has typed tools, not ambient authority. It can read the report but not secret tests or `.ans` files.” |
| 5:00 | Point at the tool cards and the answer | “Every claim is tied to a tool result. Failed turns are saved, not silently dropped.” |
| 6:00 | **Plan** | “The plan is operational: the agent maintains todos, and pinned context survives compaction.” |
| 7:00 | **Report** | Walk the checks in order: structure, validator, reference, negative, limits, PDF, spec. |
| 9:00 | **Changes** | “Review is part of the gate, not a suggestion.” |
| 10:00 | **Export** | Show the enabled state, then the disabled reason if you revert a file. |
| 11:00 | DOMjudge submissions | AC / WA / TLE. |
| 12:30 | Architecture in one minute | “React-less vanilla UI → local HTTP server → LangGraph agent → typed tools → Isolate/bwrap workers. File-based workspace, SQLite checkpoints.” |
| 13:30 | Limits and honesty | “Single-author local beta. No multi-user auth, no hypervisor VM, no load test. Here is the evidence and here is what is missing.” |
| 14:30 | Questions | Deep dive doc. |

### Safe live prompt

Use this only in the 15-minute format. It is read-only and small:

```text
Read the last verification report and give me a six-bullet technical summary:
what was verified, which checks passed, how the negative solution was killed,
and what the report does not prove. Do not edit any files.
```

Expected: a short answer that cites `report_summary` / `read_report`. It should
not write files, so `sum-test` stays verified and exportable.

If the provider is slow or fails, stop the turn and say: “The transcript is
saved; the failure is visible. That is the failure-persistence path.” Then use
the existing `eval-claim-or-concede-2` chat as the transcript fallback.

---

## 30-minute technical deep dive

Use `docs/TECHNICAL-DEEP-DIVE.md` as the spine:

1. Claims and non-claims (2 min)
2. System map and container topology (4 min)
3. Module map: what does what (4 min)
4. One agent turn, end to end (4 min)
5. Verification, end to end (5 min)
6. Export gate and review (3 min)
7. Decision log: LangGraph, Isolate, Judge0, files-not-DB, context guard (4 min)
8. "What covers what" matrix (3 min)
9. Failure modes and security boundaries (2 min)
10. Q&A bank (remaining)

Do not read the document on screen. Use it as a question bank and keep the live
UI or a code editor open.

---

## Live click path

This is the exact path used in the 5- and 15-minute scripts.

1. **Workspace selector** → `Sum Test`.
2. **Files** → `submissions/accepted/ref.cpp`.
3. **Run** panel → backend `Isolate` → **Run**.
4. **Report** tab → read top to bottom:
   - status `verified`
   - 16 checks
   - `Validator results: 6/6 inputs valid`
   - `Statement PDF: problem.pdf compiled`
   - `ICPC package spec: 18/18 checks pass`
5. **Changes** → `0` unreviewed.
6. **Export** → downloads `sum-test-domjudge.zip`.
7. DOMjudge `http://127.0.0.1:18080/` → `demo` contest → Submissions:
   - submission 1/4 → AC
   - submission 2/5 → WA
   - submission 3/6 → TLE (about 1.9 s)
8. Optional: run the judging test in a terminal and show the JSON.

Optional terminal proof:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\qa\test_domjudge_judging.ps1
```

Expected tail:

```json
{"accepted":{"verdict":"AC"},"wrongAnswer":{"verdict":"WA"},"timeLimit":{"verdict":"TLE"}}
DOMJUDGE JUDGING TEST PASSED
```

The exact submission IDs will change on each run.

---

## Fallbacks

### The app is up but the provider is down

- Do not retry in front of the audience.
- Show the existing `eval-claim-or-concede-2` conversation: 92 messages, real
  tool cards, a verified package.
- Show `qa/screenshots/01-overview.png`, `03-report.png`, `17-review-queue.png`.
- Continue with the deterministic verifier and DOMjudge, which do not need the
  provider.

### DOMjudge is down

- Run `.\scripts\domjudge-up.ps1 -WithJudgehost` and wait for
  `DOMJUDGE JUDGEHOST READY`.
- If it still fails, show `docs/DOMJUDGE-LOCAL.md`’s recorded JSON and the
  `qa/test_domjudge_judging.ps1` output. Say plainly that the live judge is not
  available and the recorded result is from a clean volume.

### Export is disabled

Read the button title. The three reasons are:

- not verified → run **Verify**;
- stale → the workspace changed after verification, run **Verify** again;
- unreviewed changes → **Changes** → **Mark reviewed**.

Do not bypass the gate to make the demo smoother. The gate is the product.

### The browser is stale

Reload. If the app container was restarted, in-memory jobs are gone; the
workspace, chats, plans and reports are on disk. Do not restart while a turn or
verification is running.

---

## Q&A quick answers

Full answers and evidence pointers are in
`docs/TECHNICAL-DEEP-DIVE.md`.

- **“Is the model judging its own work?”** No. `verify.py` compiles and runs the
  package; the report is deterministic. Export requires that report plus a
  fresh snapshot and zero unreviewed changes.
- **“What stops it from faking a pass?”** Tool results are the only evidence;
  the system prompt says so, and the export gate ignores model claims.
- **“Why three execution backends?”** Isolate is the verifier and default quick
  run; bwrap handles LaTeX/PDF and fallback; Judge0 is an optional quick-run
  backend. Only Isolate/bwrap can produce verification evidence.
- **“Is this a VM?”** No. It is a hardened container plus Isolate/bwrap. A true
  hypervisor microVM is future work.
- **“Can I host it for my team?”** Not as-is. It is loopback-only, single-user
  and unauthenticated. Each author should run their own local instance.
- **“Does it really import into DOMjudge?”** Yes: HTTP 200, `sum-test-qa`,
  6 tests, `D.pdf`, no danger, no CRLF. And it judges AC/WA/TLE.
- **“What is the biggest gap?”** Independent authors, real contest load, a
  security review, and a manual screen-reader pass. The single-author loop is
  proven; “battle-tested” is not.

---

## Teardown

```powershell
# stop the authoring stack
.\scripts\docker-down.ps1

# stop DOMjudge, keep its database
.\scripts\domjudge-down.ps1

# or wipe DOMjudge only
.\scripts\domjudge-down.ps1 -Reset
```

Do **not** reset `workspaces/` or `.author-agent/`. DOMjudge reset only affects
the local test stack.

---

## Final checklist

- [ ] `demo-ready.ps1 -PrepareData` exits 0.
- [ ] `sum-test` is selected, **verified**, **Export** enabled.
- [ ] DOMjudge is logged in off-screen; submissions page is open.
- [ ] Fallback screenshots are open in a second window.
- [ ] Terminal font is large enough to read the JSON.
- [ ] The admin password is not visible on the projected screen.
- [ ] You have said what is **not** proven.
