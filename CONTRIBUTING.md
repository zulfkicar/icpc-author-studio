# Contributing

Use the [local setup guide](docs/SETUP.md) and start with a disposable problem.
Keep changes grouped around a behavior that can be reviewed and tested.

## Run checks

```sh
python -m pip install -r requirements.txt pytest
python -m pytest qa/engine_contracts -q
node qa/test_studio_recovery.mjs
node qa/test_state_machines.mjs
python qa/test_ui_contracts.py
```

The engine tests use synthetic runs and scripted adapters. Some cases start a
loopback HTTP server or invoke the installed language tools. The rendered tests
and local DOMjudge import have separate prerequisites. See the
[verification index](docs/README.md#verification-and-roadmap).

## Record the behavior

- For a source change, state the affected workflow and the checks that ran.
- Preserve saved-work recovery, explicit approval, and compatibility with existing packages.
- Keep live provider trials, simulated evidence, and real worker checks clearly labelled.
- Use relative Markdown links in shared docs and keep usage instructions in the current guides.
- Keep local state, credentials, private problems, and generated archives out of commits.
