"""The HTTP API: users, courses, course files, and chats; serves the built frontend from `IKN_FRONTEND_DIR`.

With `IKN_MOCK_USER=1`, there is also the user `mock`: its courses are the mock client's sample data, its chats
are answered by the mock AI client, open as the sample chat, and are not stored.

Every request except listing and choosing users is served for the user in the cookie `ikn_user`.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from iknownothing import accounts, courses
from iknownothing.ai_client import AIClient, AIError
from iknownothing.config import Settings
from iknownothing.course_store import CourseStore, CourseStoreError
from iknownothing.ingestion import runs
from iknownothing.ingestion.pipeline import RESULT, unit
from iknownothing.mock.ai_client import SAMPLE_DATA, MockAIClient, sample_chat
from iknownothing.tutor.chat import PROGRESS, TutorError, progress, reply, topic_entry

log = logging.getLogger(__name__)

settings = Settings.from_env()
app = FastAPI(title="iknownothing")

HEARTBEAT = 10
COOKIE = "ikn_user"
MOCK_USER = "mock"



def _is_mock(user: str) -> bool:
    return settings.mock_user and user == MOCK_USER


def _data_dir(user: str) -> Path:
    return SAMPLE_DATA if _is_mock(user) else settings.data_dir


def _user_exists(name: str) -> bool:
    return accounts.exists(_data_dir(name), name)


def current_user(ikn_user: str | None = Cookie(None)) -> str:
    if ikn_user is None or not _user_exists(ikn_user):
        raise HTTPException(401, "no user chosen")
    return ikn_user


@app.get("/api/users")
def list_users() -> list[str]:
    names = accounts.names(settings.data_dir)
    return sorted({*names, MOCK_USER}) if settings.mock_user else names


@app.get("/api/user")
def get_user(user: str = Depends(current_user)) -> dict:
    return {"name": user}


class UserChoice(BaseModel):
    name: str


@app.post("/api/user", status_code=204)
def choose_user(body: UserChoice, response: Response) -> None:
    if not _user_exists(body.name):
        raise HTTPException(404, "no such user")
    response.set_cookie(COOKIE, body.name, max_age=365 * 24 * 3600, httponly=True, samesite="strict")


def course_store(course: str, user: str = Depends(current_user)) -> CourseStore:
    try:
        store = CourseStore(_data_dir(user), user, course)
    except CourseStoreError:
        raise HTTPException(404, "no such course")
    if not store.exists():
        raise HTTPException(404, "no such course")
    return store


def ready_store(store: CourseStore = Depends(course_store)) -> CourseStore:
    if not store.exists("topics.json"):
        raise HTTPException(409, "course is not ingested")
    return store


def _summary(store: CourseStore) -> dict:
    """A course's name and status, with the step of a running ingestion or why the last one failed."""
    return {"name": store.course, "status": courses.status(store), "ingestion": runs.step(store),
            "error": runs.error(store)}


@app.get("/api/courses")
def list_courses(user: str = Depends(current_user)) -> list[dict]:
    data_dir = _data_dir(user)
    names = sorted(p.name for p in (data_dir / user).iterdir() if p.is_dir())
    return [_summary(CourseStore(data_dir, user, n)) for n in names]


async def _material(exams: list[UploadFile], exercises: list[UploadFile]) -> courses.Material:
    return {"exams": [(f.filename or "", await f.read()) for f in exams],
            "exercises": [(f.filename or "", await f.read()) for f in exercises]}


def _ingest(store: CourseStore) -> None:
    try:
        runs.start(settings, store)
    except runs.IngestionRunning as e:
        raise HTTPException(409, str(e))


@app.post("/api/courses", status_code=202)
async def create_course(name: str = Form(), notes: str = Form(""), exams: list[UploadFile] = File([]),
                        exercises: list[UploadFile] = File([]), user: str = Depends(current_user)) -> dict:
    """Creates a course from its notes and PDFs and starts ingesting it."""
    if _is_mock(user):
        raise HTTPException(403, "the mock user cannot create courses")
    try:
        store = CourseStore(settings.data_dir, user, name)
        courses.create(store, notes, await _material(exams, exercises))
    except CourseStoreError:
        raise HTTPException(422, "a course name has lowercase letters, digits, hyphens, and underscores")
    except courses.CourseError as e:
        raise HTTPException(409 if store.exists() else 422, str(e))
    _ingest(store)
    return _summary(store)


@app.post("/api/courses/{course}/files", status_code=202)
async def add_files(notes: str = Form(), exams: list[UploadFile] = File([]), exercises: list[UploadFile] = File([]),
                    store: CourseStore = Depends(course_store)) -> dict:
    """Adds PDFs to a course, replaces its notes, and starts ingesting what is new."""
    if _is_mock(store.user):
        raise HTTPException(403, "the mock user cannot change courses")
    if runs.step(store):
        raise HTTPException(409, f"{store.course} is being ingested")
    try:
        courses.add(store, notes, await _material(exams, exercises))
    except courses.CourseError as e:
        raise HTTPException(422, str(e))
    _ingest(store)
    return _summary(store)


@app.post("/api/courses/{course}/ingestion", status_code=202)
def retry_ingestion(store: CourseStore = Depends(course_store)) -> dict:
    """Starts ingesting the course again, from the steps whose results are missing."""
    if _is_mock(store.user):
        raise HTTPException(403, "the mock user cannot change courses")
    _ingest(store)
    return _summary(store)


@app.delete("/api/courses/{course}", status_code=204)
def delete_course(store: CourseStore = Depends(course_store)) -> None:
    """Deletes the course with everything in it."""
    if _is_mock(store.user):
        raise HTTPException(403, "the mock user cannot change courses")
    if runs.step(store):
        raise HTTPException(409, f"{store.course} is being ingested")
    store.remove()


@app.get("/api/courses/{course}")
def get_course(store: CourseStore = Depends(course_store)) -> dict:
    """The course with its topics in priority order, each with its score, the Markdown files and the progress of its
    directory, and its sources: the PDFs and their Markdown conversions.

    `usage` holds the tokens spent on the chats of a topic.
    """
    topics = []
    if store.exists("topics.json"):
        for t in store.read_json("topics.json"):
            files = sorted(p.name for p in store.path(t["dir"]).glob("*") if p.suffix == ".md" or p.name == PROGRESS)
            topics.append({"slug": t["slug"], "name": t["name"], "priority": t["priority"],
                           "score": progress(store, t)["score"],
                           "files": [f"{t['dir']}/{f}" for f in files], "usage": courses.usage(store, t["dir"])})
    sources = sorted((p.relative_to(store.root).as_posix() for p in store.path("sources").glob("*/*")
                      if p.suffix in (".md", ".pdf")),
                     key=lambda f: (f.split("/")[1], unit(f), f))
    return {"name": store.course, "status": courses.status(store), "topics": topics,
            "files": [f for f in ("notes.md", "cheatsheet.md") if store.exists(f)], "sources": sources}


SOURCE_MEDIA = {".jpeg": "image/jpeg", ".jpg": "image/jpeg", ".png": "image/png", ".pdf": "application/pdf"}


@app.get("/api/courses/{course}/files/{rel:path}", response_model=None)
def read_file(rel: str, store: CourseStore = Depends(course_store)) -> PlainTextResponse | FileResponse:
    """A Markdown file of the course, or a source PDF or an image of its conversion; pipeline results are not
    served."""
    try:
        path = store.path(rel)
    except CourseStoreError:
        raise HTTPException(404, "no such file")
    if not path.is_file():
        raise HTTPException(404, "no such file")
    if path.suffix == ".md" or path.name == PROGRESS:
        return PlainTextResponse(store.read_text(rel))
    if path.suffix in SOURCE_MEDIA and rel.startswith("sources/"):
        return FileResponse(path, media_type=SOURCE_MEDIA[path.suffix])
    raise HTTPException(404, "no such file")


def _directory(store: CourseStore, topic: str) -> str:
    """The directory of a topic."""
    try:
        return topic_entry(store, topic)["dir"]
    except TutorError as e:
        raise HTTPException(404, str(e))


@app.get("/api/courses/{course}/chat")
def get_chat(topic: str, store: CourseStore = Depends(ready_store)) -> dict:
    """The open chat of a topic: its transcript and usage."""
    directory = _directory(store, topic)
    return sample_chat() if _is_mock(store.user) else courses.chat(store, directory)


@app.delete("/api/courses/{course}/chat", status_code=204)
def end_chat(topic: str, store: CourseStore = Depends(ready_store)) -> None:
    """Ends the open chat."""
    directory = _directory(store, topic)
    if not _is_mock(store.user):
        courses.end_chat(store, directory)


class ChatRequest(BaseModel):
    topic: str
    transcript: list[dict]


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/api/courses/{course}/chat")
async def chat(body: ChatRequest, store: CourseStore = Depends(ready_store)) -> StreamingResponse:
    """Streams the reply to a transcript that ends with the student's message; stores the chat with the reply.

    Events: `thinking`, `text`, `tool`, `cheatsheet`, and `task` while the reply arrives, then `usage` with the
    tokens of the reply and `messages` with the messages to append to the transcript, or `error`. While the model thinks, a comment every
    `HEARTBEAT` seconds keeps the connection from being closed as idle.
    """
    if not body.transcript or body.transcript[-1].get("role") != "user":
        raise HTTPException(422, "the transcript must end with the student's message")
    directory = _directory(store, body.topic)
    transcript = body.transcript
    start = len(transcript)
    language = store.read_json(RESULT)["language"]

    async def produce(queue: asyncio.Queue) -> None:
        ai = _ai_client(store)
        try:
            async for event in reply(store, ai, body.topic, language, transcript):
                await queue.put(event)
            if not _is_mock(store.user):
                await asyncio.to_thread(courses.save_chat, store, directory, transcript, ai.tokens())
            await queue.put(("usage", ai.tokens()))
            await queue.put(("messages", transcript[start:]))
        except (TutorError, AIError) as e:
            await queue.put(("error", str(e)))
        except Exception:
            log.exception("chat failed")
            await queue.put(("error", "the reply failed"))
        finally:
            if not _is_mock(store.user):
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


def _ai_client(store: CourseStore) -> AIClient | MockAIClient:
    return (MockAIClient if _is_mock(store.user) else AIClient)(settings, store.user, store.course)


async def _add_usage(store: CourseStore, directory: str, ai: AIClient) -> None:
    try:
        await courses.add_usage(store, directory, ai.tokens())
    except Exception:
        log.exception("recording usage of %s/%s failed", store.user, store.course)


if settings.frontend_dir:
    app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
