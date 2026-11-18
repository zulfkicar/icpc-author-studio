# V0-V3 fixtures

These fixtures are independent of the production controller and can be reviewed
without reading graph code.

- `instances.json` — hand-checked scheduling instances, expected optima, legal
  negative controls and the invalid “omits empty choice” defect label.
- `candidates/*.cpp` — reviewable C++20-shaped candidate controls. They contain a
  `// fake-behavior:` marker so the **simulated** worker can deterministically
  reproduce their behaviour without compiling. The real `IsolateWorker` ignores
  the marker and compiles the source; no generated code is run on the host.

The fake worker is a mechanics seam. It does not establish C++ correctness,
compiler behaviour, resource control or containment. `real-worker-tested` stays
false until an `AUTHOR_AGENT_ISOLATE_URL` endpoint is available and qualified.

`dp_correct.cpp` and `sweep_line_correct.cpp` are correct controls and must
survive review. `dp_strict.cpp` is the half-open predecessor defect.
`dp_base_error.cpp` is a real index defect, not the invalid empty-choice label.
