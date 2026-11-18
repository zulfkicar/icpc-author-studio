# ICPC Author Agent

Author Studio is a local workspace for creating programming contest problems.
Develop a specification in chat, test the solution against an independent
oracle, and review the saved files before exporting a DOMjudge package.

[**Watch the Canal Bookings walkthrough**](docs/design/product-experience/evidence/release-4/canal-bookings-walkthrough.webp) ·
[**Local setup**](docs/SETUP.md) ·
[**Architecture**](docs/ARCHITECTURE.md) ·
[**Verification**](docs/README.md#verification-and-roadmap)

## Quick start

Python 3.13 is the tested local version. From the repository root:

```sh
python -m pip install -r requirements.txt
python server.py --port 8787
```

Open [Author Studio](http://127.0.0.1:8787/) and choose
**Commands → Open Canal Bookings sample**. Choose how touching bookings work,
open the counterexample, and run the starter solution. The sample can stage
a fix for you to inspect and save. It uses a separate workspace and scripted
chat, so this path works without a provider key. Full verification uses the
local language and statement toolchains described in [Setup](docs/SETUP.md).

For your own problem, start with an idea in chat or open a saved package.
Configure live chat under **Classic workbench & settings**. Local file editing,
Run, Verify, and export are available independently of chat.

## What you can do

| Task | Where to work |
| --- | --- |
| Develop a problem | Use chat to choose rules, contribute code or a lemma, compare approaches, and inspect evidence. |
| Edit and test | Open workspace files in Monaco, preview statements, run a saved solution, or build expected answers. |
| Investigate a failure | Replay a counterexample, inspect expected and actual output, and trace a diagnostic back to the saved source. |
| Release a package | Verify the saved revision, review the file changes, approve that snapshot, and generate its ZIP. |
| Resume work | Reopen drafts, earlier chat pages, and interrupted local jobs from the same workspace. |

## Evidence and scope

- The scripted sample exercises the real editor, local runner, verifier,
  review and export. Release 4 recorded **325 passing engine tests** and a
  **DOMjudge 9.0.1** import of the sample statement and two cases.
  [Release 4 record](docs/design/product-experience/RELEASE-4.md)
- A separate bounded DeepSeek Flash and Isolate trial recorded a real
  wrong answer, a live model repair, and a passing replay on the same
  inputs. Live investigation record
- The planned next engine milestone is broader correctness campaigns,
  counterexample reduction, mutation testing, and validator audits.
  [Engine roadmap](docs/research/agentic-engine-portfolio/07-ROADMAP-AND-PORTFOLIO.md)

Author Studio is a single-user local preview. Run it on loopback and keep
provider credentials, workspaces, and unsent drafts private.
[Local trust and execution boundaries](SECURITY.md)

## Develop

See [Contributing](CONTRIBUTING.md) for local checks and documentation
conventions. The [docs index](docs/README.md) links setup, architecture,
release notes, and the underlying evidence.
