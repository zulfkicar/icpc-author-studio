# Local trust boundaries

Author Studio is a single-user local application. Bind it to loopback and keep
it on a machine you control. The HTTP routes operate with the local user's
authority over the configured workspace roots.

- **Provider credentials** are saved in `.author-agent/config.json` or supplied through the local environment. Keep those files, `.env`, and any credential export out of commits, screenshots and shared logs. `.env.example` contains empty fields for first-time setup.
- **Manual execution** uses local toolchains. Run saved code you trust or use a configured isolated worker for applicable investigation paths. The sample's simulated worker and local process receipts carry separate labels.
- **Saved package effects** are scoped to the workspace. Export uses a verified and human-approved snapshot. Recheck the saved files and provenance before sharing a ZIP.
- **Provider requests** can contain selected chat and artifact context. Review the target and intended material before using a live provider with private contest work.

To report a security problem, contact the maintainer privately. Include the
affected version, observed behavior and a synthetic reproduction. Keep keys,
private contest cases and personal data out of the report.
