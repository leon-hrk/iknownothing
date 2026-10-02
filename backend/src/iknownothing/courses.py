"""Courses: a user's courses and their status, creating and adding to them, usage, and open chats."""

import json
from pathlib import Path

from iknownothing.course_store import DOC_TYPES, CourseStore

class CourseError(Exception):
    pass


def status(store: CourseStore) -> str:
    return "ready" if store.exists("topics.json") else "not ingested"


def _material(src: Path) -> dict[str, list[Path]]:
    """The PDFs of a course directory - notes.md, exams/*.pdf, exercises/*.pdf - by document type, after checking it."""
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
    return sources


Material = dict[str, list[tuple[str, bytes]]]
"""PDFs by document type, each with its file name."""


def _check(material: Material) -> None:
    for doc_type, files in material.items():
        if doc_type not in DOC_TYPES:
            raise CourseError(f"unknown document type: {doc_type}; the types are {', '.join(DOC_TYPES)}")
        for name, _ in files:
            if "/" in name or name.startswith(".") or not name.endswith(".pdf"):
                raise CourseError(f"not a .pdf file: {name}")


def create(store: CourseStore, notes: str, material: Material) -> None:
    """A new course from its notes and PDFs."""
    if store.exists():
        raise CourseError(f"course exists: {store.user}/{store.course}")
    _check(material)
    if not any(material.values()):
        raise CourseError("no PDFs: a course needs past exams or exercise sheets")
    store.write_text("notes.md", notes)
    for doc_type, files in material.items():
        for name, data in files:
            store.write_bytes(f"sources/{doc_type}/{name}", data)


def add(store: CourseStore, notes: str, material: Material) -> list[str]:
    """Adds the PDFs the course does not have yet and replaces its notes; returns the PDFs added. A PDF the course
    has must be unchanged."""
    _check(material)
    added = []
    for doc_type, files in material.items():
        for name, data in files:
            rel = f"sources/{doc_type}/{name}"
            if not store.exists(rel):
                added.append((rel, data))
            elif store.read_bytes(rel) != data:
                raise CourseError(f"changed: {name}; a PDF of a course cannot be replaced")
    store.write_text("notes.md", notes)
    for rel, data in added:
        store.write_bytes(rel, data)
    return [rel for rel, _ in added]


def _read(src: Path) -> tuple[str, Material]:
    sources = _material(src)
    return ((src / "notes.md").read_text(encoding="utf-8"),
            {t: [(f.name, f.read_bytes()) for f in files] for t, files in sources.items()})


def add_from_dir(store: CourseStore, src: Path) -> None:
    """Copies the course material in `src` - notes.md, exams/*.pdf, exercises/*.pdf - into a new course."""
    if store.exists():
        raise CourseError(f"course exists: {store.user}/{store.course}")
    create(store, *_read(src))


def update_from_dir(store: CourseStore, src: Path) -> list[str]:
    """Copies the PDFs in `src` that the course does not have yet, and its notes.md; returns the PDFs copied. A PDF
    the course has must be unchanged."""
    if not store.exists("topics.json"):
        raise CourseError(f"not an ingested course: {store.user}/{store.course}")
    return add(store, *_read(src))


USAGE = "usage.json"
_NO_USAGE = {"input": 0, "cached": 0, "output": 0, "eur": 0.0}


def usage(store: CourseStore, directory: str) -> dict[str, int]:
    """Tokens and approximate euros spent on the chats of a topic directory."""
    rel = f"{directory}/{USAGE}"
    return _NO_USAGE | (store.read_json(rel) if store.exists(rel) else {})


async def add_usage(store: CourseStore, directory: str, tokens: dict[str, float]) -> None:
    def change(text: str) -> str:
        total = _NO_USAGE | (json.loads(text) if text else {})
        return json.dumps({k: total[k] + tokens[k] for k in total}) + "\n"

    await store.update_text(f"{directory}/{USAGE}", change)


CHAT = "chat.json"


def _chat_file(directory: str) -> str:
    return f"{directory}/{CHAT}"


def chat(store: CourseStore, directory: str) -> dict:
    """The open chat of a topic directory: its transcript and usage."""
    rel = _chat_file(directory)
    return {"transcript": [], "usage": _NO_USAGE} | (store.read_json(rel) if store.exists(rel) else {})


def save_chat(store: CourseStore, directory: str, transcript: list[dict], tokens: dict[str, float]) -> None:
    """Stores the transcript and adds `tokens` to the open chat's usage."""
    total = chat(store, directory)["usage"]
    store.write_json(_chat_file(directory), {"transcript": transcript,
                                             "usage": {k: total[k] + tokens[k] for k in total}})


def end_chat(store: CourseStore, directory: str) -> list[dict]:
    """Removes the open chat; returns its transcript."""
    transcript = chat(store, directory)["transcript"]
    store.delete(_chat_file(directory))
    return transcript
