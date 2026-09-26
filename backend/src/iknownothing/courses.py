"""Courses: a user's courses and their status, and the operator's course commands."""

import json
from pathlib import Path

from iknownothing.course_store import DOC_TYPES, CourseStore

STUDENT_STATE = ("cheatsheet.md", "progress.md", "usage.json")


class CourseError(Exception):
    pass


def status(store: CourseStore) -> str:
    return "ready" if store.exists("topics.json") else "not ingested"


def add_from_dir(store: CourseStore, src: Path) -> None:
    """Copies the course material in `src` - notes.md, exams/*.pdf, exercises/*.pdf - into a new course."""
    if store.exists():
        raise CourseError(f"course exists: {store.user}/{store.course}")
    if not src.is_dir():
        raise CourseError(f"no such directory: {src}")
    for p in src.iterdir():
        if not p.name.startswith(".") and p.name not in ("notes.md", *DOC_TYPES):
            raise CourseError(f"unexpected: {p}; a course has notes.md, {', '.join(f'{t}/' for t in DOC_TYPES)}")
    if not (src / "notes.md").is_file():
        raise CourseError(f"missing: {src / 'notes.md'}")
    sources = {t: sorted(f for f in (src / t).glob("*") if not f.name.startswith(".")) if (src / t).is_dir() else []
               for t in DOC_TYPES}
    for f in (f for files in sources.values() for f in files):
        if f.suffix != ".pdf" or not f.is_file():
            raise CourseError(f"not a .pdf file: {f}")
    if not any(sources.values()):
        raise CourseError(f"no PDFs in {', '.join(str(src / t) for t in DOC_TYPES)}")

    store.write_text("notes.md", (src / "notes.md").read_text(encoding="utf-8"))
    for doc_type, files in sources.items():
        for f in files:
            store.write_bytes(f"sources/{doc_type}/{f.name}", f.read_bytes())


def copy_from(store: CourseStore, src: CourseStore) -> None:
    """Copies an ingested course of another user, without the student state."""
    if store.exists():
        raise CourseError(f"course exists: {store.user}/{store.course}")
    if not src.exists("topics.json"):
        raise CourseError(f"not an ingested course: {src.user}/{src.course}")
    for rel in src.files():
        if rel.split("/")[-1] not in STUDENT_STATE:
            store.write_bytes(rel, src.read_bytes(rel))


USAGE = "usage.json"
_NO_USAGE = {"input": 0, "cached": 0, "output": 0, "eur": 0.0}


def _usage_file(directory: str) -> str:
    return f"{directory}/{USAGE}" if directory else USAGE


def usage(store: CourseStore, directory: str = "") -> dict[str, int]:
    """Tokens and approximate euros spent on the chats of a topic directory, or of the course-level chat for `""`."""
    rel = _usage_file(directory)
    return _NO_USAGE | (store.read_json(rel) if store.exists(rel) else {})


async def add_usage(store: CourseStore, directory: str, tokens: dict[str, float]) -> None:
    def change(text: str) -> str:
        total = _NO_USAGE | (json.loads(text) if text else {})
        return json.dumps({k: total[k] + tokens[k] for k in total}) + "\n"

    await store.update_text(_usage_file(directory), change)
