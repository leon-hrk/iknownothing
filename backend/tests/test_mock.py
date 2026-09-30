import asyncio

import pytest

from iknownothing.mock import ai_client as mock_ai_client
from iknownothing.ai_client import AIError
from iknownothing.config import Settings
from iknownothing.mock.ai_client import TASK, MockAIClient, commands, replies, rounds, sample_chat
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
    kinds = [k for k, _ in events]
    assert kinds.count("text") > 100 and set(kinds) == {"thinking", "text"}
    assert kinds.index("text") > max(i for i, k in enumerate(kinds) if k == "thinking")
    assert "".join(v for k, v in events if k == "text") == normal
    thinking = "".join(v for k, v in events if k == "thinking")
    assert transcript[-1] == {"role": "assistant", "content": [
        {"type": "thinking", "thinking": thinking, "signature": "mock"}, {"type": "text", "text": normal}]}
    assert ai.tokens()["eur"] == 0


def test_tools_poses_a_task_in_a_tool_round(store, ai):  # noqa: F811
    transcript = [{"role": "user", "content": "/tools"}]
    events = run_reply(store, ai, transcript)

    kinds = [k for i, (k, _) in enumerate(events) if i == 0 or k != events[i - 1][0]]
    assert kinds == ["thinking", "text", "tool", "task", "thinking", "text"]
    assert ("tool", "pose_task") in events and ("task", TASK) in events
    assert [m["role"] for m in transcript] == ["user", "assistant", "user", "assistant"]
    assert transcript[2]["content"][0]["type"] == "tool_result"


@pytest.mark.parametrize("message", ["hello", "/unknown"])
def test_other_messages_list_the_commands(store, ai, message):  # noqa: F811
    events = run_reply(store, ai, [{"role": "user", "content": message}])
    assert "- `/normal`" in "".join(v for _, v in events)


def test_other_requests_fail(ai):
    with pytest.raises(AIError):
        asyncio.run(ai.request_text("finalization", []))


def test_sample_chat_sends_each_command():
    transcript = sample_chat()["transcript"]
    sent = [m["content"] for m in transcript if isinstance(m["content"], str)]
    assert sent == [f"/{name}" for name in commands()]
    replied = [m["content"] for m in transcript if m["role"] == "assistant"]
    assert replied == [c for name in commands() for c in rounds(f"/{name}")]
