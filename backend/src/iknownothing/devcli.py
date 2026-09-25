"""Development tool: create and ingest courses from the command line, without frontend and database."""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from iknownothing.ai_client import AIClient
from iknownothing.config import Settings
from iknownothing.course_store import CourseStore
from iknownothing.ingestion.pipeline import ingest


def create(settings: Settings, args: argparse.Namespace) -> None:
    store = CourseStore(settings.data_dir, args.user, args.course)
    if store.exists():
        sys.exit(f"course exists: {store.root}")
    sources = {"exams": args.exams, "exercises": args.exercises}
    for doc_type, files in sources.items():
        names = [f.name for f in files]
        if len(set(names)) != len(names):
            sys.exit(f"{doc_type}: duplicate file names")
        for f in files:
            if f.suffix.lower() != ".pdf":
                sys.exit(f"not a PDF: {f}")
    store.write_text("notes.md", args.notes.read_text(encoding="utf-8"))
    for doc_type, files in sources.items():
        for f in files:
            store.write_bytes(f"sources/{doc_type}/{f.name}", f.read_bytes())
    print(f"created {store.root}")


def run_ingest(settings: Settings, args: argparse.Namespace) -> None:
    store = CourseStore(settings.data_dir, args.user, args.course)
    if not store.exists():
        sys.exit(f"no such course: {store.root}")
    ai = AIClient(settings, args.user, args.course)
    try:
        asyncio.run(ingest(store, ai, report=lambda s: print(s, flush=True)))
    finally:
        for model, u in ai.usage.items():
            print(
                f"{model}: {u['requests']} requests, input {u['input']}, output {u['output']}, "
                f"cache read {u['cache_read']}, cache write {u['cache_write']}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(prog="ikn-dev")
    sub = parser.add_subparsers(required=True)
    course = sub.add_parser("course").add_subparsers(required=True)

    p = course.add_parser("create", help="create a course from local files")
    p.add_argument("user")
    p.add_argument("course")
    p.add_argument("--notes", type=Path, required=True)
    p.add_argument("--exams", type=Path, nargs="*", default=[])
    p.add_argument("--exercises", type=Path, nargs="*", default=[])
    p.set_defaults(func=create)

    p = course.add_parser("ingest", help="ingest a course; resumes where a previous run stopped")
    p.add_argument("user")
    p.add_argument("course")
    p.set_defaults(func=run_ingest)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for noisy in ("anthropic", "httpx", "httpx2", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    args.func(Settings.from_env(), args)
