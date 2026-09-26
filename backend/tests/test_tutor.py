import asyncio
import base64
import io
from types import SimpleNamespace

import pytest
from pypdf import PdfReader, PdfWriter

from iknownothing.course_store import CourseStore
from iknownothing.tutor.chat import TutorError, context, reply
from iknownothing.tutor.cheatsheet import CheatsheetError, parse, set_entry
from iknownothing.tutor.finalization import finalize, render_transcript


def pdf(pages: int) -> bytes:
    w = PdfWriter()
    for i in range(pages):
        w.add_blank_page(width=100 + i, height=100)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


@pytest.fixture
def store(tmp_path):
    s = CourseStore(tmp_path, "alice", "control")
    s.write_text("notes.md", "notes")
    s.write_bytes("sources/exams/2023.pdf", pdf(6))
    s.write_bytes("sources/exercises/uebung1.pdf", pdf(3))
    s.write_text("topics/laplace/topic.md", "# Laplace")
    s.write_json("topics.json", [{
        "slug": "laplace", "name": "Laplace", "priority": "high", "dir": "topics/laplace",
        "sources": [
            {"task": "Übung 1, Aufgabe 1", "tier": "A", "pages": [{"file": "exercises/uebung1.pdf", "pages": "2"}]},
            {"task": "Klausur 2023, Aufgabe 2", "tier": "A", "pages": [{"file": "exams/2023.pdf", "pages": "4-5"}]},
            {"task": "Klausur 2023, Aufgabe 3", "tier": "B", "pages": [{"file": "exams/2023.pdf", "pages": "1-2"}]},
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
    ctx = asyncio.run(context(store, "laplace", "German"))
    docs = [b for b in ctx if b["type"] == "document"]
    assert [d["title"] for d in docs] == ["exams/2023.pdf, pages 1-2, 4-5", "exercises/uebung1.pdf, pages 2"]
    assert "cache_control" in docs[-1] and "cache_control" not in docs[0]
    assert len(PdfReader(io.BytesIO(base64.b64decode(docs[0]["source"]["data"]))).pages) == 4
    assert "<cheatsheet>\n(empty)\n</cheatsheet>" in ctx[-1]["text"]


def block(type, **kw):
    return SimpleNamespace(type=type, to_dict=lambda exclude_none: {"type": type, **kw}, **kw)


class FakeAI:
    """Replies with a cheatsheet update and a posed task, then with text."""

    def __init__(self, stop_reason="end_turn"):
        self.requests = []
        self.stop_reason = stop_reason

    async def stream_chat(self, request_type, messages, tools):
        self.requests.append(messages)
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


def run_reply(store, ai, transcript):
    async def collect():
        return [e async for e in reply(store, ai, "laplace", "German", transcript)]
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
    assert first[0]["type"] == "document" and first[-1] == {"type": "text", "text": "quiz me"}


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
