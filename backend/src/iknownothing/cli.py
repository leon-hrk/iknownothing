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
    try:
        asyncio.run(ingest(store, ai, report=lambda s: print(s, flush=True)))
    finally:
        for model, u in ai.usage.items():
            print(f"{model}: {u['requests']} requests, input {u['input']}, output {u['output']}, "
                  f"cache read {u['cache_read']}, cache write {u['cache_write']}")


def course_add(settings: Settings, args: argparse.Namespace) -> None:
    store = course_store(settings, args.user, args.course)
    if args.source:
        courses.copy_from(store, CourseStore(settings.data_dir, args.source, args.course))
        print(f"copied {args.source}/{args.course} to {args.user}")
        return
    courses.add_from_dir(store, settings.courses_dir / (args.dir or args.course))
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
    p = course.add_parser("add", help="hand a course to a user: ingest it from a directory under courses/, "
                                      "or copy it from another user without their cheatsheet and progress")
    p.add_argument("user")
    p.add_argument("course")
    source = p.add_mutually_exclusive_group()
    source.add_argument("dir", nargs="?", help="directory under courses/ with notes.md, exams/, exercises/; "
                                               "defaults to the course name")
    source.add_argument("--from", dest="source", metavar="USER", help="user whose ingested course to copy")
    p.set_defaults(func=course_add)
    p = course.add_parser("ingest", help="resume an ingestion that failed")
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
            IngestionError, AIError) as e:
        sys.exit(str(e))
