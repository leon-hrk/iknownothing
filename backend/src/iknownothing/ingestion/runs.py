"""Ingestions running in the backend process, at most one per course."""

import asyncio
import logging

from iknownothing.ai_client import AIClient
from iknownothing.config import Settings
from iknownothing.course_store import CourseStore
from iknownothing.ingestion.pipeline import ingest
from iknownothing.ocr_client import OCRClient

log = logging.getLogger(__name__)

ERROR = "ingestion/error.txt"

_steps: dict[tuple[str, str], str] = {}
_tasks: set[asyncio.Task] = set()


class IngestionRunning(Exception):
    pass


def step(store: CourseStore) -> str | None:
    """The step a running ingestion of the course is at, or None."""
    return _steps.get((store.user, store.course))


def error(store: CourseStore) -> str | None:
    """Why the last ingestion of the course failed, or None."""
    return store.read_text(ERROR) if store.exists(ERROR) else None


def start(settings: Settings, store: CourseStore) -> None:
    """Starts ingesting the course in the background."""
    key = (store.user, store.course)
    if key in _steps:
        raise IngestionRunning(f"{store.user}/{store.course} is being ingested")
    _steps[key] = "starting"
    store.delete(ERROR)
    task = asyncio.get_running_loop().create_task(_run(settings, store, key))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _run(settings: Settings, store: CourseStore, key: tuple[str, str]) -> None:
    def report(step: str) -> None:
        _steps[key] = step
        log.info("ingestion %s/%s: %s", store.user, store.course, step)

    clients = []
    try:
        ai = AIClient(settings, store.user, store.course)
        clients.append(ai)
        ocr = OCRClient(settings, store.user, store.course)
        clients.append(ocr)
        await ingest(store, ai, ocr, report)
    except Exception as e:
        log.exception("ingestion of %s/%s failed", store.user, store.course)
        store.write_text(ERROR, str(e) or type(e).__name__)
    finally:
        del _steps[key]
        for client in clients:
            await client.close()
