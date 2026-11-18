# Author Studio product experience plan

18 November 2026 · Research and implementation plan

[Release 1](RELEASE-1.md), [Release 2](RELEASE-2.md), [Release 3](RELEASE-3.md), and [Release 4](RELEASE-4.md) are implemented. The experiences
below describe the initial audit and the intended delivery order.

**Make it effortless to stop, return, and keep working on the same problem.** A setter
should be able to name an idea, explore it with the agent, switch into code, inspect
the evidence, and release a judge package without re-entering information or
guessing which version a result refers to.

The first release should fix the everyday actions that currently lose work or change
more than they appear to. A browser walkthrough reproduced a decision button clearing
an unsent message, reload losing chat and editor drafts, and linking an existing
package applying the conversation title without a preview. The same walkthrough
confirmed that an explicit rename already follows the problem into the package and
correctly makes its previous verification stale. That propagation is a strength.
Make it discoverable, predictable, and easy to recover from.

| Read | Use it for |
| --- | --- |
| [Experience map](EXPERIENCE-MAP.md) | Audiences, routes, journey map, observed friction, evidence and failure paths |
| [Research and design direction](RESEARCH.md) | Visual references, interaction research, reusable components and the design decision |
| [Delivery plan](DELIVERY.md) | Ordered work, 50+ product details, owners, acceptance criteria and release gates |
| [Release 1 verification](RELEASE-1.md) | Implemented behavior, browser scenarios and remaining evidence |
| [Release 2 verification](RELEASE-2.md) | Keyboard, navigation, narrow workspaces and package release |
| [Release 3 verification](RELEASE-3.md) | Case replay, verification, cumulative review, and human-approved export |
| [Release 4 verification](RELEASE-4.md) | Context receipts, sample, long sessions, interrupted jobs, and DOMjudge import |
| [Design contract](../../../DESIGN.md) | The existing Author Studio contract and the proposed direction for this work |

## Who the plan serves

- **A setter with a rough idea** needs something useful to type, a clear first
  decision, and the ability to steer in their own words.
- **A setter with an existing problem** may have code, cases, or an imported
  package. They need useful manual tools before and alongside chat.
- **A setter reviewing or handing off a problem** needs to understand what passed,
  what is still uncertain, and which exact files will go to the judge.
- **Someone viewing a portfolio demo** needs one understandable real workflow
  with the model, test worker, and export modes identified. The setter's daily
  workspace supplies the example.

These jobs are based on the project history and walkthrough. The same person can
switch between them during a session.

## Recommended experience

Keep the technical studio. Concentrate its identity in disciplined typography,
predictable keyboard behavior, and useful domain details. The problem title anchors
the app. **Conversation**, **Workspace**, and **Release** each have one home.
Chat and editor layouts keep the current problem, drafts, and permissions as the
author switches focus. Proof and activity are views of the same work.

| Area | First thing the setter should see |
| --- | --- |
| Problem switcher | Full title, recent position, and any decision that needs them |
| Problem header | Title, how to rename it, and one meaningful current state |
| Conversation | Their current question or the latest useful result, with a stable composer |
| Workspace | Active file, whether it is saved, and what version Run will use |
| Release | Current blocker or next action, then the verified ZIP name when available |

Progress, warnings and completion messages use plain words. Give logs and IDs
a place under Details. Keep the context bar small beside the composer with the
optional map in its popup. Use the space recovered from toolbar clutter to make
code, proof, and output easier to read.

## Delivery order

| Release | What a setter gets | Exit condition |
| --- | --- | --- |
| 1 · Keep my work | Predictable naming and linking, recoverable drafts, consistent receipts, return to the same problem and file | Pass loss-of-work, wrong-target, reload, and linked rename regressions |
| 2 · Make it easy to work | Clearer navigation, editor continuity, responsive panes, useful keyboard paths and readable controls | Complete a keyboard-only edit, run and review journey on the supported layouts |
| 3 · Make it easy to judge | Evidence linked to cases and source, a clear expected/actual comparison, trustworthy review, and one release flow | Trace a mismatch to its cause, correct it, and deliver the human-approved saved revision |
| 4 · Qualify and showcase | Accurate optional context details, repeatable demos, accessibility and performance evidence, and author sessions | Meet the release gates on the replay fixture and collect evidence from setters |

The order favors recovery and confidence before adding more surfaces. A model,
framework, or dependency change earns its place by solving a specific workflow
problem. The delivery plan includes the cases to prove that improvement.
