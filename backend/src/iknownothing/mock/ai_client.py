"""A stand-in for the AI Client that answers chats with sample replies, for testing the UI without the Anthropic API.

A chat message `/<name>` is answered with `replies/<name>.md`; any other message with the list of names.
"""

import asyncio
import re
from collections.abc import AsyncIterator
from importlib import resources
from types import SimpleNamespace
from typing import Any

from anthropic.types import TextBlock

from iknownothing.ai_client import AIError
from iknownothing.config import Settings

THINKING_SECONDS = 2.0
CHUNK_SECONDS = 0.005


def replies() -> dict[str, str]:
    """The sample replies by name."""
    files = resources.files("iknownothing.mock.replies").iterdir()
    return {f.name.removesuffix(".md"): f.read_text(encoding="utf-8") for f in files if f.name.endswith(".md")}


def reply_to(message: str) -> str:
    samples = replies()
    name = message.strip().removeprefix("/")
    if message.strip().startswith("/") and name in samples:
        return samples[name]
    commands = "\n".join(f"- `/{n}`" for n in sorted(samples))
    return f"This is the **mock AI client**. Send one of these commands:\n\n{commands}\n"


def _last_text(messages: list[dict]) -> str:
    content = messages[-1]["content"]
    if isinstance(content, str):
        return content
    return next((b["text"] for b in reversed(content) if b.get("type") == "text"), "")


class MockAIClient:
    """Answers every chat message by `reply_to`, streamed in small chunks after a pause; other requests fail."""

    def __init__(self, settings: Settings, user: str, course: str):
        pass

    async def close(self) -> None:
        pass

    async def request_json(self, request_type: str, messages: list[dict], schema: dict) -> Any:
        raise AIError(f"{request_type}: not available with the mock AI client")

    async def request_text(self, request_type: str, messages: list[dict]) -> str:
        raise AIError(f"{request_type}: not available with the mock AI client")

    async def stream_chat(
        self, request_type: str, messages: list[dict], tools: list[dict],
    ) -> AsyncIterator[tuple[str, Any]]:
        text = reply_to(_last_text(messages))
        await asyncio.sleep(THINKING_SECONDS)
        for chunk in re.findall(r"\S+\s*", text):
            await asyncio.sleep(CHUNK_SECONDS)
            yield "text", chunk
        yield "message", SimpleNamespace(stop_reason="end_turn", content=[TextBlock(type="text", text=text)])

    def tokens(self) -> dict[str, float]:
        return {"input": 0, "cached": 0, "output": 0, "eur": 0.0}
