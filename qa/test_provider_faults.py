"""Real HTTP provider fault injection: 429, disconnect, refusal, no tools."""
from __future__ import annotations

import os
import pathlib
import shutil
import sys
import warnings

warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "qa"))

from langchain_core.exceptions import ModelRefusalError

import graph_agent
import workspace
from fault_proxy import FaultServer


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS {name}")
        return
    print(f"  FAIL {name} {detail}")
    raise AssertionError(name)


def make_workspace(name: str) -> tuple[str, str]:
    created = workspace.create(name, "provider fault injection")
    slug = created["slug"]
    chat = workspace.ensure_chats(slug)["activeChat"]
    return slug, chat


def use(server: FaultServer) -> None:
    os.environ["AUTHOR_AGENT_BASE_URL"] = server.base_url
    os.environ["AUTHOR_AGENT_API_KEY"] = "fault-injection-key"
    os.environ["AUTHOR_AGENT_MODEL"] = "fault-injection-model"


def clear() -> None:
    for key in ("AUTHOR_AGENT_BASE_URL", "AUTHOR_AGENT_API_KEY", "AUTHOR_AGENT_MODEL"):
        os.environ.pop(key, None)


def main() -> int:
    # 429 once, then success: retry middleware must recover.
    server = FaultServer("429-once").start()
    use(server)
    slug, chat = make_workspace("QA Fault Retry")
    try:
        result = graph_agent.run_turn(slug, chat, "say ok", lambda *_: None)
        check("429 retried to success", "fault-proxy-ok" in str(result.get("text")), result)
        check("429 proxy saw two requests", server.count >= 2, server.count)
    finally:
        server.stop()
        clear()
        shutil.rmtree(workspace.ws_path(slug), ignore_errors=True)

    # Stream disconnect: surfaced as an error, never a false success.
    server = FaultServer("disconnect").start()
    use(server)
    slug, chat = make_workspace("QA Fault Disconnect")
    try:
        error = None
        try:
            graph_agent.run_turn(slug, chat, "say ok", lambda *_: None)
        except Exception as exc:  # noqa: BLE001
            error = exc
        check("stream disconnect surfaced", error is not None, error)
        check("disconnect is not a false success", not isinstance(error, type(None)), error)
    finally:
        server.stop()
        clear()
        shutil.rmtree(workspace.ws_path(slug), ignore_errors=True)

    # Provider refusal: surfaced as ModelRefusalError.
    server = FaultServer("refusal").start()
    use(server)
    slug, chat = make_workspace("QA Fault Refusal")
    try:
        error = None
        try:
            graph_agent.run_turn(slug, chat, "do something disallowed", lambda *_: None)
        except ModelRefusalError as exc:
            error = exc
        check("provider refusal surfaced", isinstance(error, ModelRefusalError), error)
    finally:
        server.stop()
        clear()
        shutil.rmtree(workspace.ws_path(slug), ignore_errors=True)

    # Model without tool calling: clear failure, not a false success.
    server = FaultServer("no-tool-calling").start()
    use(server)
    slug, chat = make_workspace("QA Fault Tools")
    try:
        error = None
        try:
            graph_agent.run_turn(slug, chat, "use a tool", lambda *_: None)
        except Exception as exc:  # noqa: BLE001
            error = exc
        check("missing tool calling surfaced", error is not None, error)
        check("tool error is explanatory", "tool" in str(error).lower() or "400" in str(error), error)
    finally:
        server.stop()
        clear()
        shutil.rmtree(workspace.ws_path(slug), ignore_errors=True)

    # Model returns text when tools are available: a valid final answer.
    server = FaultServer("no-tools").start()
    use(server)
    slug, chat = make_workspace("QA Fault Text")
    try:
        result = graph_agent.run_turn(slug, chat, "just answer", lambda *_: None)
        check("text answer without tool calls", "fault-proxy-text" in str(result.get("text")), result)
    finally:
        server.stop()
        clear()
        shutil.rmtree(workspace.ws_path(slug), ignore_errors=True)

    print("PROVIDER FAULT TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
