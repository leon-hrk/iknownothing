import asyncio

import pytest

from iknownothing.mock import ai_client as mock_ai_client
from iknownothing.ai_client import AIError
from iknownothing.config import Settings
from iknownothing.mock.ai_client import MockAIClient, replies, sample_chat
from test_tutor import run_reply, store  # noqa: F401


@pytest.fixture
def ai(tmp_path, monkeypatch):
    monkeypatch.setattr(mock_ai_client, "THINKING_SECONDS", 0)
    monkeypatch.setattr(mock_ai_client, "CHUNK_SECONDS", 0)
    return MockAIClient(Settings(tmp_path, "m", "m"), "alice", "signals")


def test_command_streams_its_reply(store, ai):  # noqa: F811
    transcript = [{"role": "user", "content": "/normal"}]
    events = run_reply(store, ai, transcript)

    normal = replies()["normal"]
    assert len(events) > 100 and {k for k, _ in events} == {"text"}
    assert "".join(v for _, v in events) == normal
    assert transcript[-1] == {"role": "assistant", "content": [{"type": "text", "text": normal}]}
    assert ai.tokens()["eur"] == 0


@pytest.mark.parametrize("message", ["hello", "/unknown"])
def test_other_messages_list_the_commands(store, ai, message):  # noqa: F811
    events = run_reply(store, ai, [{"role": "user", "content": message}])
    assert "- `/normal`" in "".join(v for _, v in events)


def test_other_requests_fail(ai):
    with pytest.raises(AIError):
        asyncio.run(ai.request_text("finalization", []))


def test_sample_chat_sends_each_command():
    transcript = sample_chat()["transcript"]
    sent = {m["content"]: n["content"][0]["text"] for m, n in zip(transcript[::2], transcript[1::2])}
    assert sent == {f"/{name}": text for name, text in replies().items()}
