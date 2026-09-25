"""The ingestion pipeline: topic extraction, topic files, and topic list."""

import asyncio
import base64
import json
import re
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Any

from iknownothing.ai_client import AIClient, load_prompt
from iknownothing.course_store import CourseStore
from iknownothing.ingestion.render import render_topic
from iknownothing.ingestion.topics import EXTRACTION_SCHEMA, sorted_by_priority, validate_extraction

RESULT = "ingestion/topics.json"
MAX_ATTEMPTS = 3


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
    """The document title of a source: its path below `sources/`."""
    return file.removeprefix("sources/")


async def ingest(store: CourseStore, ai: AIClient, report: Report) -> None:
    if not store.exists("notes.md"):
        raise IngestionError("notes.md is missing")

    exams = by_unit(store.sources("exams"))
    exercises = by_unit(store.sources("exercises"))
    if not exams and not exercises:
        raise IngestionError("no past exams and no exercises")

    if not store.exists(RESULT):
        report("topic extraction")
        reply = await _extract(store, ai, exams + exercises, exam_count=len({unit(f) for f in exams}))
        store.write_json(RESULT, reply)
    result = store.read_json(RESULT)
    topics = sorted_by_priority(result["topics"])

    report("topic files")
    for t in topics:
        store.write_text(f"topics/{t['slug']}/topic.md", render_topic(t))
    store.write_json(
        "topics.json",
        [{"slug": t["slug"], "name": t["name"], "priority": t["priority"],
          "dir": f"topics/{t['slug']}", "sources": t["sources"]} for t in topics],
    )
    report(f"ready: {len(topics)} topics, language {result['language']}")


async def _extract(store: CourseStore, ai: AIClient, files: list[str], exam_count: int) -> dict:
    page_counts = {}
    documents = []
    for f in files:
        data = await asyncio.to_thread(store.read_bytes, f)
        page_counts[title(f)] = await asyncio.to_thread(store.page_count, f)
        documents.append({
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf",
                       "data": base64.standard_b64encode(data).decode("ascii")},
            "title": title(f),
        })
    data = (
        f"<notes>\n{store.read_text('notes.md')}\n</notes>\n\n"
        f"<past_exams>{exam_count}</past_exams>"
    )
    return await _request_valid(
        ai, "topic_extraction", documents, data, EXTRACTION_SCHEMA,
        lambda r: validate_extraction(r, page_counts),
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
