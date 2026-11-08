# ICPC Problem Package Format

Author packages against the ICPC subset:
<httpC://Projects.io/problem-package-format/spec/legacy-icpc.html>

Required layout:

```text
problem.yaml
problem_statement/problem.en.tex
data/sample/*.in *.ans
data/secret/**/*.in *.ans
submissions/accepted/<reference>
input_validators/<validator>
output_validators/<validator>        # only when validation is custom
```

Rules that the deterministic verifier enforces:

1. `input_validators/` programs receive the input on stdin and must exit **42**
   when it is valid. Any other code means invalid or broken.
2. `output_validators/` programs are invoked as
   `<validator> input answer feedback_dir [validator_flags]` with the team
   output on **stdin**. Exit **42** means accepted, **43** means wrong answer,
   and any other code is a validator failure.
3. `validation` starts with `default` or `custom`. Use `custom` for a checker
   and `custom interactive` for an interactor. Interactive packages also need
   `data/sample/*.interaction` files whose non-empty lines start with `>` or `<`.
4. Use `problem_statement/` (the 2025-09 draft calls it `statement/`; both are
   accepted). A LaTeX statement must contain `\problemname`.
5. `limits.memory` is in MiB. `domjudge-problem.ini` may add a DOMjudge
   `timelimit`; both are read.
6. Test data is UTF-8 with LF line endings. Answers must exist for every test.
7. Test groups live in `test_group.yaml` (or a map-of-maps `testdata.yaml`) with
   `points` and `depends`/`dependencies`. A group earns points only when its
   own tests and all dependencies pass.

`templates/testlib.h` is copied into the build directory automatically, so a
C++ checker or interactor may `#include "testlib.h"`.
