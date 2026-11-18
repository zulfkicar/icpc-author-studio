# Local setup

## Start the app

Use Python 3.13 and run from the repository root. Create a virtual environment
before installing dependencies if you share the machine with other projects.

```sh
python -m pip install -r requirements.txt
python server.py --port 8787
```

Open [Author Studio](http://127.0.0.1:8787/) for the chat and workspace. Open
[Classic workbench](http://127.0.0.1:8787/workbench) for the earlier editor and
Provider settings. The default bind address is `127.0.0.1`.

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

Open **Provider settings** in Classic workbench. Save a key in the slot for the
provider, enable live Author Studio chat, and restart the server. Choose that
provider before starting a new conversation. Each run keeps its provider.

| Provider | Local settings |
| --- | --- |
| OpenRouter | Save its key and model ID. The configured default is `deepseek/deepseek-v4.1-flash`. |
| OpenCode | Save its key and choose Console or Go for the new conversation. These are separate billing routes. |
| OpenAI-compatible | Save the endpoint, model and key in the standard provider fields. |

`AUTHOR_AGENT_ENGINE_LIVE_MODEL=1` or `0` overrides the saved live-chat setting
for that process. `AUTHOR_AGENT_ENGINE_DEMO=1` enables the scripted default when
there is no live override. The built-in sample selects its scripted provider
and simulated worker per conversation. It needs neither switch.

The optional `AUTHOR_AGENT_CONTEXT_WINDOWS` map of model capacities is
a JSON object keyed by the exact model ID. Use a capacity verified for the
configured endpoint. Studio shows unknown capacity when none is recorded.

## Install local tools as needed

- Python runs the sample reference and validator. C/C++ and Java workflows use their configured local compilers or worker.
- TeX builds the statement PDF. Poppler's `pdftocairo` enables the inline first-page preview.
- `clang-format` and Ruff provide editor formatting and linting. Install the project's optional pins or place the tools on `PATH`.

```sh
python -m pip install --target .author-agent/editor-tools -r requirements-editor.txt
```

The local worker options and the pinned contest stack are covered in
[Isolate backend](ISOLATE-BACKEND.md) and [Local DOMjudge](DOMJUDGE-LOCAL.md).
Manual **Run saved source** uses the host runner. Its result is scoped to the
source and input shown in the drawer.

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
