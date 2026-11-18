# Local setup

## Install locally

Use Git and Python 3.13. The sample starts without a provider account, an API
key, or a judge server.

On Windows PowerShell, run the following.

```powershell
git clone https://github.com/zulfkicar/icpc-author-agent.git
Set-Location icpc-author-agent
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe server.py --port 8787
```

On Linux or macOS, run the following.

```sh
git clone https://github.com/zulfkicar/icpc-author-agent.git
cd icpc-author-agent
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python server.py --port 8787
```

Open [Author Studio](http://127.0.0.1:8787/) for the chat and workspace. Open
[Classic workbench](http://127.0.0.1:8787/workbench) for the earlier editor and
Provider settings. The default bind address is `127.0.0.1`.
Use `Ctrl+C` in the terminal to stop the app. For an occupied port, start it
with `--port 8788` and open the matching URL.

## Use the Docker stack

On a local Linux or WSL2 Docker installation with Compose, run from the
checkout directory.

```sh
docker compose up --build -d
docker compose ps
```

Open the same loopback address. Compose includes Isolate and the supporting
executor. Isolate uses a privileged container in this stack. Review the local
trust boundary before enabling it. `docker compose stop` stops the services.
The checkout's local state and saved workspaces are mounted into the app.
[Worker setup and limits](ISOLATE-BACKEND.md) · [Local trust boundaries](../SECURITY.md)

## Try the sample

1. Choose **Commands → Open Canal Bookings sample**. The sample creates a separate synthetic problem and package.
2. Choose the endpoint rule in chat. Open the counterexample with **Run this case** and run the saved reference to reproduce the mismatch.
3. Choose **Load sample fix**, inspect the draft, and use **Save & Run** to confirm the repair.
4. Build expected answers, measure limits, and verify the saved package. In **Export ZIP**, review and approve that snapshot before generating the archive.

The sample uses scripted chat and a simulated investigation worker. The
workspace runner, verifier and export use the normal local backend. The browser
walkthrough documents exactly which parts were tested.
[Sample walkthrough record](design/product-experience/RELEASE-4.md)

## Configure live chat

Open **Provider settings** in Classic workbench. Use your own key, enable live
Author Studio chat, and restart the server. Choose the provider before starting
a new conversation. Each run keeps its provider. Provider calls can incur
charges and send selected chat and artifact context to the configured endpoint.

| Provider | Local settings |
| --- | --- |
| OpenRouter | Save its key and model ID. The configured default is `deepseek/deepseek-v4.1-flash`. |
| OpenCode | Save its key and choose Console or Go for the new conversation. These are separate billing routes. |
| OpenAI-compatible | Enter the model ID and key in the standard fields. Enter your compatible endpoint for a service other than OpenAI. |

`AUTHOR_AGENT_ENGINE_LIVE_MODEL=1` or `0` overrides the saved live-chat setting
for that process. `AUTHOR_AGENT_ENGINE_DEMO=1` enables the scripted default when
there is no live override. The built-in sample selects its scripted provider
and simulated worker per conversation. It needs neither switch.

When using Compose, you can instead copy `.env.example` to `.env` locally and
fill in the three OpenAI-compatible fields you need. Keep `.env` and the app's
saved settings local. Compose reads `.env` when creating containers. For a
native run, use Provider settings or set environment variables in the shell
that starts the server.

The optional `AUTHOR_AGENT_CONTEXT_WINDOWS` map of model capacities is
a JSON object keyed by the exact model ID. Use a capacity verified for the
configured endpoint. Studio shows unknown capacity when none is recorded.

## Install local tools as needed

- Python runs the sample reference and validator. C/C++ and Java workflows use their configured local compilers or worker.
- TeX builds the statement PDF. Poppler's `pdftocairo` enables the inline first-page preview.
- `clang-format` and Ruff provide editor formatting and linting. Install the project's optional pins or place the tools on `PATH`.

On Debian or Ubuntu, the native toolchain can be installed with
`sudo apt install g++ default-jdk-headless latexmk lmodern texlive-latex-extra poppler-utils`.
On Windows, put your compiler, JDK, TeX distribution and Poppler on `PATH`,
or use the Docker stack from WSL2. Confirm the tools you need in the Workspace
Run and Verify drawers.

Install the editor tools with `python -m pip install --target .author-agent/editor-tools -r requirements-editor.txt`,
using the virtual-environment Python from the install step.

The local worker options and the pinned contest stack are covered in
[Isolate backend](ISOLATE-BACKEND.md) and [Local DOMjudge](DOMJUDGE-LOCAL.md).
Manual **Run saved source** uses the host runner. Its result is scoped to the
source and input shown in the drawer.

| If you see | What to check |
| --- | --- |
| The app opens with no live provider | Start the built-in sample or configure your own provider and restart the app. |
| Run reports a missing compiler | Install the language toolchain on the server's `PATH`, or use a configured worker for supported runs. |
| The statement PDF is missing | Install the TeX tools and generate it through verification. Poppler enables the inline preview. |
| Export needs verification or review | Verify the saved files, then approve that exact snapshot in the Export ZIP drawer. |

## Data and recovery

| Location | Contents |
| --- | --- |
| `.author-agent/config.json` | Local provider settings and credentials |
| `.author-agent/engine/` | Conversation ledgers, checkpoints and attachments |
| `workspaces/` | Saved package files and package-specific history |
| Browser storage | Local composer and file drafts, layout and navigation state |

`AUTHOR_AGENT_ENGINE_ROOT` and `AUTHOR_AGENT_WORKSPACES_ROOT` can select
separate roots for a disposable instance. Back up the local roots before an
upgrade. Preserve drafts separately when moving to another browser profile.
Git ignores these roots and generated ZIPs by default.

The project has recorded checks on Windows/WSL2 and Linux-based CI.
See the verification index for the scope of each check. [Verification records](README.md#verification-and-roadmap)
