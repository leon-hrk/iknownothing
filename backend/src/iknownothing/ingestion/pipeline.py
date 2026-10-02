"""The ingestion pipeline: conversion, topic extraction unit by unit, topic files, and topic list."""

import asyncio
import json
import re
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Any

from iknownothing.ai_client import AIClient, load_prompt
from iknownothing.course_store import CourseStore
from iknownothing.ingestion.conversion import FIGURE, blocks, convert, markdown_path, page_of
from iknownothing.ingestion.passages import source_content
from iknownothing.ingestion.render import render_solutions, render_topic
from iknownothing.ingestion.topics import (
    ASSIGNMENT_SCHEMA, GROUPING_SCHEMA, OTHER, SOLUTIONS_SCHEMA, UNIT_SCHEMA, Topic, apply_grouping, apply_unit,
    priority, range_numbers, sorted_by_priority, validate_grouping, validate_solutions, validate_unit,
)
from iknownothing.ocr_client import OCRClient

RESULT = "ingestion/topics.json"
SOLUTIONS = "solutions.md"
MAX_ATTEMPTS = 3
PARALLEL = 6


class IngestionError(Exception):
    pass


Report = Callable[[str], None]


def unit(file: str) -> tuple:
    """Files with the same digits in their name form one unit (an exam or exercise sheet with its solutions)."""
    name = PurePosixPath(file).name
    digits = "".join(re.findall(r"\d", name))
    return (0, int(digits)) if digits else (1, name)


def by_unit(files: list[str]) -> list[str]:
    return sorted(files, key=lambda f: (unit(f), f))


def title(file: str) -> str:
    """The document title of a source PDF: the path of its conversion below `sources/`."""
    return markdown_path(file).removeprefix("sources/")


def unit_key(title: str) -> str:
    """The unit of a document title, with its document type: `exams/(0, 20211006)`."""
    return f"{title.split('/')[0]}/{unit(title)}"


def units(files: list[str]) -> list[list[str]]:
    """The files grouped by unit, in unit order."""
    out: dict[tuple, list[str]] = {}
    for f in by_unit(files):
        out.setdefault(unit(f), []).append(f)
    return list(out.values())


async def ingest(store: CourseStore, ai: AIClient, ocr: OCRClient, report: Report) -> None:
    if not store.exists("notes.md"):
        raise IngestionError("notes.md is missing")

    exams = units(store.sources("exams"))
    exercises = units(store.sources("exercises"))
    if not exams and not exercises:
        raise IngestionError("no past exams and no exercises")

    report("conversion")
    await convert(store, ocr, [f for u in exams + exercises for f in u])

    result = store.read_json(RESULT) if store.exists(RESULT) else {"language": None, "done": [], "topics": []}

    def todo(us: list[list[str]]) -> list[list[str]]:
        return [u for u in us if not {title(f) for f in u} <= set(result["done"])]

    def applied(files: list[str], reply: dict) -> dict:
        return {**result, "language": result["language"] or reply.get("language"),
                "done": [*result["done"], *(title(f) for f in files)],
                "topics": apply_unit(result["topics"], {"topics": [], **reply})}

    # the past exams define the topics, one after another; without past exams, the exercises do
    defining, assigned = (exams, exercises) if exams else (exercises, [])
    pending = todo(defining)
    for i, files in enumerate(pending, 1):
        report(f"topic extraction {i}/{len(pending)}: {', '.join(title(f) for f in files)}")
        result = applied(files, await _extract(store, ai, files, result["topics"]))
        store.write_json(RESULT, result)
    if not result["topics"]:
        raise IngestionError("topic extraction found no topics")

    pending = todo(assigned)
    if pending:
        report(f"task assignment: {len(pending)} exercise sheets")
        limit = asyncio.Semaphore(PARALLEL)

        async def assign(files: list[str]) -> dict:
            async with limit:
                return await _assign(store, ai, files, result["topics"])

        replies = await asyncio.gather(*(assign(u) for u in pending), return_exceptions=True)
        for files, reply in zip(pending, replies):
            if not isinstance(reply, BaseException):
                result = applied(files, reply)
        store.write_json(RESULT, result)
        for reply in replies:
            if isinstance(reply, BaseException):
                raise reply

    other = next((t for t in result["topics"] if t["slug"] == OTHER), None)
    if other and not result.get("grouped"):
        report(f"task grouping: {len(other['sources'])} tasks without a topic")
        reply = await _group(store, ai, other, result["topics"])
        result = {**result, "topics": apply_grouping(result["topics"], reply), "grouped": True}
        store.write_json(RESULT, result)

    report("topic files")
    exam_units = [unit_key(title(u[0])) for u in exams]
    all_units = [unit_key(title(u[0])) for u in exams + exercises]
    topics = []
    for t in result["topics"]:
        asked = {unit_key(r["file"]) for s in t["sources"] for r in s["blocks"]}
        topics.append({**t, "priority": priority(asked, t["raised_by_notes"], exam_units, all_units),
                       "exams": len(asked & set(exam_units))})
    topics = sorted_by_priority(topics)
    listed = [{"slug": t["slug"], "name": t["name"], "priority": t["priority"],
               "dir": f"topics/{t['slug']}", "sources": _sources(store, t)} for t in topics]
    for t, entry in zip(topics, listed):
        store.write_text(f"topics/{t['slug']}/topic.md",
                         render_topic({**t, "sources": entry["sources"]}, len(exam_units)))
    store.write_json("topics.json", listed)

    solved = set(result.get("solved", []))
    pending = [e for e in listed if e["slug"] not in solved and any(s["tier"] != "C" for s in e["sources"])]
    if pending:
        report(f"solutions: {len(pending)} topics")
        limit = asyncio.Semaphore(PARALLEL)

        async def solve(entry: dict) -> dict:
            async with limit:
                return await _solve(store, ai, entry, result["language"])

        replies = await asyncio.gather(*(solve(e) for e in pending), return_exceptions=True)
        for entry, reply in zip(pending, replies):
            if not isinstance(reply, BaseException):
                if reply["solutions"]:
                    store.write_text(f"{entry['dir']}/{SOLUTIONS}", render_solutions(reply["solutions"]))
                solved.add(entry["slug"])
        result = {**result, "solved": sorted(solved)}
        store.write_json(RESULT, result)
        for reply in replies:
            if isinstance(reply, BaseException):
                raise reply
    report(f"ready: {len(topics)} topics, language {result['language']}")


def _sources(store: CourseStore, topic: Topic) -> list[dict]:
    """The topic's sources as listed: each with its ID, and each block range with the pages it spans."""
    cache: dict[str, list[str]] = {}
    out = []
    for i, s in enumerate(topic["sources"], 1):
        ranges = []
        for r in s["blocks"]:
            bs = cache.setdefault(r["file"], blocks(store.read_text(f"sources/{r['file']}")))
            numbers = range_numbers(r["blocks"])
            first, last = page_of(bs, numbers[0]), page_of(bs, numbers[-1])
            ranges.append({**r, "pages": str(first) if first == last else f"{first}-{last}"})
        out.append({"id": f"{topic['slug']}/{i}", "task": s["task"], "tier": s["tier"], "fit": s["fit"],
                    "blocks": ranges})
    return out


def _topics_so_far(topics: list[Topic]) -> str:
    if not topics:
        return "(none yet)"
    return "\n\n".join(
        f'<topic slug="{t["slug"]}" name="{t["name"]}">\n{t["description"].strip()}\n'
        + "".join(f"- {s['task']} (Tier {s['tier']})\n" for s in t["sources"])
        + "</topic>"
        for t in topics
    )


async def _documents(store: CourseStore, files: list[str]) -> tuple[list[dict], dict[str, int]]:
    """A unit's conversions with numbered blocks, their figures replaced by `[figure]`, and their block counts."""
    block_counts = {}
    documents = []
    for f in files:
        bs = blocks(await asyncio.to_thread(store.read_text, markdown_path(f)))
        block_counts[title(f)] = len(bs)
        numbered = "\n\n".join(f"[{n}] {FIGURE.sub('[figure]', b)}" for n, b in enumerate(bs, 1))
        documents.append({"type": "text", "text": f'<document title="{title(f)}">\n{numbered}\n</document>'})
    return documents, block_counts


async def _assign(store: CourseStore, ai: AIClient, files: list[str], topics: list[Topic]) -> dict:
    """Assigns the tasks of one exercise unit to the topics."""
    documents, block_counts = await _documents(store, files)
    known = {t["slug"] for t in topics} | {OTHER}
    return await _request_valid(
        ai, "task_assignment", documents, f"<topics>\n{_topics_so_far(topics)}\n</topics>", ASSIGNMENT_SCHEMA,
        lambda r: validate_unit({"topics": [], **r}, known, block_counts),
    )


async def _group(store: CourseStore, ai: AIClient, other: Topic, topics: list[Topic]) -> dict:
    """Sends the tasks of `OTHER`, numbered, with their blocks, and the other topics."""
    converted: dict[str, list[str]] = {}
    tasks = []
    for i, s in enumerate(other["sources"], 1):
        passages = []
        for r in s["blocks"]:
            if r["file"] not in converted:
                converted[r["file"]] = blocks(await asyncio.to_thread(store.read_text, f"sources/{r['file']}"))
            text = "\n\n".join(FIGURE.sub("[figure]", converted[r["file"]][n - 1]) for n in range_numbers(r["blocks"]))
            passages.append(f'<passage file="{r["file"]}">\n{text}\n</passage>')
        tasks.append(f'<task index="{i}" label="{s["task"]}" tier="{s["tier"]}">\n' + "\n".join(passages) + "\n</task>")
    rest = [t for t in topics if t["slug"] != OTHER]
    documents = [{"type": "text", "text": "<tasks>\n" + "\n\n".join(tasks) + "\n</tasks>"}]
    known = {t["slug"] for t in rest}
    return await _request_valid(
        ai, "task_grouping", documents, f"<topics>\n{_topics_so_far(rest)}\n</topics>", GROUPING_SCHEMA,
        lambda r: validate_grouping(r, known, len(other["sources"])),
    )


async def _extract(store: CourseStore, ai: AIClient, files: list[str], topics: list[Topic]) -> dict:
    """Sends one unit's conversions, the notes, and the topics so far."""
    documents, block_counts = await _documents(store, files)
    data = (
        f"<notes>\n{store.read_text('notes.md')}\n</notes>\n\n"
        f"<topics>\n{_topics_so_far(topics)}\n</topics>"
    )
    known = {t["slug"] for t in topics}
    return await _request_valid(
        ai, "topic_extraction", documents, data, UNIT_SCHEMA,
        lambda r: validate_unit(r, known, block_counts),
    )


async def _solve(store: CourseStore, ai: AIClient, entry: dict, language: str) -> dict:
    """Sends a topic's sources, figures included, and its topic.md; receives solutions for the tasks without one."""
    labels = {s["task"] for s in entry["sources"] if s["tier"] != "C"}
    data = f"<language>{language}</language>\n\n<topic>\n{store.read_text(f'{entry['dir']}/topic.md')}\n</topic>"
    return await _request_valid(
        ai, "solution_writing", await source_content(store, entry), data, SOLUTIONS_SCHEMA,
        lambda r: validate_solutions(r, labels),
    )


async def _request_valid(
    ai: AIClient, kind: str, documents: list[dict], data: str, schema: dict,
    validate: Callable[[Any], list[str]],
) -> Any:
    """Sends the request and repeats it with the errors while the reply violates `validate`."""
    messages: list[dict] = [{"role": "user", "content": [*documents, {"type": "text", "text": data}]}]
    for _ in range(MAX_ATTEMPTS):
        reply = await ai.request_json(kind, messages, schema)
        errors = validate(reply)
        if not errors:
            return reply
        messages += [
            {"role": "assistant", "content": json.dumps(reply, ensure_ascii=False)},
            {"role": "user", "content": load_prompt("rejected").format(errors="\n".join(f"- {e}" for e in errors))},
        ]
    raise IngestionError(f"{kind}: reply still invalid after {MAX_ATTEMPTS} attempts: {errors}")
