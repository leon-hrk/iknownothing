"""The operator's commands: users, and courses handed to a user."""

import argparse
import asyncio
import logging
import sys

from iknownothing import accounts, courses
from iknownothing.ai_client import AIClient, AIError
from iknownothing.config import Settings
from iknownothing.course_store import CourseStore, CourseStoreError
from iknownothing.ingestion.pipeline import IngestionError, ingest
from iknownothing.ocr_client import OCRClient, OCRError


class CommandError(Exception):
    pass


def user_command(settings: Settings, args: argparse.Namespace) -> None:
    if args.command == "add":
        accounts.add(settings.data_dir, args.name)
    else:
        accounts.remove(settings.data_dir, args.name)
    print(f"{args.command}: {args.name}")


def course_store(settings: Settings, user: str, course: str) -> CourseStore:
    if not accounts.exists(settings.data_dir, user):
        raise CommandError(f"no such user: {user}")
    return CourseStore(settings.data_dir, user, course)


def run_ingest(settings: Settings, store: CourseStore) -> None:
    ai = AIClient(settings, store.user, store.course)
    ocr = OCRClient(settings, store.user, store.course)

    async def run() -> None:
        try:
            await ingest(store, ai, ocr, report=lambda s: print(s, flush=True))
        finally:
            await ai.close()
            await ocr.close()

    try:
        asyncio.run(run())
    finally:
        print(f"OCR: {ocr.pages} pages")
        for model, u in ai.usage.items():
            print(f"{model}: {u['requests']} requests, input {u['input']}, output {u['output']}, "
                  f"cache read {u['cache_read']}, cache write {u['cache_write']}")


def course_add(settings: Settings, args: argparse.Namespace) -> None:
    store = course_store(settings, args.user, args.course)
    courses.add_from_dir(store, settings.courses_dir / (args.dir or args.course))
    run_ingest(settings, store)


def course_update(settings: Settings, args: argparse.Namespace) -> None:
    store = course_store(settings, args.user, args.course)
    if not store.exists():
        raise CommandError(f"no such course: {args.user}/{args.course}")
    added = courses.update_from_dir(store, settings.courses_dir / (args.dir or args.course))
    print(f"added {len(added)} PDFs" + "".join(f"\n  {rel}" for rel in added))
    run_ingest(settings, store)


def course_ingest(settings: Settings, args: argparse.Namespace) -> None:
    store = course_store(settings, args.user, args.course)
    if not store.exists():
        raise CommandError(f"no such course: {args.user}/{args.course}")
    run_ingest(settings, store)


def course_remove(settings: Settings, args: argparse.Namespace) -> None:
    store = course_store(settings, args.user, args.course)
    if not store.exists():
        raise CommandError(f"no such course: {args.user}/{args.course}")
    store.remove()
    print(f"removed {args.user}/{args.course}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="iknownothing")
    sub = parser.add_subparsers(required=True)

    user = sub.add_parser("user").add_subparsers(dest="command", required=True)
    for command, help in [("add", "create a user"), ("remove", "delete a user with all their courses")]:
        p = user.add_parser(command, help=help)
        p.add_argument("name")
        p.set_defaults(func=user_command)

    course = sub.add_parser("course").add_subparsers(required=True)
    for command, help, func in [
        ("add", "hand a course to a user: ingest it from a directory under courses/", course_add),
        ("update", "add the new PDFs of the course's directory under courses/ and ingest them", course_update),
    ]:
        p = course.add_parser(command, help=help)
        p.add_argument("user")
        p.add_argument("course")
        p.add_argument("dir", nargs="?", help="directory under courses/ with notes.md, exams/, exercises/; "
                                              "defaults to the course name")
        p.set_defaults(func=func)
    p = course.add_parser("ingest", help="run the ingestion steps whose results are missing, e.g. after a failure")
    p.add_argument("user")
    p.add_argument("course")
    p.set_defaults(func=course_ingest)
    p = course.add_parser("remove", help="delete a user's course with their cheatsheet and progress")
    p.add_argument("user")
    p.add_argument("course")
    p.set_defaults(func=course_remove)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for noisy in ("anthropic", "httpx", "httpx2", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    try:
        args.func(Settings.from_env(), args)
    except (CommandError, accounts.AccountError, courses.CourseError, CourseStoreError,
            IngestionError, AIError, OCRError) as e:
        sys.exit(str(e))
