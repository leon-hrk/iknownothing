import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from iknownothing import api
from iknownothing.config import Settings
from iknownothing.mock import ai_client as mock_ai_client
from iknownothing.course_store import CourseStore
from iknownothing.mock.ai_client import SAMPLE_DATA, sample_chat
from test_tutor import FakeAI, store  # noqa: F401


class ClosableFakeAI(FakeAI):
    async def close(self):
        pass

    def tokens(self):
        return {"input": 100, "cached": 80, "output": 10, "eur": 0.5}


@pytest.fixture
def client(store, tmp_path, monkeypatch):  # noqa: F811
    store.write_json("ingestion/topics.json", {"language": "German"})
    monkeypatch.setattr(api, "settings", Settings(tmp_path, "m", "m"))
    monkeypatch.setattr(api, "AIClient", lambda *a: ClosableFakeAI())
    monkeypatch.setitem(api.app.dependency_overrides, api.current_user, lambda: "alice")
    return TestClient(api.app)


def events(response) -> list[tuple[str, object]]:
    out = []
    for chunk in response.text.strip().split("\n\n"):
        if chunk.startswith(":"):
            out.append(("heartbeat", None))
            continue
        kind, data = chunk.split("\n")
        out.append((kind.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


def test_course_and_files(client, store):  # noqa: F811
    assert client.get("/api/courses").json() == [{"name": "control", "status": "ready"}]
    course = client.get("/api/courses/control").json()
    store.write_json("topics/laplace/progress.json", {"introduction": True})
    course = client.get("/api/courses/control").json()
    assert course["topics"] == [{"slug": "laplace", "name": "Laplace", "priority": "high",
                                 "files": ["topics/laplace/progress.json", "topics/laplace/topic.md"], "usage": {"input": 0, "cached": 0, "output": 0, "eur": 0.0}}]
    assert course["files"] == ["notes.md"]
    assert course["sources"] == ["sources/exams/2023.md", "sources/exercises/uebung1.md"]
    assert client.get("/api/courses/control/files/topics/laplace/topic.md").text == "# Laplace"
    assert client.get("/api/courses/control/files/..%2F..%2Fbob/x/notes.md").status_code == 404
    assert client.get("/api/courses/nope").status_code == 404


def test_converted_sources(client, store):  # noqa: F811
    store.write_bytes("sources/exams/2023.pdf", b"%PDF")
    store.write_bytes("ingestion/figure.png", b"png")
    assert client.get("/api/courses/control").json()["sources"] == [
        "sources/exams/2023.md", "sources/exams/2023.pdf", "sources/exercises/uebung1.md"]
    assert client.get("/api/courses/control/files/sources/exams/2023.md").text.startswith("<!-- page 1 -->")
    image = client.get("/api/courses/control/files/sources/exams/2023/p2-img-0.jpeg")
    assert image.content == b"jpeg" and image.headers["content-type"] == "image/jpeg"
    pdf = client.get("/api/courses/control/files/sources/exams/2023.pdf")
    assert pdf.content == b"%PDF" and pdf.headers["content-type"] == "application/pdf"
    assert client.get("/api/courses/control/files/ingestion/figure.png").status_code == 404


def test_chat_streams_reply(client, store):  # noqa: F811
    transcript = [{"role": "user", "content": "quiz me"}]
    r = client.post("/api/courses/control/chat", json={"topic": "laplace", "transcript": transcript})
    evs = events(r)
    assert [k for k, _ in evs] == ["cheatsheet", "task", "text", "usage", "messages"]
    assert evs[-2][1] == {"input": 100, "cached": 80, "output": 10, "eur": 0.5}
    assert [m["role"] for m in evs[-1][1]] == ["assistant", "user", "assistant"]
    client.post("/api/courses/control/chat", json={"topic": "laplace", "transcript": transcript})
    client.post("/api/courses/control/chat", json={"topic": None, "transcript": transcript})
    course = client.get("/api/courses/control").json()
    assert course["topics"][0]["usage"] == {"input": 200, "cached": 160, "output": 20, "eur": 1.0}
    assert course["usage"] == {"input": 100, "cached": 80, "output": 10, "eur": 0.5}
    assert "Laplace" in store.read_text("cheatsheet.md")

    r = client.post("/api/courses/control/chat", json={"topic": "nope", "transcript": transcript})
    assert r.status_code == 404
    r = client.post("/api/courses/control/chat", json={"transcript": []})
    assert r.status_code == 422


def test_chat_is_stored_until_ended(client, store):  # noqa: F811
    empty = {"transcript": [], "usage": {"input": 0, "cached": 0, "output": 0, "eur": 0.0}}
    assert client.get("/api/courses/control/chat", params={"topic": "laplace"}).json() == empty
    transcript = [{"role": "user", "content": "quiz me"}]
    messages = events(client.post("/api/courses/control/chat", json={"topic": "laplace", "transcript": transcript}))[-1][1]
    client.post("/api/courses/control/chat", json={"topic": "laplace", "transcript": [*transcript, *messages, *transcript]})
    stored = client.get("/api/courses/control/chat", params={"topic": "laplace"}).json()
    assert len(stored["transcript"]) == 8
    assert stored["usage"] == {"input": 200, "cached": 160, "output": 20, "eur": 1.0}
    assert client.get("/api/courses/control/chat").json() == empty
    assert client.get("/api/courses/control/chat", params={"topic": "nope"}).status_code == 404

    assert client.delete("/api/courses/control/chat", params={"topic": "laplace"}).status_code == 204
    assert client.get("/api/courses/control/chat", params={"topic": "laplace"}).json() == empty


def test_ending_a_course_or_empty_chat(client, store):  # noqa: F811
    client.post("/api/courses/control/chat", json={"topic": None, "transcript": [{"role": "user", "content": "hi"}]})
    assert client.delete("/api/courses/control/chat").status_code == 204
    assert client.delete("/api/courses/control/chat", params={"topic": "laplace"}).status_code == 204
    assert not store.exists("chat.json")


def test_chat_heartbeat(client, monkeypatch):
    class SlowAI(ClosableFakeAI):
        async def stream_chat(self, *args):
            await asyncio.sleep(0.05)
            async for e in super().stream_chat(*args):
                yield e

    monkeypatch.setattr(api, "HEARTBEAT", 0.01)
    monkeypatch.setattr(api, "AIClient", lambda *a: SlowAI())
    r = client.post("/api/courses/control/chat", json={"topic": None, "transcript": [{"role": "user", "content": "hi"}]})
    kinds = [k for k, _ in events(r)]
    assert "heartbeat" in kinds and kinds[-1] == "messages"


def test_mock_user_gets_the_sample_data_and_stores_nothing(client, store, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(api, "settings", Settings(tmp_path, "m", "m", mock_user=True))
    monkeypatch.setattr(mock_ai_client, "THINKING_SECONDS", 0)
    monkeypatch.setattr(mock_ai_client, "CHUNK_SECONDS", 0)
    sample = CourseStore(SAMPLE_DATA, "mock", "sample-course")
    before = {rel: sample.read_bytes(rel) for rel in sample.files()}

    assert client.get("/api/users").json() == ["alice", "mock"]
    assert client.post("/api/user", json={"name": "mock"}).status_code == 204
    assert client.get("/api/courses").json() == [{"name": "control", "status": "ready"}]

    monkeypatch.setitem(api.app.dependency_overrides, api.current_user, lambda: "mock")
    assert client.get("/api/courses").json() == [{"name": "sample-course", "status": "ready"}]
    for topic in (None, "first-topic"):
        params = {"topic": topic} if topic else {}
        assert client.get("/api/courses/sample-course/chat", params=params).json() == sample_chat()
        r = client.post("/api/courses/sample-course/chat",
                        json={"topic": topic, "transcript": [{"role": "user", "content": "/normal"}]})
        assert events(r)[-1][0] == "messages"
        assert client.delete("/api/courses/sample-course/chat", params=params).status_code == 204
    assert {rel: sample.read_bytes(rel) for rel in sample.files()} == before


def test_no_mock_user_without_the_flag(client):
    assert client.get("/api/users").json() == ["alice"]
    assert client.post("/api/user", json={"name": "mock"}).status_code == 404
