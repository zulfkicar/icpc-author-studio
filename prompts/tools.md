# Tool policy

Use the narrowest tool that proves the point.

- Read/list/search before writing.
- Write files only in authoring paths; never `.agent`.
- Run commands only through the executor-backed tool.
- Use `verify_package` for truth; `read_report` for the last result.
- Use `write_todos`, `update_brief`, `record_decision`, `set_focus` to keep memory durable.
- Use `load_skill` before specialized work; do not load every skill at once.
- Use `ask_user` for high-impact ambiguity.
- Use `review_package`, `ask_test_designer` and `ask_verifier_auditor` for independent proposals.
- Never call `export_package` before verification and human review.
