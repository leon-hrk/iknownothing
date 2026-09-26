import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from iknownothing import api
from iknownothing.config import Settings
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


def test_course_and_files(client):
    assert client.get("/api/courses").json() == [{"name": "control", "status": "ready"}]
    course = client.get("/api/courses/control").json()
    assert course["topics"] == [{"slug": "laplace", "name": "Laplace", "priority": "high",
                                 "files": ["topics/laplace/topic.md"], "usage": {"input": 0, "cached": 0, "output": 0, "eur": 0.0}}]
    assert course["files"] == ["notes.md"]
    assert client.get("/api/courses/control/files/topics/laplace/topic.md").text == "# Laplace"
    assert client.get("/api/courses/control/files/sources/exams/2023.pdf").status_code == 404
    assert client.get("/api/courses/control/files/..%2F..%2Fbob/x/notes.md").status_code == 404
    assert client.get("/api/courses/nope").status_code == 404


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

    r = client.delete("/api/courses/control/chat", params={"topic": "laplace"})
    assert r.status_code == 202
    assert store.read_text("topics/laplace/progress.md") == "# Progress\n"
    assert client.get("/api/courses/control/chat", params={"topic": "laplace"}).json() == empty


def test_ending_an_empty_or_course_chat_does_not_finalize(client, store):  # noqa: F811
    client.post("/api/courses/control/chat", json={"topic": None, "transcript": [{"role": "user", "content": "hi"}]})
    assert client.delete("/api/courses/control/chat").status_code == 202
    assert client.delete("/api/courses/control/chat", params={"topic": "laplace"}).status_code == 202
    assert not store.exists("chat.json")
    assert not store.exists("topics/laplace/progress.md")


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
