# How to use the workbench

This is the local single-author workflow. It covers the authoring app, the
optional local DOMjudge loop, and the commands you will actually type.

## 1. Prerequisites

- Windows 11 with WSL2 + Docker Desktop, or Linux with Docker.
- A provider key for an OpenAI-compatible chat endpoint.
- The repository at `C:\Projects\author-agent` (or your clone path).

The app is a **local single-user tool**. Do not expose port 8787 or share
`.author-agent/`.

## 2. First run

```powershell
cd C:\Projects\author-agent
Copy-Item .env.example .env
# edit .env and set AUTHOR_AGENT_API_KEY=<your key>
.\scripts\docker-up.ps1
```

`docker-up.ps1` starts the app, Isolate, the bwrap executor, and a WSL keepalive,
then waits for health. You should see:

```text
ICPC Author Agent: http://127.0.0.1:8787/
```

Open <http://127.0.0.1:8787/>.

Alternatively, start the app and enter the key in **Settings** (gear icon).
The key is stored in `.author-agent/config.json`; never commit it.

### Optional local DOMjudge

```powershell
.\scripts\domjudge-up.ps1 -WithJudgehost
```

DOMjudge is then at <http://127.0.0.1:18080/>. The admin password is printed by
the script, or read it with:

```powershell
wsl -e docker exec icpc-domjudge-server cat /opt/domjudge/domserver/etc/initial_admin_password.secret
```

## 3. Create a problem

In the app:

1. Click **+** next to the **Problem** selector, or **New problem** in the
   empty state.
2. Enter the name, idea, author and short name.
3. Leave **Start the agent immediately** checked if you want the first turn to
   begin now; otherwise create the workspace and write `NOTES.md` first.

The workspace appears in the selector. The left navigator has:

- **Chats** — conversations for this problem.
- **Files** — the workspace tree and editor tabs.
- **Changes** — the review queue and diffs.

## 4. Ask the agent

The agent panel is on the right.

- Type in the composer and press **Ctrl+Enter** or **Send**.
- Use **@** to mention a file and pin it to the context.
- Use **+ context** to select workspace files explicitly.
- **Author / Debug / Review** changes the agent's mode.
- **Stop** cancels the current turn.

A good first prompt:

```text
Author this problem end-to-end from the idea in NOTES.md. State your
assumptions, publish a plan, write the statement, validator, reference,
samples, secret tests and at least one negative solution, then measure limits
and verify until the package is green. Ask only if the rules are genuinely
ambiguous.
```

Approvals appear inline when the agent proposes a write/delete and
**Review every file write/delete** is enabled. Approve or reject them there.

If a turn fails, the saved error message appears in the transcript; the
conversation is not silently dropped. The context guard recovers long chats.

## 5. Edit and run

- Open a file in **Files**; it opens in the center editor as a tab.
- Click **Edit** to use Monaco. Dirty tabs ask before closing or switching.
- **Ctrl+S** saves.
- The **Run** panel appears under runnable files:
  - Backend: Local, Isolate, or Judge0.
  - Per-file stdin, output tabs (stdin/stdout/stderr/compile/result), status,
    time/memory, and last-10 history.
  - **Quick run is not verification.** Isolate remains the verifier.
- **Ctrl+`** toggles the run panel.
- **Ctrl+K** quick-opens a file; **Ctrl+Shift+P** opens the command palette.

## 6. Review, verify and export

The normal end state:

1. Click **Limits** to measure time/memory from the reference.
2. Click **Verify**. This runs the deterministic verifier: validator, accepted
   solutions, negative solutions, statement, tests.
3. Open **Report** to read checks, warnings, limits, stale state and changed
   files. Click a changed file to open its diff.
4. In **Changes**, review each change. You can apply selected hunks, revert, or
   **Mark reviewed**.
5. **Export** is enabled only when the package is verified, not stale, and has
   zero unreviewed changes. The reason is shown as text when it is disabled.
6. Click **Export** to download the DOMjudge ZIP.

Verification can take minutes. Do not restart the app while it runs; jobs are
in memory.

## 7. Import and judge in local DOMjudge

The repeatable tests prove the full local loop:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\qa\test_domjudge_import.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\qa\test_domjudge_judging.ps1
```

The import test:

- exports the verified `sum-test` package,
- imports it into the local `demo` contest,
- verifies HTTP 200, 6 test cases, a statement, no danger, no CRLF.

The judging test additionally submits accepted/wrong/slow C++ and asserts:

```text
accepted → AC
wrong    → WA
slow     → TLE
```

For your own problem, export its ZIP, then import it through the local DOMjudge
jury interface or API. The ZIP basename must match the DOMjudge problem
external ID. The scripts in `qa/` are the working reference for the API calls.

DOMjudge is a separate local UI at <http://127.0.0.1:18080/>. It is not the
authoring app and does not share its workspace files.

## 8. Daily commands

```powershell
# start/stop the authoring app
.\scripts\docker-up.ps1
.\scripts\docker-down.ps1

# start/stop DOMjudge (database preserved)
.\scripts\domjudge-up.ps1 -WithJudgehost
.\scripts\domjudge-down.ps1

# wipe DOMjudge data only
.\scripts\domjudge-down.ps1 -Reset
```

Use `docker-up.ps1`, not plain `docker compose up -d`, on Windows/WSL. WSL
idles and stops the Docker engine; the script keeps it alive.

## 9. Data and backups

| Path | Contents | Share? |
|---|---|---|
| `workspaces/<slug>/` | authored problem, tests, chats, checkpoints | only if intended; contains secret tests |
| `workspaces/<slug>/.agent/export/*.zip` | exported packages | yes, after review |
| `.author-agent/config.json` | provider settings and key | **no** |
| `.env` | provider key | **no** |
| Judge0/DOMjudge volumes | execution/submission data | normally no |

Back up `workspaces/` and `.author-agent/` securely. Do not commit either.
To share one problem, copy its `workspaces/<slug>/` directory or send the
exported ZIP.

## 10. Troubleshooting

**`http://127.0.0.1:8787/` is unreachable**
Run `.\scripts\docker-up.ps1`. WSL may have idled. Check:

```powershell
wsl -e docker ps
wsl -e docker logs icpc-author-agent --tail 100
```

**The agent fails or the turn is not saved**
Failed/cancelled turns are now saved with an error/partial message. If a chat
is still problematic, start a new chat; the old checkpoint remains. For a
context issue, the hard guard and autocompact should recover the next turn.

**Export is disabled**
Check the title on the button. You need: verified, not stale, zero unreviewed
changes. Run **Limits** before **Verify** if limits are not measured.

**DOMjudge import says “Specified problem does not exist”**
The API import target must already exist. Add the problem metadata first, or
use the provided import test as the pattern. The ZIP basename must match the
problem external ID.

**DOMjudge judgehost fails with cgroup errors**
The judgehost must be `privileged` and use `cgroup: host` with
`/sys/fs/cgroup` mounted. The compose file already does this.

**A program needs a writable temp directory**
The judgehost currently runs without `DOMJUDGE_CREATE_WRITABLE_TEMP_DIR` because
its cleanup path fails on this image. Most ICPC programs do not need it; if yours
does, that needs a separate fix.

## 11. What “done” means

A problem is export-ready when:

- the deterministic verifier says **verified**;
- the workspace is **not stale**;
- every change is **reviewed**;
- the exported ZIP imports into local DOMjudge;
- an accepted solution gets **AC**, a wrong solution gets **WA**, and a slow
  solution gets **TLE**.

The manual screen-reader sign-off remains the only human verification item.
