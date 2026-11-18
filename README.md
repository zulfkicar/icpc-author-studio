# ICPC Author Agent

Author Studio is a local workspace for creating programming contest problems.
Develop a specification in chat, test the solution against an independent
oracle, and review the saved files before exporting a DOMjudge package.

[**Watch the Canal Bookings walkthrough**](docs/design/product-experience/evidence/release-4/canal-bookings-walkthrough.webp) ·
[**Local setup**](docs/SETUP.md) ·
[**Architecture**](docs/ARCHITECTURE.md) ·
[**Roadmap**](ROADMAP.md) ·
[**Verification**](docs/README.md#verification-and-roadmap)

## Quick start

Use Git and Python 3.13. On Linux or macOS, run the following in a terminal.

```sh
git clone https://github.com/zulfkicar/icpc-author-studio.git
cd icpc-author-studio
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m author_studio --port 8787
```

Open [Author Studio](http://127.0.0.1:8787/) and choose
**Commands → Open Canal Bookings sample**. Choose how touching bookings work,
open the counterexample, and run the starter solution. The sample can stage
a fix for you to inspect and save. It uses a separate workspace and scripted
chat, so this path works without a provider key. Full verification uses the
local language and statement toolchains. [Windows, Docker, and optional tools](docs/SETUP.md)

For your own problem, start with an idea in chat or open a saved package.
Configure live chat under **Classic workbench & settings**. Local file editing,
Run, Verify, and export are available independently of chat.

## What you can do

| Task | Where to work |
| --- | --- |
| Develop a problem | Use chat to choose rules, contribute code or a lemma, compare approaches, and inspect evidence. |
| Edit and test | Open workspace files in Monaco, preview statements, run a saved solution, or build expected answers. |
| Investigate a failure | Compare a weighted scheduling solution with an independent oracle, inspect the first mismatch, and reopen its frozen inputs and seed. |
| Release a package | Verify the saved revision, review the file changes, approve that snapshot, and generate its ZIP. |
| Resume work | Reopen drafts, earlier chat pages, and interrupted local jobs from the same workspace. |

## Evidence and scope

- The scripted sample exercises the real editor, local runner, verifier,
  review and export. Release 4 recorded **325 passing engine tests** and a
  **DOMjudge 9.0.1** import of the sample statement and two cases.
  [Release 4 record](docs/design/product-experience/RELEASE-4.md)
- A bounded DeepSeek Flash and Isolate trial recorded a wrong answer, a model
  repair, and a passing replay on the same inputs. [Verification scope](docs/design/author-studio/VERIFICATION.md)
- T34 adds bounded weighted scheduling campaigns with seeded variants and
  a finite grid, recorded oracle checks, and a replay manifest.
  [Campaign guide](docs/implementation/T34-WEIGHTED-CAMPAIGNS.md)
- T35 is next in V4. It will replay and reduce counterexamples, followed by
  mutation testing and validator audits. [Current roadmap](ROADMAP.md)

Author Studio is a single-user local preview. Run it on loopback and keep
provider credentials, workspaces, and unsent drafts private.
[Local trust and execution boundaries](SECURITY.md)

## Develop

| Directory | What lives there |
| --- | --- |
| `author_studio/` | HTTP app, classic workbench, judging and saved packages |
| `engine/` | Collaborative investigation graph, decisions and durable receipts |
| `workers/` | Standalone execution services used in Docker |
| `web/` | Studio and classic browser interfaces |
| `prompts/`, `skills/`, `templates/` | Runtime authoring resources and starter packages |
| `qa/`, `eval/`, `scripts/` | Tests, evaluation harness and maintenance commands |

See [Contributing](CONTRIBUTING.md) for local checks and documentation
conventions. The [docs index](docs/README.md) links setup, architecture,
release notes, and the underlying evidence.
