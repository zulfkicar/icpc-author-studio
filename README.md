# ICPC Author Agent (local MVP)

A small, runnable reduction of the Contest Studio author-assistant design. It
takes an idea to a DOMjudge problem package with deterministic verification.

Open one problem workspace, chat with an agent, and watch it edit files, compile
solutions, run tests and build the statement. Every agent write is recorded as a
reviewable change with a diff and a revert button. Export is blocked until the
deterministic verifier passes.

## Run

```powershell
cd icpc-author-agent
python -m pip install -r requirements.txt
python server.py --port 8787
```

Open <http://127.0.0.1:8787/>. The server binds loopback only.

Commands run headless inside the selected workspace. On Windows the app hides
child console windows, suppresses loader error dialogs, and captures stdout,
stderr, exit code and duration into the chat. The agent also narrates each step;
if the provider returns `reasoning_content` (for example a reasoner model), it is
shown in collapsible **Thinking** cards.

A small verified demo workspace (`workspaces/sum-test`) is present so the UI is
not empty on first launch. Delete that folder if you want to start clean.

Python 3.13 plus `g++` (MinGW) and `pdflatex` (MiKTeX). The agent runtime uses
LangGraph (`langgraph` + `langchain-openai`) with the OpenAI-compatible provider.

## Docker

The image includes Python, LangGraph, g++, the JDK and a TeX Live toolchain, so
the same verification path works without host toolchains.

```powershell
docker compose up --build -d
# open http://127.0.0.1:8787/
docker compose logs -f author-agent
docker compose down
```

After the first build, `docker compose up -d` and `docker compose down` are
enough. Use `--build` again after changing source.

By default the container bind-mounts `./workspaces` and `./.author-agent`, so it
sees your existing problems, chats, reports and provider key. `docker compose
down` leaves them untouched. On Linux hosts, make those directories writable by
the container user (UID 1000):

```bash
mkdir -p workspaces .author-agent
sudo chown -R 1000:1000 workspaces .author-agent
```

If you prefer a clean, isolated install, replace the two volumes with named
volumes and declare them at the bottom of `docker-compose.yml`:

```yaml
    volumes:
      - author-workspaces:/app/workspaces
      - author-state:/app/.author-agent
volumes:
  author-workspaces:
  author-state:
```

To pass a provider key without opening Settings, copy `.env.example` to `.env`
and fill it in; the key is injected into the container but `.env` is never
committed or baked into the image. The Settings UI works too and writes to
`.author-agent/config.json` (or the `author-state` volume).

The container binds the published port to host `127.0.0.1` only. Change the
`ports` mapping in `docker-compose.yml` if you intentionally want LAN access.

## Configure a provider

Open **Settings** in the app and set:

| Field | Default |
|---|---|
| Base URL | `https://api.deepseek.com/v1` |
| Model | `deepseek-chat` |
| API key | your DeepSeek key |

Any OpenAI-compatible chat-completions endpoint with tool calling works,
including OpenRouter (`https://openrouter.ai/api/v1`, e.g.
`deepseek/deepseek-chat`). The key is stored only in
`.author-agent/config.json`, which is gitignored, and is never sent back to the
browser. Environment overrides are also supported:

```powershell
$env:AUTHOR_AGENT_API_KEY = "sk-..."
$env:AUTHOR_AGENT_BASE_URL = "https://api.deepseek.com/v1"
$env:AUTHOR_AGENT_MODEL = "deepseek-chat"
```

## Agent architecture

The provider loop is a LangGraph `StateGraph` (`graph_agent.py`) built with
`create_react_agent`. The model node can call a bounded tool registry; a
`ToolNode` executes it. LangGraph event streaming feeds the UI with reasoning,
assistant text, tool start/end, plan updates and verification events in real
time. The agent can publish a plan with `update_plan`, which is stored per chat
and shown in the **Plan** inspector.

Conversations are durable per workspace. **Chats** in the left sidebar are
separate sessions with titles, timestamps and message counts. **New chat** no
longer deletes the previous one; you can switch back at any time.

Deterministic tools and the verifier remain the authority. LangGraph does not
grant the agent approval or export rights.

## What the agent can do

The model is given a bounded tool registry, not a raw host shell:

- `list_files`, `read_file`, `write_file`, `delete_file`
- `run_command` limited to `g++`, `gcc`, `python`, `javac`, `java`, `pdflatex`,
  `latexmk`, with cwd pinned inside the workspace, no shell operators, no
  redirection, a 120 s cap and output limits. Runs are headless; output is
  returned to the agent and shown in the chat, never in a host terminal window.
- `build_answers` (run the accepted reference on every input and write `.ans`)
- `verify_package`, `read_report`, `export_package`

All tool calls go through the same workspace and verifier code used by the UI.
The model cannot mark a report verified or export a package; only the
deterministic verifier and an explicit user click can do that.

## The workflow

1. **New problem** creates a workspace from the ICPC template:
   `problem.yaml`, `domjudge-problem.ini`, `problem_statement/problem.en.tex`,
   `data/sample`, `data/secret`, `submissions/accepted`,
   `submissions/wrong_answer`, `input_validators`, `NOTES.md`.
2. Ask the agent to author the idea. It writes the statement, validator,
   reference solution, tests and negative solutions.
3. **Build answers** runs the reference solution on every input and writes the
   expected `.ans` files. Multiple accepted references must agree.
4. **Verify** runs the full check.
5. Review the **Changes** panel and diffs, revert anything unwanted, and mark
   changes reviewed.
6. **Export ZIP** builds the final DOMjudge package with
   `problem_statement/manifest.json` containing hashes and the verification
   timestamp. Export is refused while
   changes are unreviewed or the workspace has changed since verification, so
   the agent cannot publish its own work without human acknowledgment.

## What verification actually checks

- Required DOMjudge structure and metadata.
- Every sample/secret input is accepted by `input_validators/validate.py`
  (exit 42 or 0).
- Every accepted reference compiles and matches the stored answer on every test.
- At least one sample, one secret test, one reference and one negative solution.
- Every negative solution compiles and is killed by at least one test. A
  negative program that gets AC on every test is reported as a survivor and
  fails verification. A compile failure is reported but is not counted as a
  kill.
- `problem_statement/problem.en.tex` compiles with `pdflatex` (two passes) and
  `problem.pdf` is produced. If `pdflatex` is unavailable the check is marked
  skipped, not passed.
- Time limit is read from `domjudge-problem.ini`; memory is read from
  `problem.yaml`. Reference and negative runs are bounded by the time limit.
  Windows does not enforce the memory limit.

Output comparison is token-based (whitespace-insensitive). Custom checkers,
interactive problems and float tolerances are intentionally not implemented in
this MVP; the verifier will not pretend they are.

## Reduced from the full design

This keeps the essential author-assistant loop from
`platform-prototype/tooling/omp/AUTHOR-AGENT.md` and the seven-stage workflow in
`docs/research/2026-11-05-interactive-coding/WORKFLOW.md`:

Kept: selected workspace context, typed tool registry, human-reviewed diffs,
literal tests vs generators, reference/wrong-solution evidence, statement
compilation, real subprocess execution, explicit verification, export gating.

Deliberately dropped for now: multi-user auth/RBAC, the full contest platform,
live DOMjudge adapters, MCP transport, managed AI usage accounting, container
sandboxes, Monaco/IDE sessions, interactive/custom-checker problems, and the
Keycloak/Postgres stack. This is a single-user localhost tool, not the
production platform.

## Known MVP limits

- `data/sample` and `data/secret` are flat; DOMjudge test groups are not modelled.
- Comparison is whitespace-token based. Float tolerance, custom output validators
  and interactive problems are not verified.
- Memory limits are recorded but not enforced on Windows.
- One local user; no accounts, RBAC, audit trail or multi-tenant isolation.
- Reference/negative languages: C++/C, Python, Java (toolchains must be on PATH).
- The statement uses the local `icpcproblem.cls`; replace it with the official
  ICPC class if your contest toolchain provides one.

## Security note

The `run_command` tool is allowlisted and path-confined, but `python` and
compiled programs execute real code on this machine. This is a trusted local
authoring tool: run it only with workspaces and model output you are willing to
execute. It is not a hostile-tenant sandbox.

## Files

```
server.py        loopback HTTP API, static UI, background jobs
graph_agent.py   LangGraph state graph, streaming events, plan tool
agent.py         bounded tool implementations + system prompt
verify.py        deterministic package checks and ZIP export
workspace.py     path safety, scaffold, chats, changes, diffs, revert
config.py        local provider configuration
winutil.py       headless Windows process execution
sandbox/         sitecustomize for headless child Python processes
templates/       ICPC statement class and DOMjudge scaffold
web/             chat timeline, chats/files/changes sidebar, inspector
workspaces/      one directory per problem (gitignored)
```
