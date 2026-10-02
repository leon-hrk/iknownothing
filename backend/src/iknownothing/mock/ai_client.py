"""A stand-in for the AI Client that answers chats with sample replies, for testing the UI without the Anthropic API.

A chat message `/<name>` is answered with `replies/<name>.md`, `/tools` with a reply that poses a task in a tool
call, and any other message with the list of commands. Each reply starts with a thinking summary. Every chat opens
as the sample chat, which sends each command once. `data/` holds the sample data: the user `mock` with a sample
course.
"""

import asyncio
import re
from collections.abc import AsyncIterator
from importlib import resources
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from anthropic.types import TextBlock, ThinkingBlock, ToolUseBlock

from iknownothing.ai_client import AIError
from iknownothing.config import Settings
from iknownothing.tutor.chat import POSED

SAMPLE_DATA = Path(__file__).parent / "data"

THINKING_SECONDS = 2.0
CHUNK_SECONDS = 0.005

TOOLS = "tools"
TASK = {"task": "Sample exam, task 2a", "tier": "A"}

_BLOCKS = {"thinking": ThinkingBlock, "text": TextBlock, "tool_use": ToolUseBlock}


def replies() -> dict[str, str]:
    """The sample replies by name."""
    files = resources.files("iknownothing.mock.replies").iterdir()
    return {f.name.removesuffix(".md"): f.read_text(encoding="utf-8") for f in files if f.name.endswith(".md")}


def commands() -> list[str]:
    return sorted([*replies(), TOOLS])


def _thinking(text: str) -> dict:
    return {"type": "thinking", "thinking": text, "signature": "mock"}


def _text(text: str) -> dict:
    return {"type": "text", "text": text}


def rounds(message: str) -> list[list[dict]]:
    """The reply to a message: the content of each assistant message, all but the last ending in a tool call."""
    samples = replies()
    name = message.strip().removeprefix("/")
    if not message.strip().startswith("/") or name not in commands():
        listed = "\n".join(f"- `/{n}`" for n in commands())
        return [[_thinking("The message is no command I know, so I list the commands the mock AI client answers."),
                 _text(f"This is the **mock AI client**. Send one of these commands:\n\n{listed}\n")]]
    if name == TOOLS:
        return [
            [_thinking("**Choosing a task**\n\nThe student wants to see a tool call. I pick a task from the sample "
                       "exam and mark it with its tier before I state it."),
             _text("Here is a task from the sample exam.\n\n"),
             {"type": "tool_use", "id": "mock-pose-task", "name": "pose_task", "input": TASK}],
            [_thinking("**Stating the task**\n\nThe task is marked as Tier A, so I will grade the answer. "
                       "Now I state it and wait."),
             _text("**Sample exam, task 2a.** The figure shows a finite automaton over the alphabet "
                   "\\(\\{0, 1\\}\\).\n\n![](sources/exams/sample/p1-img-0.png)\n\n"
                   "Which words of length two does it accept?\n")],
        ]
    return [[_thinking(f"**Answering `/{name}`**\n\nThe student sent `/{name}`. As the mock AI client, I answer "
                       "with the sample reply of that name, streamed in small chunks."),
             _text(samples[name])]]


def sample_chat() -> dict:
    """The chat every chat opens as: each command with its reply, and no usage."""
    transcript: list[dict] = []
    for name in commands():
        transcript.append({"role": "user", "content": f"/{name}"})
        for content in rounds(f"/{name}"):
            transcript.append({"role": "assistant", "content": content})
            calls = [b for b in content if b["type"] == "tool_use"]
            if calls:
                transcript.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": b["id"], "content": POSED[b["input"]["tier"]]}
                    for b in calls]})
    return {"transcript": transcript, "usage": {"input": 0, "cached": 0, "output": 0, "eur": 0.0}}


def _message_and_round(messages: list[dict]) -> tuple[str, int]:
    """The student's last message, and how many rounds of the reply to it are done."""
    done = 0
    for m in reversed(messages):
        if m["role"] != "user":
            continue
        content = m["content"]
        if isinstance(content, str):
            return content, done
        texts = [b["text"] for b in content if b.get("type") == "text"]
        if texts:
            return texts[-1], done
        done += 1
    return "", done


class MockAIClient:
    """Answers every chat message by `rounds`, one round per request, streamed in small chunks; other requests
    fail."""

    def __init__(self, settings: Settings, user: str, course: str):
        pass

    async def close(self) -> None:
        pass

    async def request_json(self, request_type: str, messages: list[dict], schema: dict) -> Any:
        raise AIError(f"{request_type}: not available with the mock AI client")

    async def stream_chat(
        self, request_type: str, messages: list[dict], tools: list[dict],
    ) -> AsyncIterator[tuple[str, Any]]:
        message, done = _message_and_round(messages)
        content = rounds(message)[done]
        for block in content:
            if block["type"] == "thinking":
                chunks = re.findall(r"\S+\s*", block["thinking"])
                for chunk in chunks:
                    await asyncio.sleep(THINKING_SECONDS / len(chunks))
                    yield "thinking", chunk
            elif block["type"] == "text":
                for chunk in re.findall(r"\S+\s*", block["text"]):
                    await asyncio.sleep(CHUNK_SECONDS)
                    yield "text", chunk
            else:
                yield "tool", block["name"]
                await asyncio.sleep(THINKING_SECONDS)
        stop_reason = "tool_use" if content[-1]["type"] == "tool_use" else "end_turn"
        yield "message", SimpleNamespace(
            stop_reason=stop_reason, content=[_BLOCKS[b["type"]].model_validate(b) for b in content])

    def tokens(self) -> dict[str, float]:
        return {"input": 0, "cached": 0, "output": 0, "eur": 0.0}
