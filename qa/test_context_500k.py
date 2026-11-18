"""Synthetic 500k-token compaction test (no provider cost)."""
import os
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from author_studio.classic import graph_agent
from author_studio.packages import workspace
from qa.stress_agent import FakeChat, use_model


def main():
    os.environ["AUTHOR_AGENT_SUMMARY_KEEP_MESSAGES"] = "2"
    created = workspace.create("QA Context 500k", "500k compaction")
    slug = created["slug"]
    chat = workspace.ensure_chats(slug)["activeChat"]
    try:
        huge = "x" * 2_500_000  # approximately 625k tokens in the default counter
        workspace.save_chat_messages(slug, chat, [
            {"role": "user", "content": huge},
            {"role": "assistant", "content": "acknowledged"},
        ])
        use_model(FakeChat(long_text=True))
        result = graph_agent.run_turn(slug, chat, "continue after compaction", lambda *_: None)
        messages = workspace.get_chat(slug, chat)["messages"]
        text = "\n".join(str(item.get("content") or "") for item in messages)
        print(f"  messages={len(messages)} chars={len(text)}")
        assert result.get("text"), result
        assert "summary" in text.lower(), "summarization did not run"
        assert len(text) < 1_000_000, "history was not compacted"
        print("500K CONTEXT TEST PASSED")
        return 0
    finally:
        os.environ.pop("AUTHOR_AGENT_SUMMARY_KEEP_MESSAGES", None)
        shutil.rmtree(workspace.ws_path(slug), ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
