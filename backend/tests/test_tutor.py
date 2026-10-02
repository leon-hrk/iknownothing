import asyncio
import base64
from types import SimpleNamespace

import pytest

from iknownothing.course_store import CourseStore
from iknownothing.tutor.chat import TutorError, course_context, reply, topic_context
from iknownothing.tutor.cheatsheet import CheatsheetError, parse, set_entry
from iknownothing.tutor.finalization import finalize, render_transcript


@pytest.fixture
def store(tmp_path):
    s = CourseStore(tmp_path, "alice", "control")
    s.write_text("notes.md", "notes")
    s.write_text("sources/exams/2023.md", (
        "<!-- page 1 -->\n\n# Aufgabe 1\n\nIntro\n\n<!-- page 2 -->\n\n# Aufgabe 2\n\nGegeben:\n\n"
        "![p2-img-0.jpeg](2023/p2-img-0.jpeg)\n\na) Teil a\n\nb) Teil b\n"))
    s.write_bytes("sources/exams/2023/p2-img-0.jpeg", b"jpeg")
    s.write_text("sources/exercises/uebung1.md", "<!-- page 1 -->\n\nÜbung 1\n\nLösung\n")
    s.write_text("topics/laplace/topic.md", "# Laplace")
    s.write_json("topics.json", [{
        "slug": "laplace", "name": "Laplace", "priority": "high", "dir": "topics/laplace",
        "sources": [
            {"id": "laplace/1", "task": "Klausur 2023, Aufgabe 2b", "tier": "A", "fit": "clear", "blocks": [
                {"file": "exams/2023.md", "blocks": "5-7", "pages": "2"},
                {"file": "exams/2023.md", "blocks": "9", "pages": "2"}]},
            {"id": "laplace/2", "task": "Übung 1, Aufgabe 1", "tier": "B", "fit": "loose", "blocks": [
                {"file": "exercises/uebung1.md", "blocks": "2-3", "pages": "1"}]},
        ],
    }])
    return s


def test_cheatsheet_entries():
    text = set_entry("", "Laplace", "Transform", "$F(s)$")
    text = set_entry(text, "Laplace", "Final value", "$\\lim sF(s)$")
    text = set_entry(text, "Bode", "Slope", "-20 dB/dec")
    text = set_entry(text, "Laplace", "Transform", "$F(s) = \\int f e^{-st}$\n\n#### Note\nlinear")
    assert parse(text) == {
        "Laplace": {"Transform": "$F(s) = \\int f e^{-st}$\n\n#### Note\nlinear", "Final value": "$\\lim sF(s)$"},
        "Bode": {"Slope": "-20 dB/dec"},
    }
    text = set_entry(text, "Bode", "Slope", "")
    assert text.startswith("# Cheatsheet\n") and "Bode" not in text
    with pytest.raises(CheatsheetError):
        set_entry(text, "Bode", "Slope", "")
    with pytest.raises(CheatsheetError):
        set_entry(text, "Laplace", "X", "## heading")


def test_context(store):
    ctx = asyncio.run(topic_context(store, "laplace", "German"))
    assert [b["type"] for b in ctx] == ["text", "image", "text", "text"]
    assert ctx[0]["text"] == (
        '<source id="laplace/1" task="Klausur 2023, Aufgabe 2b" tier="A" fit="clear">\n'
        '<passage file="exams/2023.md" blocks="5-7">\n# Aufgabe 2\n\nGegeben:\n\n'
        '![](sources/exams/2023/p2-img-0.jpeg)\n')
    assert base64.b64decode(ctx[1]["source"]["data"]) == b"jpeg"
    assert ctx[2]["text"] == (
        '\n\n</passage>\n<passage file="exams/2023.md" blocks="9">\nb) Teil b\n\n</passage>\n</source>\n\n'
        '<source id="laplace/2" task="Übung 1, Aufgabe 1" tier="B" fit="loose">\n'
        '<passage file="exercises/uebung1.md" blocks="2-3">\nÜbung 1\n\nLösung\n\n</passage>\n</source>\n\n')
    assert "cache_control" in ctx[2] and "cache_control" not in ctx[0]
    assert "<cheatsheet>\n(empty)\n</cheatsheet>" in ctx[-1]["text"]


def block(type, **kw):
    return SimpleNamespace(type=type, to_dict=lambda exclude_none: {"type": type, **kw}, **kw)


class FakeAI:
    """Replies with a cheatsheet update and a posed task, then with text."""

    def __init__(self, stop_reason="end_turn"):
        self.requests = []
        self.request_types = []
        self.tools = []
        self.stop_reason = stop_reason

    async def stream_chat(self, request_type, messages, tools):
        self.requests.append(messages)
        self.request_types.append(request_type)
        self.tools.append(tools)
        if len(self.requests) == 1:
            content = [
                block("tool_use", id="t1", name="update_cheatsheet",
                      input={"section": "Laplace", "heading": "Transform", "body": "$F(s)$"}),
                block("tool_use", id="t2", name="pose_task", input={"task": "Klausur 2023, Aufgabe 3", "tier": "B"}),
            ]
            msg = SimpleNamespace(stop_reason="tool_use", content=content)
        else:
            yield "text", "Draw it."
            msg = SimpleNamespace(stop_reason=self.stop_reason, content=[block("text", text="Draw it.")])
        yield "message", msg

    async def request_text(self, request_type, messages):
        self.requests.append(messages)
        return "# Progress\n"


def run_reply(store, ai, transcript, slug="laplace"):
    async def collect():
        return [e async for e in reply(store, ai, slug, "German", transcript)]
    return asyncio.run(collect())


def test_reply_runs_tools(store):
    ai = FakeAI()
    transcript = [{"role": "user", "content": "quiz me"}]
    events = run_reply(store, ai, transcript)

    assert [k for k, _ in events] == ["cheatsheet", "task", "text"]
    assert parse(store.read_text("cheatsheet.md")) == {"Laplace": {"Transform": "$F(s)$"}}
    assert [m["role"] for m in transcript] == ["user", "assistant", "user", "assistant"]
    results = transcript[2]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"] and "Do not grade" in results[1]["content"]
    first = ai.requests[1][0]["content"]
    assert first[0]["text"].startswith("<source") and first[-1] == {"type": "text", "text": "quiz me"}


def test_reply_failure_keeps_transcript(store):
    transcript = [{"role": "user", "content": "quiz me"}]
    with pytest.raises(TutorError):
        run_reply(store, FakeAI(stop_reason="refusal"), transcript)
    assert transcript == [{"role": "user", "content": "quiz me"}]


def test_finalize(store):
    transcript = [{"role": "user", "content": "quiz me"}]
    run_reply(store, FakeAI(), transcript)
    assert render_transcript(transcript) == (
        "Student: quiz me\n\n[Cheatsheet entry: Transform]\n\n"
        "[Task posed: Klausur 2023, Aufgabe 3, Tier B]\n\nTutor: Draw it."
    )
    ai = FakeAI()
    asyncio.run(finalize(store, ai, "laplace", "German", transcript))
    assert store.read_text("topics/laplace/progress.md") == "# Progress\n"
    assert "(none yet" in ai.requests[0][0]["content"]

    ai = FakeAI()
    asyncio.run(finalize(store, ai, "laplace", "German", []))
    assert ai.requests == []


def test_course_chat(store):
    store.write_text("topics/laplace/progress.md", "# Progress\ncan transform")
    ctx = course_context(store, "German")
    assert len(ctx) == 1 and "cache_control" in ctx[0]
    assert '<topic name="Laplace" priority="high">' in ctx[0]["text"]
    assert "- Übung 1, Aufgabe 1 (Tier B)" in ctx[0]["text"] and "can transform" in ctx[0]["text"]

    ai = FakeAI()
    transcript = [{"role": "user", "content": "what next?"}]
    run_reply(store, ai, transcript, slug=None)
    assert ai.request_types == ["planning", "planning"]
    assert [t["name"] for t in ai.tools[0]] == ["update_cheatsheet"]
