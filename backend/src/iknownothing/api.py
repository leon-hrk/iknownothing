"""The HTTP API: users, courses, course files, and chats; serves the built frontend from `IKN_FRONTEND_DIR`.

Every request except listing and choosing users is served for the user in the cookie `ikn_user`.
"""

import asyncio
import json
import logging
from collections import defaultdict
from collections.abc import AsyncIterator

from fastapi import BackgroundTasks, Cookie, Depends, FastAPI, HTTPException, Response
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from iknownothing import accounts, courses
from iknownothing.ai_client import AIClient, AIError
from iknownothing.config import Settings
from iknownothing.course_store import CourseStore, CourseStoreError
from iknownothing.ingestion.pipeline import RESULT
from iknownothing.tutor.chat import TutorError, reply, topic_entry
from iknownothing.tutor.finalization import finalize

log = logging.getLogger(__name__)

settings = Settings.from_env()
app = FastAPI(title="iknownothing")

HEARTBEAT = 10
COOKIE = "ikn_user"

_finalization_locks: defaultdict[tuple[str, str], asyncio.Lock] = defaultdict(asyncio.Lock)


def current_user(ikn_user: str | None = Cookie(None)) -> str:
    if ikn_user is None or not accounts.exists(settings.data_dir, ikn_user):
        raise HTTPException(401, "no user chosen")
    return ikn_user


@app.get("/api/users")
def list_users() -> list[str]:
    return accounts.names(settings.data_dir)


@app.get("/api/user")
def get_user(user: str = Depends(current_user)) -> dict:
    return {"name": user}


class UserChoice(BaseModel):
    name: str


@app.post("/api/user", status_code=204)
def choose_user(body: UserChoice, response: Response) -> None:
    if not accounts.exists(settings.data_dir, body.name):
        raise HTTPException(404, "no such user")
    response.set_cookie(COOKIE, body.name, max_age=365 * 24 * 3600, httponly=True, samesite="strict")


def course_store(course: str, user: str = Depends(current_user)) -> CourseStore:
    try:
        store = CourseStore(settings.data_dir, user, course)
    except CourseStoreError:
        raise HTTPException(404, "no such course")
    if not store.exists():
        raise HTTPException(404, "no such course")
    return store


def ready_store(store: CourseStore = Depends(course_store)) -> CourseStore:
    if not store.exists("topics.json"):
        raise HTTPException(409, "course is not ingested")
    return store


@app.get("/api/courses")
def list_courses(user: str = Depends(current_user)) -> list[dict]:
    d = settings.data_dir / user
    names = sorted(p.name for p in d.iterdir() if p.is_dir())
    return [{"name": n, "status": courses.status(CourseStore(settings.data_dir, user, n))} for n in names]


@app.get("/api/courses/{course}")
def get_course(store: CourseStore = Depends(course_store)) -> dict:
    """The course with its topics in priority order, each with the Markdown files of its directory.

    `usage` holds the tokens spent on the chats of a topic, finalizations included, and on the
    course-level chat.
    """
    topics = []
    if store.exists("topics.json"):
        for t in store.read_json("topics.json"):
            files = sorted(p.name for p in store.path(t["dir"]).glob("*.md"))
            topics.append({"slug": t["slug"], "name": t["name"], "priority": t["priority"],
                           "files": [f"{t['dir']}/{f}" for f in files], "usage": courses.usage(store, t["dir"])})
    return {"name": store.course, "status": courses.status(store), "topics": topics,
            "files": [f for f in ("notes.md", "cheatsheet.md") if store.exists(f)], "usage": courses.usage(store)}


@app.get("/api/courses/{course}/files/{rel:path}", response_class=PlainTextResponse)
def read_file(rel: str, store: CourseStore = Depends(course_store)) -> str:
    """A Markdown file of the course; uploaded PDFs and pipeline results are not served."""
    try:
        path = store.path(rel)
    except CourseStoreError:
        raise HTTPException(404, "no such file")
    if path.suffix != ".md" or not path.is_file():
        raise HTTPException(404, "no such file")
    return store.read_text(rel)


class ChatRequest(BaseModel):
    topic: str | None = None
    transcript: list[dict]


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/api/courses/{course}/chat")
async def chat(body: ChatRequest, store: CourseStore = Depends(ready_store)) -> StreamingResponse:
    """Streams the reply to a transcript that ends with the student's message.

    Events: `text`, `cheatsheet`, and `task` while the reply arrives, then `usage` with the
    tokens of the reply and `messages` with the messages to append to the transcript, or `error`. While the model thinks, a comment every
    `HEARTBEAT` seconds keeps the connection from being closed as idle.
    """
    if not body.transcript or body.transcript[-1].get("role") != "user":
        raise HTTPException(422, "the transcript must end with the student's message")
    directory = ""
    if body.topic is not None:
        try:
            directory = topic_entry(store, body.topic)["dir"]
        except TutorError as e:
            raise HTTPException(404, str(e))
    transcript = body.transcript
    start = len(transcript)
    language = store.read_json(RESULT)["language"]

    async def produce(queue: asyncio.Queue) -> None:
        ai = AIClient(settings, store.user, store.course)
        try:
            async for event in reply(store, ai, body.topic, language, transcript):
                await queue.put(event)
            await queue.put(("usage", ai.tokens()))
            await queue.put(("messages", transcript[start:]))
        except (TutorError, AIError) as e:
            await queue.put(("error", str(e)))
        except Exception:
            log.exception("chat failed")
            await queue.put(("error", "the reply failed"))
        finally:
            await _add_usage(store, directory, ai)
            await ai.close()
            await queue.put(None)

    async def events() -> AsyncIterator[str]:
        queue: asyncio.Queue = asyncio.Queue()
        task = asyncio.create_task(produce(queue))
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), HEARTBEAT)
                except TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                if event is None:
                    return
                yield _sse(*event)
        finally:
            task.cancel()

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _add_usage(store: CourseStore, directory: str, ai: AIClient) -> None:
    try:
        await courses.add_usage(store, directory, ai.tokens())
    except Exception:
        log.exception("recording usage of %s/%s failed", store.user, store.course)


class FinalizeRequest(BaseModel):
    transcript: list[dict]


async def _finalize(store: CourseStore, slug: str, transcript: list[dict]) -> None:
    ai = AIClient(settings, store.user, store.course)
    try:
        async with _finalization_locks[(store.user, store.course)]:
            await finalize(store, ai, slug, store.read_json(RESULT)["language"], transcript)
    except Exception:
        log.exception("finalization of %s/%s/%s failed", store.user, store.course, slug)
    finally:
        await _add_usage(store, topic_entry(store, slug)["dir"], ai)
        await ai.close()


@app.post("/api/courses/{course}/topics/{slug}/finalize", status_code=202)
def finalize_chat(slug: str, body: FinalizeRequest, tasks: BackgroundTasks,
                  store: CourseStore = Depends(ready_store)) -> None:
    """Ends a topic-level chat: its topic's progress.md is updated from the transcript in the background."""
    try:
        topic_entry(store, slug)
    except TutorError as e:
        raise HTTPException(404, str(e))
    if body.transcript:
        tasks.add_task(_finalize, store, slug, body.transcript)


if settings.frontend_dir:
    app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
