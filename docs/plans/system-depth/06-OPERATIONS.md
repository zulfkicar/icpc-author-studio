# Operations, migration and rollout

Status: planned procedures. No installation, service launch, deployment,
destructive cleanup or paid evaluation was performed to prepare this plan.

## 1. Supported operating profiles

Primary target: one author on a local loopback application with separate
execution workers. Preserve a documented Windows/WSL route and a Linux route.
Native UI/server launch still requires a worker for generated code. The worker
must expose its capability/version contract before authoring execution starts.

Keep quick-run backends optional and distinguish them from verification.
The source-run Isolate API, argv-run worker API, bwrap statement builder and
Judge0 quick-run adapter need a tested compatibility matrix. Do not label
them equivalent simply because each can run an addition program.

Shared hosting, LAN exposure, multiple users, managed authentication and public
deployments remain separate projects. No current preview setting should imply
that those capabilities have been established.

## 2. Configuration and secret handling

Define a typed schema with default, valid range, sensitivity, source precedence,
restart requirement, client ownership and UI visibility for each field.
Reject invalid/nonfinite sizes, timeouts, retries and prices. Validate endpoint
schemes and disclose where code/data will be sent. Remote configured endpoints
must not silently receive protected test contents.

Use explicit precedence for environment overrides and saved settings. The UI
must explain fields that are environment-controlled and cannot be changed by
saving. Include clear/replace semantics for every token/key. Do not return
secrets in normal settings responses, traces, provider errors or downloaded
support bundles.

Keep keys out of workers, source packages, snapshots intended for distribution,
skill references and eval fixtures. Apply file permissions and atomic writes
for local storage, with an optional OS-managed secret-store path if justified
by the supported installation target. That optional integration is not a
reason to block unrelated local correctness work.

Service authentication and child sandboxing are separate controls. Configure
worker access according to the local threat model, remove unnecessary published
ports and validate denial of untrusted callers. Do not invent an auth guarantee
from loopback binding alone.

## 3. Packaging and reproducible environments

- Lock direct/transitive Python dependencies with integrity hashes and a
  repeatable update process. Record platform-specific constraints explicitly.
- Pin execution images/toolchains to immutable identities for validation runs.
  Document any apt/system package drift and refresh deliberately.
- Record vendor/component versions, hashes, licenses and required notices,
  including Monaco, highlight.js, axe-core and testlib.
- Choose a root project license before publishing a distributable package.
  Third-party licenses do not automatically license first-party work.
- Add dated dependency/image vulnerability checks and triage findings based on
  actual deployment and reachability. No vulnerability conclusion is made by
  this source audit.
- Keep a build manifest for source, prompts, skills, templates, dependencies,
  images and format profiles. Retain generated provenance with release artifacts.
- Audit build context to exclude private workspaces, provider configuration,
  generated evaluation data and secrets. Include a negative secret-canary test.

Do not remove toolchains from the app image until remote capability discovery
replaces local compiler probing. Then evaluate a smaller app image and
independent worker builds without changing observable behavior.

## 4. Startup, health and shutdown

Startup validates configuration, required prompt/skill resources, metadata
schemas, writable state directories, worker protocol/capabilities and migration
state. Report application health separately from readiness to run code,
verify a package or use an optional backend.

Update WSL scripts to consistently use the selected distro and project. A port
parameter must configure the actual service mapping or be rejected. Quote
paths safely. Track process identity, start time and intended command alongside
a PID before terminating a keepalive. Avoid killing unrelated processes after
PID reuse. Keep windows hidden for background helpers.

Stop accepting new jobs before shutdown. Cancel or checkpoint active operations,
wait within a bound, reap child processes and record interrupted jobs. Service
shutdown must not delete packages, histories, volumes or diagnostic evidence.

Clean-machine rehearsal covers paths with spaces, non-default distro, missing
Docker/WSL, unavailable compiler, unwritable volume, worker crash and occupied
ports. Failure messages explain the next action without exposing credentials.

## 5. Migration strategy

1. Inventory schema versions and current workspace metadata without reading
   or exporting secrets unnecessarily.
2. Create a verified backup of affected package files and application metadata.
   Record source hashes and retain the original checkpoint database and mirrors.
3. Run a dry-run migration that reports proposed changes, required disk space,
   new metadata and unresolved legacy assumptions.
4. Apply versioned idempotent migrations to a copy, verify it, then activate
   through an atomic/recoverable switch.
5. Keep the previous version usable for rollback and preserve migration logs.
6. Mark old evidence according to what it established. Do not upgrade an old
   `verified` package to reasoning-reviewed or machine-checked.
7. Migrate old review approvals only as historical records. Current approval
   must match the current revision and declared scope.

Older workspaces remain readable. New authoring sessions default to the
expanded evidence profile after the prerequisites land. Any explicit legacy
workflow is clearly labelled as missing the new correctness review, and cannot
bypass repaired execution/integrity gates. Decide the exact legacy export
compatibility behavior in T54 and test it before enabling the new default.

Incrementally add schemas behind capability flags rather than changing every
workspace on import. Feature flags control capability exposure, not permission
to falsify result states. Remove flags only after migration and rollback have
been rehearsed.

## 6. Backup, retention and recovery

Classify backups: package-only, authoring metadata, conversation/checkpoint and
private application configuration. Encrypt or otherwise protect private exports
according to the target environment. Support bundles use a documented redaction
and artifact-allowlist policy, and are reviewable before sharing.

Retention is explicit and visible: never drop unreviewed changes or silently
erase historical proof/findings. Keep source originals and superseded evidence.
Storage estimates and archive suggestions precede cleanup. Destructive cleanup
is a separate authorized action with verified target paths.

Recovery rehearsal must restore a complete session on a fresh local instance,
verify package and journal hashes, recover open findings and pending approvals
without replaying side effects, and reproduce an allowed diagnostic campaign.
Also rehearse disk-full, interrupted atomic replace, corrupt JSON/SQLite and
partial worker publication. A parse error must not quietly create a new empty
workspace or grant set.

## 7. Rollout slices

| Slice | Enable | Required fallback/rollback |
|---|---|---|
| Integrity repairs | Canonical policy, fail-closed execution, unified report lifecycle | Disable affected operation with an explicit error if worker/schema unsupported |
| Revisions/journal | Transactional writes and staged results | Restore pre-migration copy and previous application version |
| Evidence records | Additive specification/obligations/findings | Keep legacy files readable, label missing evidence |
| Deep skills/tools | Versioned resource packs and bounded campaigns | Disable incompatible pack/operation, retain generated artifacts and logs |
| Readiness UI | New facets/findings with revision links | Fall back to read-only evidence presentation without asserting readiness |
| Developer beta | Supported profiles plus tested migration/install | Preserve previous release, backup and migration report |
| Formal pilot | Explicit opt-in checker/profile | Leave proof status unavailable/incomplete, never infer it from prose |

Each slice receives current source-bound tests before wider use. No automatic
merge, deployment, installation or provider run follows from the plan itself.

## 8. Documentation and product claims

Create one current capability matrix: feature, profile, implemented state,
validation state, environment fingerprint, evidence and limitation. The README
routes to it. Keep older plans/evals as dated historical records with clear
links forward. Do not overwrite a past failed result with a later success.

Update usage, demo, troubleshooting, technical deep dive and module map when
behavior changes. Make unsupported capability states visible in the app.
Distinguish optional tests skipped from passed tests, reviewed arguments from
formal proofs, and sampled runtime measurements from worst-case guarantees.

## 9. Risks and decisions to revisit

| Risk | Mitigation / decision point |
|---|---|
| Scope grows faster than validated knowledge | Finish three deep domains before broadening tags or roles |
| Formalization consumes the project | Keep T55 selective and after the everyday workflow/eval foundation |
| Reviewers share blind spots | Independent simple oracles, diverse formulations and human rubric review |
| Evidence tracking becomes excessive author work | Auto-capture deterministic provenance, show compact actionable summaries |
| Immutable staging is slow for large test data | Content-addressed reuse with correct visibility/permissions, measured performance |
| Worker privilege remains high | Least-privilege spike, isolated deployment choices, explicit residual boundary |
| Storage/retention grows | Content deduplication and user-visible archival policy, no silent deletion |
| New checks block legitimate packages | Correct controls, profile-specific requirements and evidence-based overrides |
| Provider/model changes invalidate behavior | Configuration fingerprints and bounded requalification benchmark |
| Migration loses history or approvals | Dry-run, immutable backup, rollback rehearsal and no automatic approval upgrade |

Decisions need resolving during implementation: metadata/journal storage,
exact schema/profile versions, worker authentication defaults, compatibility of
legacy export, formal checker choice, supported toolchain matrix and evaluation
spend limits. The plan supplies defaults and acceptance criteria so these do not
prevent independent preparation of code contracts, fixtures and content.
