"""OpenAI-compatible fault-injection proxy for provider failure tests.

Run modes are set on the server object:

* ``ok``              always answer normally
* ``429``             always answer HTTP 429
* ``429-once``        answer 429 once, then normally
* ``disconnect``      send a partial SSE stream and close the socket
* ``refusal``         stream a refusal content block
* ``no-tools``        answer with text even when tools are requested
* ``no-tool-calling`` answer with a clear error when tools are requested

This is a real HTTP server on loopback, so it exercises the provider client,
retry middleware and error paths over sockets rather than monkeypatching.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = "fault-injection-model"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _json(self, value: dict, status: int = 200, headers: dict | None = None) -> None:
        body = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for key, item in (headers or {}).items():
            self.send_header(key, item)
        self.end_headers()
        self.wfile.write(body)

    def _chunk(self, delta: dict, finish: str | None = None, usage: dict | None = None) -> bytes:
        payload = {
            "id": "chatcmpl-fault",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": MODEL,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        if usage:
            payload["usage"] = usage
        return f"data: {json.dumps(payload)}\n\n".encode("utf-8")

    def _stream(self, deltas: list[dict]) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        for delta in deltas:
            self.wfile.write(self._chunk(delta))
            self.wfile.flush()
        self.wfile.write(self._chunk({}, finish="stop", usage={"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}))
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except ValueError:
            body = {}
        mode = getattr(self.server, "mode", "ok")
        with self.server.lock:
            self.server.count += 1
            count = self.server.count
        if mode == "429" or (mode == "429-once" and count == 1):
            return self._json(
                {"error": {"message": "rate limited by fault proxy", "type": "rate_limit_error"}},
                status=429,
                headers={"Retry-After": "0"},
            )
        if mode == "disconnect":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(self._chunk({"role": "assistant", "content": "partial"}))
            self.wfile.flush()
            self.close_connection = True
            try:
                self.connection.close()
            except OSError:
                pass
            return
        if mode == "no-tool-calling" and body.get("tools"):
            return self._json(
                {"error": {"message": "this model does not support tool calling", "type": "invalid_request_error"}},
                status=400,
            )
        if mode == "refusal":
            self._stream([
                {"role": "assistant", "content": [{"type": "refusal", "refusal": "I cannot help with that request."}]},
            ])
            return
        text = "fault-proxy-ok" if mode in ("ok", "429-once") else "fault-proxy-text"
        if body.get("stream"):
            self._stream([{"role": "assistant", "content": text}])
            return
        return self._json({
            "id": "chatcmpl-fault",
            "object": "chat.completion",
            "created": 0,
            "model": MODEL,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
        })


class FaultServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, mode: str = "ok"):
        super().__init__(("127.0.0.1", 0), Handler)
        self.mode = mode
        self.count = 0
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host}:{port}/v1"

    def start(self) -> "FaultServer":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.shutdown()
        self.server_close()
