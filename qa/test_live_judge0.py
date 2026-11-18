"""Live Judge0 stack test (requires the judge0 compose services)."""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from author_studio import config
from author_studio.judging import judge0_adapter


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS {name}")
        return
    print(f"  FAIL {name} {detail}")
    raise AssertionError(name)


def main() -> int:
    cfg = config.load()
    base = str(cfg.get("judge0Url") or "")
    if not base:
        print("SKIP live Judge0: judge0Url is not configured")
        return 0
    cpp = '#include <iostream>\nint main(){long long a,b;std::cin>>a>>b;std::cout<<a+b<<"\\n";}\n'
    result = judge0_adapter.quick_run(cpp, "cpp", "2 3", base_url=base, token=str(cfg.get("judge0Token") or ""))
    check("live judge0 accepted", result.get("ok") and result.get("stdout") == "5\n", result)
    check("live judge0 status", result.get("status") == "Accepted", result)
    check("live judge0 not authority", result.get("verificationAuthority") is False, result)
    result = judge0_adapter.run_file(
        "sum-test", "submissions/accepted/ref.cpp", "4 5",
        base_url=base, token=str(cfg.get("judge0Token") or ""),
    )
    check("live judge0 workspace file", result.get("ok") and result.get("stdout") == "9\n", result)
    print("LIVE JUDGE0 TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
