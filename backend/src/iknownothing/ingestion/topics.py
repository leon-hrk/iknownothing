"""Topics as data during ingestion: the reply schema of a unit's extraction, its checks, applying it, and priority."""

import re
from typing import Any

PRIORITIES = ("high", "medium", "low")
TIERS = ("A", "B", "C")

SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
RANGE = re.compile(r"^(\d+)(?:-(\d+))?$")

Topic = dict[str, Any]

OTHER = "other-tasks"
OTHER_TOPIC = {"slug": OTHER, "name": "Other tasks",
               "description": "Exercise tasks that fit none of the topics of the past exams.", "raised_by_notes": False}

_BLOCK_RANGE_SCHEMA = {
    "type": "object",
    "properties": {"file": {"type": "string"}, "blocks": {"type": "string"}},
    "required": ["file", "blocks"],
    "additionalProperties": False,
}

_TOPIC_SCHEMA = {
    "type": "object",
    "properties": {
        "slug": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "raised_by_notes": {"type": "boolean"},
    },
    "required": ["slug", "name", "description", "raised_by_notes"],
    "additionalProperties": False,
}

_SOURCE_SCHEMA = {
    "type": "object",
    "properties": {
        "topic": {"type": "string"},
        "task": {"type": "string"},
        "tier": {"type": "string", "enum": list(TIERS)},
        "blocks": {"type": "array", "items": _BLOCK_RANGE_SCHEMA},
    },
    "required": ["topic", "task", "tier", "blocks"],
    "additionalProperties": False,
}

UNIT_SCHEMA = {
    "type": "object",
    "properties": {
        "language": {"type": "string"},
        "topics": {"type": "array", "items": _TOPIC_SCHEMA},
        "sources": {"type": "array", "items": _SOURCE_SCHEMA},
    },
    "required": ["language", "topics", "sources"],
    "additionalProperties": False,
}

FITS = ("clear", "loose")

_ASSIGNED_SOURCE_SCHEMA = {
    **_SOURCE_SCHEMA,
    "properties": {**_SOURCE_SCHEMA["properties"], "fit": {"type": "string", "enum": list(FITS)}},
    "required": [*_SOURCE_SCHEMA["required"], "fit"],
}

ASSIGNMENT_SCHEMA = {
    "type": "object",
    "properties": {"sources": {"type": "array", "items": _ASSIGNED_SOURCE_SCHEMA}},
    "required": ["sources"],
    "additionalProperties": False,
}


GROUPING_SCHEMA = {
    "type": "object",
    "properties": {
        "topics": {"type": "array", "items": _TOPIC_SCHEMA},
        "tasks": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "index": {"type": "integer"},
                "topic": {"type": "string"},
                "fit": {"type": "string", "enum": list(FITS)},
            },
            "required": ["index", "topic", "fit"],
            "additionalProperties": False,
        }},
    },
    "required": ["topics", "tasks"],
    "additionalProperties": False,
}


def range_numbers(text: str) -> list[int]:
    """`"3"` or `"3-5"` as a list of 1-based numbers."""
    m = RANGE.match(text.replace(" ", ""))
    if not m:
        raise ValueError(text)
    first = int(m[1])
    last = int(m[2] or m[1])
    return list(range(first, last + 1))


def validate_unit(reply: dict, known: set[str], block_counts: dict[str, int]) -> list[str]:
    """Checks a unit's reply against the slugs of the topics so far and the unit's files, given by their document
    titles with their numbers of blocks."""
    errors = []
    replied = {}
    for t in reply["topics"]:
        slug = t["slug"]
        if not SLUG.match(slug):
            errors.append(f"invalid slug {slug!r}: use lowercase letters, digits, and single hyphens")
        if slug == OTHER:
            errors.append(f"slug {OTHER!r} is reserved")
        if slug in replied:
            errors.append(f"topic {slug!r} appears more than once")
        replied[slug] = t
    with_sources = {s["topic"] for s in reply["sources"]}
    for slug in replied.keys() - known - with_sources:
        if not replied[slug]["raised_by_notes"]:
            errors.append(f"new topic {slug!r} has no source; create a topic only for tasks of this unit or the notes")
    for s in reply["sources"]:
        where = f"source {s['task']!r}"
        if s["topic"] not in known | replied.keys():
            errors.append(f"{where}: unknown topic {s['topic']!r}; use the slug of a topic so far or of a new topic")
        if not s["blocks"]:
            errors.append(f"{where} has no blocks")
        for r in s["blocks"]:
            if r["file"] not in block_counts:
                errors.append(f"{where}: unknown file {r['file']!r}; use a document title of this unit exactly")
                continue
            try:
                numbers = range_numbers(r["blocks"])
            except ValueError:
                errors.append(f"{where}: invalid blocks {r['blocks']!r}; write `3` or `3-5`")
                continue
            count = block_counts[r["file"]]
            if not numbers or numbers[0] < 1 or numbers[-1] > count:
                errors.append(f"{where}: blocks {r['blocks']!r} outside {r['file']}, which has {count} blocks")
    return errors


def validate_grouping(reply: dict, known: set[str], count: int) -> list[str]:
    """Checks the grouping of the `count` tasks of `OTHER` against the slugs of the topics."""
    errors = []
    new = set()
    for t in reply["topics"]:
        slug = t["slug"]
        if not SLUG.match(slug):
            errors.append(f"invalid slug {slug!r}: use lowercase letters, digits, and single hyphens")
        if slug in known | new | {OTHER}:
            errors.append(f"slug {slug!r} is taken")
        new.add(slug)
    seen = set()
    for m in reply["tasks"]:
        if not 1 <= m["index"] <= count:
            errors.append(f"task {m['index']} does not exist; the tasks are numbered 1 to {count}")
        if m["index"] in seen:
            errors.append(f"task {m['index']} appears more than once")
        seen.add(m["index"])
        if m["topic"] not in known | new | {OTHER}:
            errors.append(f"task {m['index']}: unknown topic {m['topic']!r}")
    for slug in new - {m["topic"] for m in reply["tasks"]}:
        errors.append(f"new topic {slug!r} has no task")
    return errors


def apply_grouping(topics: list[Topic], reply: dict) -> list[Topic]:
    """The topics with the grouping's new topics, and the tasks of `OTHER` moved as it says; `OTHER` last, and
    gone once empty."""
    by_slug = {t["slug"]: {**t, "sources": list(t["sources"])} for t in topics}
    other = by_slug.pop(OTHER)
    for t in reply["topics"]:
        by_slug[t["slug"]] = {**t, "raised_by_notes": False, "sources": []}
    moved = {m["index"] - 1: m for m in reply["tasks"] if m["topic"] != OTHER}
    for i, s in enumerate(other["sources"]):
        if i in moved:
            by_slug[moved[i]["topic"]]["sources"].append({**s, "fit": moved[i]["fit"]})
    rest = [s for i, s in enumerate(other["sources"]) if i not in moved]
    return [*by_slug.values(), *([{**other, "sources": rest}] if rest else [])]


def apply_unit(topics: list[Topic], reply: dict) -> list[Topic]:
    """The topics with the unit's new and changed topics and its sources added, each with its fit - `clear` for a
    source without one; a source assigned to `OTHER` creates that topic."""
    by_slug = {t["slug"]: {**t, "sources": list(t["sources"])} for t in topics}
    if any(s["topic"] == OTHER for s in reply["sources"]):
        by_slug.setdefault(OTHER, {**OTHER_TOPIC, "sources": []})
    for t in reply["topics"]:
        old = by_slug.get(t["slug"], {"sources": [], "raised_by_notes": False})
        by_slug[t["slug"]] = {**old, **t, "raised_by_notes": old["raised_by_notes"] or t["raised_by_notes"]}
    for s in reply["sources"]:
        by_slug[s["topic"]]["sources"].append({"task": s["task"], "tier": s["tier"], "fit": s.get("fit", "clear"),
                                               "blocks": s["blocks"]})
    return list(by_slug.values())


def priority(asked: set[str], raised_by_notes: bool, exams: list[str], units: list[str]) -> str:
    """The priority of a topic asked for in the units `asked`: by the share of the past `exams` that ask for it, or
    without past exams, of all `units`. The notes raise it to high."""
    pool = set(exams or units)
    share = len(asked & pool) / len(pool) if pool else 0
    if raised_by_notes or share >= 0.75:
        return "high"
    return "medium" if share else "low"


def sorted_by_priority(topics: list[Topic]) -> list[Topic]:
    return sorted(topics, key=lambda t: PRIORITIES.index(t["priority"]))
