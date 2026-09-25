"""Topics as data during ingestion: the reply schema of topic extraction and its checks."""

import re
from typing import Any

PRIORITIES = ("high", "medium", "low")
TIERS = ("A", "B", "C")

SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
PAGE_RANGE = re.compile(r"^(\d+)(?:-(\d+))?$")

Topic = dict[str, Any]

_PAGE_RANGE_SCHEMA = {
    "type": "object",
    "properties": {"file": {"type": "string"}, "pages": {"type": "string"}},
    "required": ["file", "pages"],
    "additionalProperties": False,
}

_SOURCE_SCHEMA = {
    "type": "object",
    "properties": {
        "task": {"type": "string"},
        "tier": {"type": "string", "enum": list(TIERS)},
        "pages": {"type": "array", "items": _PAGE_RANGE_SCHEMA},
    },
    "required": ["task", "tier", "pages"],
    "additionalProperties": False,
}

_TOPIC_SCHEMA = {
    "type": "object",
    "properties": {
        "slug": {"type": "string"},
        "name": {"type": "string"},
        "priority": {"type": "string", "enum": list(PRIORITIES)},
        "description": {"type": "string"},
        "sources": {"type": "array", "items": _SOURCE_SCHEMA},
    },
    "required": ["slug", "name", "priority", "description", "sources"],
    "additionalProperties": False,
}

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "language": {"type": "string"},
        "topics": {"type": "array", "items": _TOPIC_SCHEMA},
    },
    "required": ["language", "topics"],
    "additionalProperties": False,
}


def page_numbers(pages: str) -> list[int]:
    """`"3"` or `"3-5"` as a list of 1-based page numbers."""
    m = PAGE_RANGE.match(pages.replace(" ", ""))
    if not m:
        raise ValueError(pages)
    first = int(m[1])
    last = int(m[2] or m[1])
    return list(range(first, last + 1))


def validate_extraction(reply: dict, page_counts: dict[str, int]) -> list[str]:
    """`page_counts` maps every file sent, by its document title, to its number of pages."""
    errors = []
    if not reply["topics"]:
        errors.append("no topics")
    seen = set()
    for t in reply["topics"]:
        slug = t["slug"]
        if not SLUG.match(slug):
            errors.append(f"invalid slug {slug!r}: use lowercase letters, digits, and single hyphens")
        if slug in seen:
            errors.append(f"slug {slug!r} appears more than once")
        seen.add(slug)
        for s in t["sources"]:
            if not s["pages"]:
                errors.append(f"{slug}: source {s['task']!r} has no pages")
            for r in s["pages"]:
                where = f"{slug}: source {s['task']!r}"
                if r["file"] not in page_counts:
                    errors.append(f"{where}: unknown file {r['file']!r}; use a document title exactly")
                    continue
                try:
                    numbers = page_numbers(r["pages"])
                except ValueError:
                    errors.append(f"{where}: invalid pages {r['pages']!r}; write `3` or `3-5`")
                    continue
                count = page_counts[r["file"]]
                if not numbers or numbers[0] < 1 or numbers[-1] > count:
                    errors.append(f"{where}: pages {r['pages']!r} outside {r['file']}, which has {count} pages")
    return errors


def sorted_by_priority(topics: list[Topic]) -> list[Topic]:
    return sorted(topics, key=lambda t: PRIORITIES.index(t["priority"]))
