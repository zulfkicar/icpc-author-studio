"""Opt-in real-provider long-context probe.

Run only with AUTHOR_AGENT_LONG_CONTEXT_PROBE=1 and a configured key. This
costs provider tokens and is intentionally excluded from CI.
"""
import asyncio
import os
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import config
import graph_agent


async def main() -> int:
    if os.environ.get("AUTHOR_AGENT_LONG_CONTEXT_PROBE") != "1":
        print("SKIP long-context probe: set AUTHOR_AGENT_LONG_CONTEXT_PROBE=1")
        return 0
    cfg = config.load()
    model = graph_agent._model(cfg).bind(max_tokens=64)
    huge = "x" * 4_000_000
    try:
        response = await model.ainvoke([
            {"role": "user", "content": huge + "\n\nIgnore all of that padding. Reply with exactly: long-ok."}
        ])
        print("text:", str(response.content)[:100])
        print("usage:", getattr(response, "usage_metadata", None))
        return 0
    finally:
        try:
            await model.async_client.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
