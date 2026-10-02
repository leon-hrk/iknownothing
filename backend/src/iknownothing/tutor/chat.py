"""Course-level and topic-level chats: context assembly, chat tools, and the reply loop."""

import asyncio
import base64
import json
from collections.abc import AsyncIterator
from pathlib import PurePosixPath
from typing import Any

from iknownothing.ai_client import AIClient
from iknownothing.course_store import CourseStore
from iknownothing.ingestion.conversion import FIGURE, blocks
from iknownothing.ingestion.topics import range_numbers
from iknownothing.tutor.cheatsheet import CheatsheetError, set_entry

MAX_TOOL_ROUNDS = 8

CHEATSHEET_TOOL = {
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
}
POSE_TASK_TOOL = {
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
}
COURSE_TOOLS = [CHEATSHEET_TOOL]
INTRODUCTION = "introduction"


COMPLETE_STEP_TOOL = {
    "name": "complete_step",
    "description": (
        "Ends a step of the session: the introduction once the student has understood it, or a task once "
        "it is graded or rated. The step is recorded in the topic's progress, and the chat continues "
        "from the updated progress without the messages before."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "step": {
                "type": "string",
                "description": (
                    f'"{INTRODUCTION}", or the source task the task was taken from or modelled on, as the '
                    "topic names it."
                ),
            },
            "note": {
                "type": "string",
                "description": "One short sentence on how it went, or empty when there is nothing to note.",
            },
        },
        "required": ["step", "note"],
        "additionalProperties": False,
    },
}
TOPIC_TOOLS = [CHEATSHEET_TOOL, POSE_TASK_TOOL, COMPLETE_STEP_TOOL]


STEP_RECORDED = "Step recorded in the progress. Continue with the next step."
PROGRESS = "progress.json"
CONTINUE = "The previous steps of this session are recorded in the progress. Continue with the next step."

POSED = {
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


def _image(rel: str, data: bytes) -> dict:
    media_type = "image/png" if rel.endswith(".png") else "image/jpeg"
    return {"type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": base64.standard_b64encode(data).decode("ascii")}}


async def source_content(store: CourseStore, topic: dict) -> list[dict]:
    """Every source of the topic with its blocks as text and the figures in them as images, where they stand, each
    after its Markdown image line with the path from the course directory. Each passage names its PDF and pages."""
    converted: dict[str, list[str]] = {}
    content: list[dict] = []
    text: list[str] = []

    def flush() -> None:
        if text:
            content.append({"type": "text", "text": "".join(text)})
            text.clear()

    for s in topic["sources"]:
        text.append(f'<source id="{s["id"]}" task="{s["task"]}" tier="{s["tier"]}" fit="{s["fit"]}">\n')
        for r in s["blocks"]:
            rel = f"sources/{r['file']}"
            if rel not in converted:
                converted[rel] = blocks(await asyncio.to_thread(store.read_text, rel))
            pdf = f"sources/{r['file'].removesuffix('.md')}.pdf"
            text.append(f'<passage file="{r["file"]}" blocks="{r["blocks"]}" pdf="{pdf}" pages="{r["pages"]}">\n')
            for n in range_numbers(r["blocks"]):
                block, pos = converted[rel][n - 1], 0
                for m in FIGURE.finditer(block):
                    figure = str(PurePosixPath(rel).parent / m[1])
                    text.append(f"{block[pos:m.start()]}![]({figure})\n")
                    flush()
                    content.append(_image(figure, await asyncio.to_thread(store.read_bytes, figure)))
                    pos = m.end()
                text.append(f"{block[pos:]}\n\n")
            text.append("</passage>\n")
        text.append("</source>\n\n")
    flush()
    return content


def _optional(store: CourseStore, rel: str, missing: str = "(empty)") -> str:
    return store.read_text(rel) if store.exists(rel) else missing


def _task_labels(topic: dict) -> list[str]:
    return list(dict.fromkeys(s["task"] for s in topic["sources"] if s["tier"] != "C"))


def _progress(text: str, topic: dict) -> dict:
    """A topic's progress from its file's text: whether the introduction was given, and every task with whether it
    is done and a note on how it went."""
    progress = json.loads(text) if text else {}
    tasks = progress.get("tasks", {})
    return {"introduction": progress.get("introduction", False),
            "tasks": {label: tasks.get(label, {"done": False}) for label in _task_labels(topic)}}


def progress(store: CourseStore, topic: dict) -> dict:
    rel = f"{topic['dir']}/{PROGRESS}"
    return _progress(store.read_text(rel) if store.exists(rel) else "", topic)


async def record_step(store: CourseStore, topic: dict, step: str, note: str) -> None:
    """Marks the introduction as given, or a task as done with its note."""
    def change(text: str) -> str:
        p = _progress(text, topic)
        if step == INTRODUCTION:
            p["introduction"] = True
        else:
            p["tasks"][step] = {"done": True, **({"note": note} if note else {})}
        return json.dumps(p, ensure_ascii=False, indent=2) + "\n"
    await store.update_text(f"{topic['dir']}/{PROGRESS}", change)


async def topic_context(store: CourseStore, slug: str, language: str) -> list[dict]:
    """The context of a topic-level chat: its sources first, marked for caching, then the course files."""
    topic = topic_entry(store, slug)
    sources = await source_content(store, topic)
    if sources:
        sources[-1]["cache_control"] = {"type": "ephemeral"}
    text = (
        f"<language>{language}</language>\n\n"
        f"<topic>\n{store.read_text(f'{topic['dir']}/topic.md')}\n</topic>\n\n"
        f"<notes>\n{store.read_text('notes.md')}\n</notes>\n\n"
        f"<cheatsheet>\n{_optional(store, 'cheatsheet.md')}\n</cheatsheet>\n\n"
        f"<progress>\n{json.dumps(progress(store, topic), ensure_ascii=False, indent=2)}\n</progress>"
    )
    return [*sources, {"type": "text", "text": text}]


def course_context(store: CourseStore, language: str) -> list[dict]:
    """The context of a course-level chat: every topic with its priority, tasks, and progress, then the course files."""
    topics = []
    for t in store.read_json("topics.json"):
        tasks = "\n".join(f"- {s['task']} (Tier {s['tier']})" for s in t["sources"])
        p = progress(store, t)
        topics.append(
            f'<topic name="{t["name"]}" priority="{t["priority"]}">\n'
            f"<tasks>\n{tasks}\n</tasks>\n<progress>\n{json.dumps(p, ensure_ascii=False)}\n</progress>\n</topic>"
        )
    text = (
        f"<language>{language}</language>\n\n"
        f"<topics>\n{chr(10).join(topics)}\n</topics>\n\n"
        f"<notes>\n{store.read_text('notes.md')}\n</notes>\n\n"
        f"<cheatsheet>\n{_optional(store, 'cheatsheet.md')}\n</cheatsheet>"
    )
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def step_start(transcript: list[dict]) -> int:
    """Where the current step begins: after the result of the last successful `complete_step` call, or 0."""
    for i in range(len(transcript) - 2, -1, -1):
        m = transcript[i]
        if m["role"] != "assistant" or not isinstance(m["content"], list):
            continue
        calls = {b["id"] for b in m["content"] if b["type"] == "tool_use" and b["name"] == "complete_step"}
        if calls and any(r["tool_use_id"] in calls and not r.get("is_error") for r in transcript[i + 1]["content"]):
            return i + 2
    return 0


def _with_context(ctx: list[dict], transcript: list[dict]) -> list[dict]:
    """The messages of the current step, the context first."""
    start = step_start(transcript)
    if start:
        return [{"role": "user", "content": [*ctx, {"type": "text", "text": CONTINUE}]}, *transcript[start:]]
    first = transcript[0]["content"]
    if isinstance(first, str):
        first = [{"type": "text", "text": first}]
    return [{"role": "user", "content": [*ctx, *first]}, *transcript[1:]]


async def _execute(store: CourseStore, topic: dict | None, block: Any) -> tuple[dict, tuple[str, Any]]:
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
        return ({"type": "tool_result", "tool_use_id": block.id, "content": POSED[args["tier"]]},
                ("task", args))
    if block.name == "complete_step":
        steps = [INTRODUCTION, *_task_labels(topic)]
        if args["step"] not in steps:
            return {"type": "tool_result", "tool_use_id": block.id, "is_error": True,
                    "content": f"No such step. Steps: {', '.join(steps)}"}, None
        await record_step(store, topic, args["step"], args["note"])
        return {"type": "tool_result", "tool_use_id": block.id, "content": STEP_RECORDED}, ("step", args)
    return {"type": "tool_result", "tool_use_id": block.id, "is_error": True,
            "content": f"unknown tool {block.name!r}"}, None


async def reply(
    store: CourseStore, ai: AIClient, slug: str | None, language: str, transcript: list[dict],
) -> AsyncIterator[tuple[str, Any]]:
    """Streams the tutor's reply to a transcript that ends with the student's message.

    `slug` names the topic of a topic-level chat; `None` makes it a course-level chat.
    A completed step is recorded in the topic's progress; the reply then continues from the updated
    context without the messages before.

    Yields `("thinking", chunk)`, `("text", chunk)`, `("tool", name)` when a tool call starts,
    `("cheatsheet", entry)`, `("task", task)`, and `("step", step)`, and appends the reply,
    tool calls and results included, to `transcript`. On failure the transcript is left as it was.
    """
    start = len(transcript)
    if slug is None:
        topic, request_type, tools, ctx = None, "planning", COURSE_TOOLS, course_context(store, language)
    else:
        topic = topic_entry(store, slug)
        request_type, tools, ctx = "tutoring", TOPIC_TOOLS, await topic_context(store, slug, language)
    try:
        for _ in range(MAX_TOOL_ROUNDS):
            msg = None
            async for kind, value in ai.stream_chat(request_type, _with_context(ctx, transcript), tools):
                if kind == "message":
                    msg = value
                else:
                    yield kind, value
            if msg.stop_reason == "refusal":
                raise TutorError("the model declined to answer")
            if msg.stop_reason == "max_tokens":
                raise TutorError("the reply exceeded max_tokens")
            transcript.append({"role": "assistant", "content": [b.to_dict(exclude_none=True) for b in msg.content]})
            if msg.stop_reason != "tool_use":
                return
            results, step = [], False
            for block in (b for b in msg.content if b.type == "tool_use"):
                result, event = await _execute(store, topic, block)
                results.append(result)
                if event:
                    step |= event[0] == "step"
                    yield event
            if step:
                ctx = await topic_context(store, slug, language)
            transcript.append({"role": "user", "content": results})
        raise TutorError(f"the reply exceeded {MAX_TOOL_ROUNDS} tool rounds")
    except BaseException:
        del transcript[start:]
        raise
