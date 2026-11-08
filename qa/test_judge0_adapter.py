"""Judge0 adapter contract against a local fake Judge0 server."""
from __future__ import annotations

import json
import pathlib
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import judge0_adapter


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        if body.get("source_code") == "compile-error":
            payload = {
                "token": "t1", "status": {"id": 6, "description": "Compilation Error"},
                "stdout": None, "stderr": None, "compile_output": "error: expected ;",
                "message": None, "time": "0.01", "memory": 100,
            }
        else:
            payload = {
                "token": "t2", "status": {"id": 3, "description": "Accepted"},
                "stdout": "42\n", "stderr": None, "compile_output": None,
                "message": None, "time": "0.02", "memory": 2048,
            }
        data = json.dumps(payload).encode("utf-8")
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS {name}")
        return
    print(f"  FAIL {name} {detail}")
    raise AssertionError(name)


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        result = judge0_adapter.quick_run("int main(){}", "cpp", "", base_url=base)
        check("judge0 accepted", result["ok"] and result["stdout"] == "42\n", result)
        check("judge0 is not authority", result["verificationAuthority"] is False and result["source"] == "judge0", result)
        check("judge0 metadata", result["status"] == "Accepted" and result["memory"] == 2048, result)
        broken = judge0_adapter.quick_run("compile-error", "cpp", "", base_url=base)
        check("judge0 compile error surfaced", not broken["ok"] and "expected ;" in broken["compileOutput"], broken)
        try:
            judge0_adapter.quick_run("x", "racket", "", base_url=base)
        except ValueError:
            check("judge0 rejects unknown language", True)
        else:
            check("judge0 rejects unknown language", False)
    finally:
        server.shutdown()
        server.server_close()
    print("JUDGE0 ADAPTER TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
