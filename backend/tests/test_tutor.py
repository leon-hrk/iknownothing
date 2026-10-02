import asyncio
import base64
from types import SimpleNamespace

import pytest

from iknownothing.course_store import CourseStore
from iknownothing.tutor.chat import CONTINUE, TutorError, course_context, progress, reply, step_start, topic_context
from iknownothing.tutor.cheatsheet import CheatsheetError, parse, set_entry


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
        '<passage file="exams/2023.md" blocks="5-7" pdf="sources/exams/2023.pdf" pages="2">\n# Aufgabe 2\n\nGegeben:\n\n'
        '![](sources/exams/2023/p2-img-0.jpeg)\n')
    assert base64.b64decode(ctx[1]["source"]["data"]) == b"jpeg"
    assert ctx[2]["text"] == (
        '\n\n</passage>\n<passage file="exams/2023.md" blocks="9" pdf="sources/exams/2023.pdf" pages="2">\nb) Teil b\n\n</passage>\n</source>\n\n'
        '<source id="laplace/2" task="Übung 1, Aufgabe 1" tier="B" fit="loose">\n'
        '<passage file="exercises/uebung1.md" blocks="2-3" pdf="sources/exercises/uebung1.pdf" pages="1">\nÜbung 1\n\nLösung\n\n</passage>\n</source>\n\n')
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


class StepAI:
    """Completes the step, then poses the next task."""

    def __init__(self):
        self.requests = []

    async def stream_chat(self, request_type, messages, tools):
        self.requests.append(messages)
        if len(self.requests) == 1:
            content = [block("text", text="Richtig."), block("tool_use", id="s1", name="complete_step",
                                                               input={"step": "Klausur 2023, Aufgabe 2b", "note": "Vorzeichen vergessen."})]
            msg = SimpleNamespace(stop_reason="tool_use", content=content)
        else:
            msg = SimpleNamespace(stop_reason="end_turn", content=[block("text", text="Next task.")])
        yield "message", msg


def test_completed_step_is_recorded_and_left_out(store):
    ai = StepAI()

    async def collect(transcript):
        return [e async for e in reply(store, ai, "laplace", "German", transcript)]

    transcript = [{"role": "user", "content": "teach me"}]
    events = asyncio.run(collect(transcript))

    assert ("step", {"step": "Klausur 2023, Aufgabe 2b", "note": "Vorzeichen vergessen."}) in events
    assert store.read_json("topics/laplace/progress.json") == {"introduction": False, "tasks": {
        "Klausur 2023, Aufgabe 2b": {"done": True, "note": "Vorzeichen vergessen."},
        "Übung 1, Aufgabe 1": {"done": False}}}
    assert step_start(transcript) == 3
    second = ai.requests[1]
    assert len(second) == 1 and second[0]["content"][-1] == {"type": "text", "text": CONTINUE}
    assert '"note": "Vorzeichen vergessen."' in second[0]["content"][-2]["text"]

    transcript.append({"role": "user", "content": "my answer"})
    ai.requests.clear()
    asyncio.run(collect(transcript))
    assert [m["role"] for m in ai.requests[0]] == ["user", "assistant", "user"]
    assert ai.requests[0][1]["content"] == [{"type": "text", "text": "Next task."}]


def test_progress_and_unknown_step(store):
    topic = store.read_json("topics.json")[0]
    assert progress(store, topic) == {"introduction": False, "tasks": {
        "Klausur 2023, Aufgabe 2b": {"done": False}, "Übung 1, Aufgabe 1": {"done": False}}}

    class UnknownStepAI(StepAI):
        async def stream_chat(self, request_type, messages, tools):
            self.requests.append(messages)
            if len(self.requests) == 1:
                content = [block("tool_use", id="s1", name="complete_step", input={"step": "Aufgabe 9", "note": ""})]
                msg = SimpleNamespace(stop_reason="tool_use", content=content)
            else:
                msg = SimpleNamespace(stop_reason="end_turn", content=[block("text", text="Next task.")])
            yield "message", msg

    transcript = [{"role": "user", "content": "teach me"}]
    events = run_reply(store, UnknownStepAI(), transcript)
    assert not any(k == "step" for k, _ in events)
    assert transcript[2]["content"][0]["is_error"] and "Klausur 2023, Aufgabe 2b" in transcript[2]["content"][0]["content"]
    assert step_start(transcript) == 0 and not store.exists("topics/laplace/progress.json")


def test_reply_failure_keeps_transcript(store):
    transcript = [{"role": "user", "content": "quiz me"}]
    with pytest.raises(TutorError):
        run_reply(store, FakeAI(stop_reason="refusal"), transcript)
    assert transcript == [{"role": "user", "content": "quiz me"}]


def test_course_chat(store):
    store.write_json("topics/laplace/progress.json", {"introduction": True, "tasks": {
        "Klausur 2023, Aufgabe 2b": {"done": True, "note": "can transform"}}})
    ctx = course_context(store, "German")
    assert len(ctx) == 1 and "cache_control" in ctx[0]
    assert '<topic name="Laplace" priority="high">' in ctx[0]["text"]
    assert "- Übung 1, Aufgabe 1 (Tier B)" in ctx[0]["text"] and "can transform" in ctx[0]["text"]

    ai = FakeAI()
    transcript = [{"role": "user", "content": "what next?"}]
    run_reply(store, ai, transcript, slug=None)
    assert ai.request_types == ["planning", "planning"]
    assert [t["name"] for t in ai.tools[0]] == ["update_cheatsheet"]
