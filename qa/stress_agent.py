"""Stress and regression suite for the authoring runtime.

Uses a fake chat model so it is deterministic and does not spend provider tokens.
Run with: python qa/stress_agent.py
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import os
import pathlib
import shutil
import sys
import time
import traceback
from typing import List

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from author_studio import config
from author_studio.classic import graph_agent
from author_studio import server
from author_studio.packages import workspace

FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL {name} {detail}")


class FailingChat(BaseChatModel):
    @property
    def _llm_type(self): return 'failing'
    def bind_tools(self, tools, **kwargs): return self
    def _generate(self, messages, stop=None, run_manager=None, **kwargs): raise ConnectionError('stream disconnected')
    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs): raise ConnectionError('stream disconnected')


class FakeChat(BaseChatModel):
    responses: List[AIMessage] = []
    delay: float = 0.0
    long_text: bool = False
    auto_text: str = "ok"

    @property
    def _llm_type(self) -> str:
        return "fake-stress"

    def bind_tools(self, tools, **kwargs):
        return self

    @staticmethod
    def _is_summary(messages: List[BaseMessage]) -> bool:
        if not messages:
            return False
        text = str(getattr(messages[-1], "content", "") or "")
        return "Context Extraction Assistant" in text or "<primary_objective>" in text

    def _next(self, messages: List[BaseMessage]) -> AIMessage:
        if self._is_summary(messages):
            return AIMessage(content="SUMMARY: earlier authoring work and decisions.")
        if self.responses:
            return self.responses.pop(0)
        if self.long_text:
            return AIMessage(content="Long working note. " * 80, usage_metadata={"input_tokens": 20, "output_tokens": 5, "total_tokens": 25})
        return AIMessage(content=self.auto_text, usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12})

    def _generate(self, messages: List[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next(messages))])

    async def _agenerate(self, messages: List[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        if self.delay:
            await asyncio.sleep(self.delay)
        return ChatResult(generations=[ChatGeneration(message=self._next(messages))])


def make_workspace(label: str) -> tuple[str, str]:
    created = workspace.create(label, "stress test workspace")
    slug = created["slug"]
    chat_id = workspace.ensure_chats(slug)["activeChat"]
    return slug, chat_id


def cleanup(slug: str) -> None:
    shutil.rmtree(workspace.ws_path(slug), ignore_errors=True)


def use_model(model: FakeChat) -> None:
    graph_agent._model = lambda cfg: model


def run_durability() -> None:
    print("durability / usage / todo")
    slug, chat_id = make_workspace("QA Durability")
    try:
        model = FakeChat(responses=[
            AIMessage(content="planning", tool_calls=[{"name": "write_todos", "args": {"todos": [{"content": "Write ref", "status": "in_progress"}]}, "id": "t1"}]),
            AIMessage(content="first", usage_metadata={"input_tokens": 100, "output_tokens": 4, "total_tokens": 104}),
        ])
        use_model(model)
        result = graph_agent.run_turn(slug, chat_id, "one", lambda *_: None)
        check("turn one text", result["text"] == "first", result["text"])
        check("usage captured", result["usage"].get("input_tokens") == 100, result["usage"])
        check("todo mirrored", workspace.get_plan(slug, chat_id)["steps"][0]["title"] == "Write ref")
        use_model(FakeChat(auto_text="second"))
        result = graph_agent.run_turn(slug, chat_id, "two", lambda *_: None)
        check("turn two text", result["text"] == "second", result["text"])
        chat = workspace.get_chat(slug, chat_id)
        check("durable history", [m["role"] for m in chat["messages"]].count("user") == 2, [m["role"] for m in chat["messages"]])
    finally:
        cleanup(slug)


def run_hitl() -> None:
    print("HITL export approval")
    slug, chat_id = make_workspace("QA HITL")
    try:
        use_model(FakeChat(responses=[
            AIMessage(content="export", tool_calls=[{"name": "export_package", "args": {}, "id": "e1"}]),
            AIMessage(content="after approval"),
        ]))
        result = graph_agent.run_turn(slug, chat_id, "export", lambda *_: None)
        check("paused", result["paused"] and len(result["interrupts"]) == 1, result)
        check("pending persisted", len(workspace.get_pending(slug, chat_id)) == 1)
        decisions = {item["id"]: {"type": "approve"} for item in result["interrupts"]}
        use_model(FakeChat(auto_text="resumed"))
        resumed = graph_agent.resume_turn(slug, chat_id, decisions, lambda *_: None)
        check("resumed", not resumed["paused"], resumed)
        check("pending cleared", workspace.get_pending(slug, chat_id) == [])
    finally:
        cleanup(slug)


def run_parallel_skills() -> None:
    print("parallel skill loads")
    slug, chat_id = make_workspace("QA Parallel Skills")
    try:
        use_model(FakeChat(responses=[
            AIMessage(content="", tool_calls=[
                {"name": "load_skill", "args": {"name": "constraints"}, "id": "s1"},
                {"name": "load_skill", "args": {"name": "test-design"}, "id": "s2"},
            ]),
            AIMessage(content="loaded"),
        ]))
        result = graph_agent.run_turn(slug, chat_id, "load both", lambda *_: None)
        check("parallel skill loads complete", result.get("text") == "loaded", result)
        messages = workspace.get_chat(slug, chat_id)["messages"]
        check("skill result recorded", any("Loaded skill" in str(item.get("content")) for item in messages), messages)
    finally:
        cleanup(slug)


def run_clarification() -> None:
    print("clarification")
    slug, chat_id = make_workspace("QA Clarification")
    try:
        use_model(FakeChat(responses=[
            AIMessage(content="", tool_calls=[{
                "name": "ask_user",
                "args": {
                    "questions": ["Should the output be a+b or a-b?"],
                    "context": "The statement and checker disagree.",
                    "options": ["a+b", "a-b"],
                    "recommended": "a+b",
                },
                "id": "q1",
            }]),
            AIMessage(content="clarified"),
        ]))
        result = graph_agent.run_turn(slug, chat_id, "author", lambda *_: None)
        check("clarification paused", result["paused"] and result["interrupts"][0]["value"].get("type") == "clarification", result)
        use_model(FakeChat(auto_text="clarified"))
        resumed = graph_agent.resume_turn(slug, chat_id, None, lambda *_: None, clarification={"answers": ["a+b"]})
        check("clarification resumed", not resumed["paused"] and resumed["text"] == "clarified", resumed)
        check("clarification recorded", bool(workspace.get_chat(slug, chat_id).get("clarifications")), workspace.get_chat(slug, chat_id).get("clarifications"))
    finally:
        cleanup(slug)


def run_provider_failure() -> None:
    print("provider failure")
    slug, chat_id = make_workspace("QA Provider Failure")
    try:
        use_model(FailingChat())
        error = None
        try:
            graph_agent.run_turn(slug, chat_id, "fail", lambda *_: None)
        except Exception as exc:
            error = exc
        check("provider failure surfaced", error is not None, error)
        messages = workspace.get_chat(slug, chat_id)["messages"]
        check("failed user turn preserved", messages and messages[-1].get("role") == "user", messages)
    finally:
        cleanup(slug)


def run_history_restore() -> None:
    print("conversation history restore")
    slug, chat_id = make_workspace("QA History")
    try:
        use_model(FakeChat(auto_text="first"))
        graph_agent.run_turn(slug, chat_id, "one", lambda *_: None)
        history = graph_agent.list_history(slug, chat_id)
        check("history listed", bool(history) and bool(history[0].get("checkpointId")), history)
        target = next((item for item in history if item.get("messages", 0) > 0), history[-1])
        result = graph_agent.restore_history(slug, chat_id, target["checkpointId"])
        check("history restored", result.get("restored") is True, result)
        check("restored transcript", len(workspace.get_chat(slug, chat_id)["messages"]) >= 2, workspace.get_chat(slug, chat_id)["messages"])
    finally:
        cleanup(slug)


def run_review_write() -> None:
    print("review-mode write approval")
    slug, chat_id = make_workspace("QA Review Write")
    original = graph_agent.config.load
    try:
        use_model(FakeChat(responses=[
            AIMessage(content="write", tool_calls=[{"name": "write_file", "args": {"path": "NOTES.md", "content": "approved"}, "id": "w1"}]),
            AIMessage(content="done"),
        ]))
        graph_agent.config.load = lambda: {**original(), "reviewWrites": True}
        result = graph_agent.run_turn(slug, chat_id, "write", lambda *_: None)
        check("write paused", result["paused"], result)
        decisions = {item["id"]: {"type": "approve"} for item in result["interrupts"]}
        use_model(FakeChat(auto_text="written"))
        graph_agent.resume_turn(slug, chat_id, decisions, lambda *_: None)
        content = (workspace.ws_path(slug) / "NOTES.md").read_text("utf-8")
        check("approved write applied", content == "approved", content)
    finally:
        graph_agent.config.load = original
        cleanup(slug)


def run_checkpoint_repair() -> None:
    print("checkpoint repair")
    slug, chat_id = make_workspace("QA Repair")

    async def poison() -> None:
        cfg = original_config()
        cfg["summaryTriggerTokens"] = 1000
        async with AsyncSqliteSaver.from_conn_string(str(workspace.checkpoint_path(slug))) as saver:
            await saver.setup()
            graph, _ = graph_agent._graph(cfg, saver)
            await graph.aupdate_state(
                {"configurable": {"thread_id": chat_id}},
                {
                    "messages": [
                        HumanMessage(content="old"),
                        AIMessage(content="", tool_calls=[{"name": "list_files", "args": {}, "id": "missing-tool"}]),
                    ],
                    "slug": slug,
                    "chat_id": chat_id,
                    "decisions": [],
                },
            )

    original_config = graph_agent.config.load
    try:
        asyncio.run(poison())
        use_model(FakeChat(auto_text="repaired"))
        result = graph_agent.run_turn(slug, chat_id, "continue", lambda *_: None)
        check("repair allowed next turn", result["text"] == "repaired", result)
        roles = [m["role"] for m in workspace.get_chat(slug, chat_id)["messages"]]
        check("no orphan tool message", "tool" not in roles or roles.count("tool") == 0, roles)
    finally:
        cleanup(slug)


def run_summarization() -> None:
    print("summarization trigger")
    old_trigger = os.environ.get("AUTHOR_AGENT_SUMMARY_TRIGGER_TOKENS")
    old_keep = os.environ.get("AUTHOR_AGENT_SUMMARY_KEEP_MESSAGES")
    os.environ["AUTHOR_AGENT_SUMMARY_TRIGGER_TOKENS"] = "80"
    os.environ["AUTHOR_AGENT_SUMMARY_KEEP_MESSAGES"] = "2"
    slug, chat_id = make_workspace("QA Summary")
    try:
        use_model(FakeChat(long_text=True))
        for index in range(6):
            graph_agent.run_turn(slug, chat_id, f"long turn {index}", lambda *_: None)
        messages = workspace.get_chat(slug, chat_id)["messages"]
        text = "\n".join(str(m.get("content") or "") for m in messages)
        check("summary appeared", "SUMMARY" in text, text[-500:])
        check("history compacted", len(messages) < 14, len(messages))
    finally:
        if old_trigger is None:
            os.environ.pop("AUTHOR_AGENT_SUMMARY_TRIGGER_TOKENS", None)
        else:
            os.environ["AUTHOR_AGENT_SUMMARY_TRIGGER_TOKENS"] = old_trigger
        if old_keep is None:
            os.environ.pop("AUTHOR_AGENT_SUMMARY_KEEP_MESSAGES", None)
        else:
            os.environ["AUTHOR_AGENT_SUMMARY_KEEP_MESSAGES"] = old_keep
        cleanup(slug)


def run_concurrency() -> None:
    print("concurrent workspaces")
    created = [make_workspace(f"QA Concurrent {i}") for i in range(5)]
    use_model(FakeChat(delay=0.02, auto_text="concurrent ok"))

    def job(pair):
        slug, chat_id = pair
        return graph_agent.run_turn(slug, chat_id, "work", lambda *_: None)["text"]

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(job, created))
        check("all concurrent turns completed", results == ["concurrent ok"] * 5, results)
    finally:
        for slug, _ in created:
            cleanup(slug)


def run_cancellation() -> None:
    print("cancellation")
    slug, chat_id = make_workspace("QA Cancel")
    try:
        use_model(FakeChat(delay=5, auto_text="slow"))
        started = time.time()
        error = None
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(graph_agent.run_turn, slug, chat_id, "slow", lambda *_: None)
            time.sleep(0.5)
            check("task registered", graph_agent.cancel_turn(slug, chat_id))
            try:
                future.result(timeout=5)
            except Exception as exc:
                error = exc
        elapsed = time.time() - started
        check("cancelled promptly", elapsed < 3.0, elapsed)
        check("cancellation surfaced", error is not None and "cancel" in str(error).lower(), error)
    finally:
        cleanup(slug)


def run_same_workspace_serialization() -> None:
    print("same-workspace serialization")
    slug, first_chat = make_workspace("QA Serialized")
    chats = [first_chat, workspace.create_chat(slug, "second")["id"], workspace.create_chat(slug, "third")["id"]]
    use_model(FakeChat(auto_text="serialized"))
    try:
        def job(chat_id):
            with server.workspace_lock(slug):
                return graph_agent.run_turn(slug, chat_id, "work", lambda *_: None)["text"]

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(job, chats))
        check("serialized turns completed", results == ["serialized"] * 3, results)
    finally:
        cleanup(slug)


def run_server_cancel() -> None:
    print("server cancellation")
    slug, chat_id = make_workspace("QA Server Cancel")
    try:
        use_model(FakeChat(delay=5, auto_text="slow"))
        job = server.start_job("cancel test", slug, lambda emit, cancelled: graph_agent.run_turn(slug, chat_id, "slow", emit, cancelled), chat_id=chat_id)
        time.sleep(0.6)
        server.JOBS[job["id"]]["cancelRequested"] = True
        check("server task cancelled", graph_agent.cancel_turn(slug, chat_id))
        state = "running"
        for _ in range(60):
            time.sleep(0.1)
            state = server.JOBS[job["id"]]["state"]
            if state != "running":
                break
        check("server job cancelled", state == "cancelled", state)
    finally:
        cleanup(slug)


def run_file_management() -> None:
    print("file and folder management")
    slug, _ = make_workspace("QA File Management")
    try:
        workspace.create_folder(slug, "qa_folder")
        workspace.create_file(slug, "qa_folder/note.txt", "hello")
        check("file created", (workspace.ws_path(slug) / "qa_folder" / "note.txt").read_text("utf-8") == "hello")
        workspace.rename_entry(slug, "qa_folder/note.txt", "qa_folder/renamed.txt")
        check("file renamed", (workspace.ws_path(slug) / "qa_folder" / "renamed.txt").is_file())
        workspace.delete_entry(slug, "qa_folder")
        check("folder deleted", not (workspace.ws_path(slug) / "qa_folder").exists())
    finally:
        cleanup(slug)


def run_cost_meter() -> None:
    print("cost meter")
    slug, chat_id = make_workspace("QA Cost")
    original = graph_agent.config.load
    try:
        use_model(FakeChat(responses=[AIMessage(
            content="priced",
            usage_metadata={"input_tokens": 100, "output_tokens": 4, "total_tokens": 104},
        )]))
        graph_agent.config.load = lambda: {
            **original(), "inputPricePerMillion": 1.0, "outputPricePerMillion": 2.0,
            "summaryTriggerTokens": 30000,
        }
        result = graph_agent.run_turn(slug, chat_id, "price", lambda *_: None)
        check("cost computed", abs(float(result["usage"].get("costUsd", 0)) - 0.000108) < 1e-9, result["usage"])
    finally:
        graph_agent.config.load = original
        cleanup(slug)


def run_chat_management() -> None:
    print("chat management")
    slug, chat_id = make_workspace("QA Chat Management")
    try:
        renamed = workspace.rename_chat(slug, chat_id, "Renamed chat")
        check("rename persisted", renamed["title"] == "Renamed chat", renamed)
        workspace.delete_chat(slug, chat_id)
        index = workspace.list_chats(slug)
        check("chat deleted", all(item["id"] != chat_id for item in index["chats"]), index)
        check("replacement chat exists", bool(index["chats"]), index)
    finally:
        cleanup(slug)


def run_reviewer() -> None:
    print("reviewer")
    slug, _ = make_workspace("QA Reviewer")
    try:
        use_model(FakeChat(auto_text="Reviewer says: add a max case."))
        result = asyncio.run(graph_agent.review_package.coroutine(request="review", state={"slug": slug, "chat_id": "reviewer"}))
        check("reviewer returned findings", "max case" in result.get("review", ""), result)
    finally:
        cleanup(slug)


def original_config() -> dict:
    return config.load()


def main() -> int:
    tests = [
        run_durability,
        run_hitl,
        run_parallel_skills,
        run_clarification,
        run_provider_failure,
        run_history_restore,
        run_review_write,
        run_checkpoint_repair,
        run_summarization,
        run_concurrency,
        run_cancellation,
        run_same_workspace_serialization,
        run_server_cancel,
        run_cost_meter,
        run_file_management,
        run_chat_management,
        run_reviewer,
    ]
    for test in tests:
        try:
            test()
        except Exception:
            FAILED.append(test.__name__)
            print(f"  ERROR {test.__name__}")
            traceback.print_exc()
    print()
    if FAILED:
        print("FAILED:", ", ".join(FAILED))
        return 1
    print("ALL STRESS TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
