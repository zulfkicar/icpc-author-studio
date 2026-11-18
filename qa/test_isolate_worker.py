"""Live real-Isolate backend: compile, run, limits, network and filesystem."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import isolate_client


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS {name}")
        return
    print(f"  FAIL {name} {detail}")
    raise AssertionError(name)


def main() -> int:
    if not os.environ.get("AUTHOR_AGENT_ISOLATE_URL"):
        print("SKIP isolate worker: AUTHOR_AGENT_ISOLATE_URL is not set")
        return 0
    health = isolate_client.health()
    check("isolate health", health.get("ok") and "isolator" in str(health.get("isolate")).lower(), health)

    cpp = '#include <iostream>\nint main(){long long a,b;std::cin>>a>>b;std::cout<<a+b<<"\\n";}\n'
    result = isolate_client.run(cpp, "cpp", "2 3", time_limit=2, memory_mb=256)
    check("isolate cpp accepted", result.get("ok") and result.get("stdout") == "5\n", result)
    check("isolate metadata", result.get("isolate") and result.get("status") == "OK" and result.get("memory", 0) > 0, result)
    check("isolate not authority", result.get("verificationAuthority") is False, result)

    result = isolate_client.run("int main() { broken", "cpp", "", time_limit=2, memory_mb=256)
    check("isolate compile error", result.get("status") == "CE" and result.get("compileOutput"), result)

    result = isolate_client.run("while True:\n    pass\n", "py", "", time_limit=1, wall_time=3, memory_mb=128)
    check("isolate wall time", result.get("status") in ("TO", "TL"), result)

    result = isolate_client.run("x = bytearray(512 * 1024 * 1024)\nprint(len(x))\n", "py", "", time_limit=3, wall_time=8, memory_mb=32)
    check("isolate memory limit", result.get("status") in ("ML", "RE", "SG") and result.get("exit") != 0, result)

    net = (
        "import socket, sys\n"
        "s=socket.socket(); s.settimeout(1)\n"
        "try:\n"
        "    s.connect(('1.1.1.1', 80)); print('NETWORK_OPEN')\n"
        "except Exception:\n"
        "    print('NETWORK_BLOCKED')\n"
    )
    result = isolate_client.run(net, "py", "", time_limit=3, wall_time=8, memory_mb=128)
    check("isolate network blocked", "NETWORK_BLOCKED" in result.get("stdout", ""), result)

    readonly = (
        "try:\n"
        "    open('/etc/isolate-write', 'w').write('x'); print('WROTE')\n"
        "except Exception:\n"
        "    print('READONLY')\n"
    )
    result = isolate_client.run(readonly, "py", "", time_limit=3, wall_time=8, memory_mb=128)
    check("isolate root read-only", "READONLY" in result.get("stdout", ""), result)

    flood = "open('big.bin','wb').write(b'x' * (2*1024*1024))\nprint('WROTE')\n"
    result = isolate_client.run(flood, "py", "", time_limit=3, wall_time=8, memory_mb=128, fsize_mb=1)
    check("isolate file-size limit", result.get("status") != "OK" or result.get("exit") != 0, result)
    print("ISOLATE WORKER TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
