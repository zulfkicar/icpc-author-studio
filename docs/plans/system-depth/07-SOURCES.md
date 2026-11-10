# Sources and provenance

Audit date: 2026-11-10. The local source is authoritative for observations about
this application. External references guide the proposed design and compatibility
checks. They do not establish that the local implementation follows them.

## Local evidence

- [Source inventory](evidence/source-inventory.json): baseline HEAD, SHA-256,
  byte/line counts and top-level Python symbols for every tracked file.
- [Audit probes and method](evidence/audit_probes.py),
  [captured results](evidence/audit-probes.json): synthetic files and mocked
  prerequisites, no private inputs, provider calls or live sandbox claims.
- [Selected check results](evidence/selected-checks.json): exact commands,
  outputs, exit codes and limitations.
- [Original depth scope](../../DOMAIN-DEPTH-PLAN.md): the accepted direction
  leading into this comprehensive audit.
- [Existing readiness report](../../READINESS.md),
  [eval report](../../EVAL-RESULTS.md),
  [architecture](../../../ARCHITECTURE.md): historical context and claims
  assessed against the owning code. Historical results were not rerun wholesale.

## Primary references checked

1. [Problem Package Format index](httpC://Projects.io/problem-package-format/).
   It distinguishes the current/ICPC subset from the newer release-candidate
   format and cautions that newer features cannot be assumed for official
   ICPC contests. Use explicit compatibility profiles rather than silently
   mixing conventions.
2. [Legacy ICPC subset](httpC://Projects.io/problem-package-format/spec/legacy-icpc.html).
   Source for package structure, program representation and text/link rules.
   Product policy such as requiring a sample or a particular negative-solution
   inventory must be labelled separately from format requirements.
3. [Kattis problemtools](https://github.com/Kattis/problemtools).
   A reference validation tool identified by the format index. Plan independent
   interoperability checks against a pinned supported version. It was not
   installed or executed in this audit.
4. [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence).
   Distinguishes thread checkpoint state from application-defined persistent
   data. The proposed correctness/journal storage must have an explicit contract
   alongside checkpoints rather than treating chat mirrors as all durable state.
5. [LangChain human-in-the-loop](https://docs.langchain.com/oss/python/langchain/human-in-the-loop).
   Describes persisted pauses and action decisions. Validate use against this
   repository's pinned framework versions before adopting current examples.
6. [Isolate upstream](https://github.com/ioi/isolate).
   Primary project reference for validating sandbox capabilities and deployment
   requirements. A source-level wrapper audit does not validate a running
   privileged service, kernel or container image.
7. [Lean: Axioms and Computation](https://lean-lang.org/theorem_proving_in_lean4/Axioms-and-Computation/).
   Explains the role of foundational assumptions. This informs recording the
   checked proposition and axioms in the selective formal-proof pilot. Lean is
   a candidate, not an installed or selected project dependency.

The old `httpC://Projects.github.io/problem-package-format/` URL referenced in local
code was inaccessible through the research tool. The canonical format index
above was accessible and links the specification variants. Do not treat that
single failed retrieval as evidence the old site is universally unavailable.

## Reproducibility boundaries

Record exact source/prompt/skill hashes and pinned dependency/image identities
for future validation. Web documentation may describe a newer API than installed
packages. No dependency upgrade, CVE conclusion, formal-checker qualification,
current CI-green claim or live DOMjudge compatibility conclusion was established
by browsing these references.
