"""Course-level and topic-level chats: context assembly, chat tools, and the reply loop."""

import asyncio
import base64
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Any

from iknownothing.ai_client import AIClient
from iknownothing.course_store import CourseStore
from iknownothing.ingestion.pipeline import by_unit
from iknownothing.ingestion.topics import page_numbers
from iknownothing.tutor.cheatsheet import CheatsheetError, set_entry

MAX_TOOL_ROUNDS = 8

TOPIC_TOOLS = [
    {
        "name": "update_cheatsheet",
        "description": (
            "Adds, changes, or removes one entry of the student's cheatsheet. Entries are grouped in "
            "sections, one per topic. An entry is a heading and a short Markdown body; an existing "
            "heading in the section is replaced. An empty body removes the entry."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "section": {"type": "string", "description": "The topic name the entry belongs to."},
                "heading": {"type": "string", "description": "The term, formula, or strategy."},
                "body": {"type": "string", "description": "Markdown, without headings of level 1 to 3."},
            },
            "required": ["section", "heading", "body"],
            "additionalProperties": False,
        },
    },
    {
        "name": "pose_task",
        "description": (
            "Marks the task you pose in this reply with its gradability tier. Call it right before "
            "stating the task."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The source task it is taken from or modelled on, as the topic names it.",
                },
                "tier": {"type": "string", "enum": ["A", "B"]},
            },
            "required": ["task", "tier"],
            "additionalProperties": False,
        },
    },
]
COURSE_TOOLS = TOPIC_TOOLS[:1]

_POSED = {
    "A": "Posed as Tier A. Grade the student's answer.",
    "B": (
        "Posed as Tier B. Do not grade the student's attempt. When they ask for it, show the reference "
        "solution; the student then rates themselves (got it / struggled / no idea)."
    ),
}


class TutorError(Exception):
    pass


def topic_entry(store: CourseStore, slug: str) -> dict:
    for t in store.read_json("topics.json"):
        if t["slug"] == slug:
            return t
    raise TutorError(f"no such topic: {slug!r}")


def _ranges(pages: list[int]) -> str:
    out: list[str] = []
    start = prev = pages[0]
    for n in [*pages[1:], None]:
        if n is not None and n == prev + 1:
            prev = n
            continue
        out.append(str(start) if start == prev else f"{start}-{prev}")
        if n is not None:
            start = prev = n
    return ", ".join(out)


async def source_documents(store: CourseStore, topic: dict) -> list[dict]:
    """The topic's source pages, one document per file, each page once."""
    pages: defaultdict[str, set[int]] = defaultdict(set)
    for source in topic["sources"]:
        for r in source["pages"]:
            pages[r["file"]].update(page_numbers(r["pages"]))
    files = [*by_unit([f for f in pages if f.startswith("exams/")]),
             *by_unit([f for f in pages if not f.startswith("exams/")])]
    documents = []
    for f in files:
        numbers = sorted(pages[f])
        data = await asyncio.to_thread(store.pages_pdf, f"sources/{f}", numbers)
        documents.append({
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf",
                       "data": base64.standard_b64encode(data).decode("ascii")},
            "title": f"{f}, pages {_ranges(numbers)}",
        })
    return documents


def _optional(store: CourseStore, rel: str, missing: str = "(empty)") -> str:
    return store.read_text(rel) if store.exists(rel) else missing


async def topic_context(store: CourseStore, slug: str, language: str) -> list[dict]:
    """The context of a topic-level chat: source pages first, marked for caching, then the course files."""
    topic = topic_entry(store, slug)
    documents = await source_documents(store, topic)
    documents[-1]["cache_control"] = {"type": "ephemeral"}
    text = (
        f"<language>{language}</language>\n\n"
        f"<topic>\n{store.read_text(f'{topic['dir']}/topic.md')}\n</topic>\n\n"
        f"<notes>\n{store.read_text('notes.md')}\n</notes>\n\n"
        f"<cheatsheet>\n{_optional(store, 'cheatsheet.md')}\n</cheatsheet>\n\n"
        f"<progress>\n{_optional(store, f'{topic['dir']}/progress.md')}\n</progress>"
    )
    return [*documents, {"type": "text", "text": text}]


def course_context(store: CourseStore, language: str) -> list[dict]:
    """The context of a course-level chat: every topic with its priority, tasks, and progress, then the course files."""
    topics = []
    for t in store.read_json("topics.json"):
        tasks = "\n".join(f"- {s['task']} (Tier {s['tier']})" for s in t["sources"])
        progress = _optional(store, f"{t['dir']}/progress.md", "(no session yet)")
        topics.append(
            f'<topic name="{t["name"]}" priority="{t["priority"]}">\n'
            f"<tasks>\n{tasks}\n</tasks>\n<progress>\n{progress}\n</progress>\n</topic>"
        )
    text = (
        f"<language>{language}</language>\n\n"
        f"<topics>\n{chr(10).join(topics)}\n</topics>\n\n"
        f"<notes>\n{store.read_text('notes.md')}\n</notes>\n\n"
        f"<cheatsheet>\n{_optional(store, 'cheatsheet.md')}\n</cheatsheet>"
    )
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def _with_context(ctx: list[dict], transcript: list[dict]) -> list[dict]:
    first = transcript[0]["content"]
    if isinstance(first, str):
        first = [{"type": "text", "text": first}]
    return [{"role": "user", "content": [*ctx, *first]}, *transcript[1:]]


async def _execute(store: CourseStore, block: Any) -> tuple[dict, tuple[str, Any]]:
    """Runs one tool call; returns its tool result and the event it emits."""
    args = block.input
    if block.name == "update_cheatsheet":
        try:
            await store.update_text(
                "cheatsheet.md", lambda text: set_entry(text, args["section"], args["heading"], args["body"]))
        except CheatsheetError as e:
            return {"type": "tool_result", "tool_use_id": block.id, "is_error": True, "content": str(e)}, None
        return ({"type": "tool_result", "tool_use_id": block.id, "content": "Cheatsheet updated."},
                ("cheatsheet", args))
    if block.name == "pose_task":
        return ({"type": "tool_result", "tool_use_id": block.id, "content": _POSED[args["tier"]]},
                ("task", args))
    return {"type": "tool_result", "tool_use_id": block.id, "is_error": True,
            "content": f"unknown tool {block.name!r}"}, None


async def reply(
    store: CourseStore, ai: AIClient, slug: str | None, language: str, transcript: list[dict],
) -> AsyncIterator[tuple[str, Any]]:
    """Streams the tutor's reply to a transcript that ends with the student's message.

    `slug` names the topic of a topic-level chat; `None` makes it a course-level chat.

    Yields `("text", chunk)`, `("cheatsheet", entry)`, and `("task", task)`, and appends the reply,
    tool calls and results included, to `transcript`. On failure the transcript is left as it was.
    """
    start = len(transcript)
    if slug is None:
        request_type, tools, ctx = "planning", COURSE_TOOLS, course_context(store, language)
    else:
        request_type, tools, ctx = "tutoring", TOPIC_TOOLS, await topic_context(store, slug, language)
    try:
        for _ in range(MAX_TOOL_ROUNDS):
            msg = None
            async for kind, value in ai.stream_chat(request_type, _with_context(ctx, transcript), tools):
                if kind == "text":
                    yield "text", value
                else:
                    msg = value
            if msg.stop_reason == "refusal":
                raise TutorError("the model declined to answer")
            if msg.stop_reason == "max_tokens":
                raise TutorError("the reply exceeded max_tokens")
            transcript.append({"role": "assistant", "content": [b.to_dict(exclude_none=True) for b in msg.content]})
            if msg.stop_reason != "tool_use":
                return
            results = []
            for block in (b for b in msg.content if b.type == "tool_use"):
                result, event = await _execute(store, block)
                results.append(result)
                if event:
                    yield event
            transcript.append({"role": "user", "content": results})
        raise TutorError(f"the reply exceeded {MAX_TOOL_ROUNDS} tool rounds")
    except BaseException:
        del transcript[start:]
        raise
