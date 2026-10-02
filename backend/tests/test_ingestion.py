import asyncio

import pytest

from iknownothing.course_store import CourseStore, CourseStoreError
from iknownothing.ingestion.conversion import blocks, inline_math, page_of
from iknownothing.ingestion.pipeline import by_unit, ingest
from iknownothing.ingestion.topics import priority, range_numbers, validate_grouping, validate_unit


def new(slug, raised=False):
    return {"slug": slug, "name": slug.title(), "description": "d", "raised_by_notes": raised}


def source(topic, task, file, ranges, tier="A", fit=None):
    s = {"topic": topic, "task": task, "tier": tier, "blocks": [{"file": file, "blocks": ranges}]}
    return {**s, "fit": fit} if fit else s


@pytest.fixture
def store(tmp_path):
    return CourseStore(tmp_path, "alice", "control")


def test_store_confines_paths(store):
    with pytest.raises(CourseStoreError):
        store.path("../bob/x")
    with pytest.raises(CourseStoreError):
        CourseStore(store.root, "../bob", "x")


def test_by_unit():
    files = [f"sources/exercises/{n}" for n in
             ("uebung10.pdf", "loesung02.pdf", "uebung02.pdf", "extra.pdf", "loesung10.pdf", "uebung1.pdf")]
    assert [f.rsplit("/", 1)[1] for f in by_unit(files)] == [
        "uebung1.pdf", "loesung02.pdf", "uebung02.pdf", "loesung10.pdf", "uebung10.pdf", "extra.pdf"]


def test_range_numbers():
    assert range_numbers("3") == [3]
    assert range_numbers("3 - 5") == [3, 4, 5]
    with pytest.raises(ValueError):
        range_numbers("p. 3")


def test_blocks():
    markdown = ("<!-- page 1 -->\n\n# A\n\nline one\nline two\n\n```\ncode\n\nmore\n```\n\n"
                "$$\nx\n\ny\n$$\n<!-- page 2 -->\n![p2-img-0.jpeg](a/p2-img-0.jpeg)\n")
    bs = blocks(markdown)
    assert bs == ["<!-- page 1 -->", "# A", "line one\nline two", "```\ncode\n\nmore\n```", "$$\nx\n\ny\n$$",
                  "<!-- page 2 -->", "![p2-img-0.jpeg](a/p2-img-0.jpeg)"]
    assert [page_of(bs, n) for n in (2, 5, 6, 7)] == [1, 1, 2, 2]


def test_validate_unit():
    counts = {"exams/2023.md": 6}
    ok = {"language": "German", "topics": [new("laplace")], "sources": [source("laplace", "A1", "exams/2023.md", "2-4")]}
    assert validate_unit(ok, set(), counts) == []
    assert validate_unit({"language": "German", "topics": [], "sources": [source("laplace", "A1", "exams/2023.md", "2")]},
                         {"laplace"}, counts) == []
    reply = {"language": "German", "topics": [new("Bad Slug"), new("lonely"), new("tips", raised=True)], "sources": [
        source("bode", "A1", "exams/2023.md", "2"), source("tips", "A2", "exams/other.md", "2"),
        source("tips", "A3", "exams/2023.md", "3-9"), source("tips", "A4", "exams/2023.md", "S. 3"),
    ]}
    assert len(validate_unit(reply, set(), counts)) == 7


def test_validate_grouping():
    assert validate_grouping({"topics": [new("regs")], "tasks": [{"index": 2, "topic": "regs", "fit": "clear"}]},
                             {"laplace"}, 2) == []
    reply = {"topics": [new("laplace"), new("empty")], "tasks": [
        {"index": 3, "topic": "laplace", "fit": "clear"}, {"index": 1, "topic": "nope", "fit": "loose"},
        {"index": 1, "topic": "other-tasks", "fit": "clear"}]}
    assert len(validate_grouping(reply, {"laplace"}, 2)) == 5


def test_priority():
    exams, units = ["exams/a", "exams/b", "exams/c", "exams/d"], ["exams/a", "exams/b", "exams/c", "exams/d", "ex/1"]
    assert priority({"exams/a", "exams/b", "exams/c"}, False, exams, units) == "high"
    assert priority({"exams/a", "ex/1"}, False, exams, units) == "medium"
    assert priority({"ex/1"}, False, exams, units) == "low"
    assert priority(set(), True, exams, units) == "high"
    assert priority({"ex/1"}, False, [], ["ex/1", "ex/2"]) == "medium"


class FakeAI:
    """Replies to each unit, by its first document; the first reply to the first exam is invalid."""

    REPLIES = {
        "exams/2023.md": {"topics": [new("laplace"), new("sketch")], "sources": [
            source("laplace", "Klausur 2023, Aufgabe 1", "exams/2023.md", "2-4"),
            source("sketch", "Klausur 2023, Aufgabe 2", "exams/2023.md", "3-6", tier="C")]},
        "exams/2024.md": {"topics": [new("exam-tips", raised=True)], "sources": [
            source("laplace", "Klausur 2024, Aufgabe 1", "exams/2024.md", "2-4")]},
        "exercises/loesung1.md": {"sources": [
            {**source("laplace", "Übung 1, Aufgabe 1", "", "", fit="loose"), "blocks": [
                {"file": "exercises/uebung1.md", "blocks": "2"}, {"file": "exercises/loesung1.md", "blocks": "2-3"}]},
            source("other-tasks", "Übung 1, Aufgabe 2", "exercises/uebung1.md", "3", fit="clear")]},
        "exercises/uebung2.md": {"sources": [
            source("sketch", "Übung 2, Aufgabe 1", "exercises/uebung2.md", "2", fit="clear"),
            source("other-tasks", "Übung 2, Aufgabe 2", "exercises/uebung2.md", "3", fit="clear")]},
    }

    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on

    async def request_json(self, request_type, messages, schema):
        texts = [b["text"] for b in messages[0]["content"] if b["type"] == "text"]
        if request_type == "solution_writing":
            topic = texts[0].split('"')[1].split("/")[0]
            self.calls.append((request_type, topic))
            assert texts[-1].startswith("<language>German</language>\n\n<topic>\n# ")
            if topic == "laplace":
                return {"solutions": [{"task": "Klausur 2023, Aufgabe 1", "solution": "\\(x = 1\\)",
                                       "values_from_figure": True}]}
            return {"solutions": []}
        if request_type == "task_grouping":
            self.calls.append((request_type, None))
            assert texts[0].startswith('<tasks>\n<task index="1" label="Übung 1, Aufgabe 2" tier="A">\n'
                                       '<passage file="exercises/uebung1.md">\n')
            assert '<task index="2" label="Übung 2, Aufgabe 2"' in texts[0] and "other-tasks" not in texts[-1]
            return {"topics": [new("registers")], "tasks": [{"index": 1, "topic": "registers", "fit": "clear"}]}
        first = texts[0].split('"')[1]
        self.calls.append((request_type, first))
        if first == self.fail_on:
            raise RuntimeError("request failed")
        if first == "exams/2023.md":
            assert texts[0] == ('<document title="exams/2023.md">\n[1] <!-- page 1 -->\n\n[2] # Aufgabe 1\n\n'
                                '[3] Gegeben \\(x^2\\):\n\n[4] [figure]\n\n[5] <!-- page 2 -->\n\n[6] Text\n</document>')
            assert "<topics>\n(none yet)\n</topics>" in texts[-1]
            if len(messages) == 1:
                return {"language": "German", "topics": [new("laplace")],
                        "sources": [source("laplace", "Klausur 2023, Aufgabe 1", "exams/2023.md", "9")]}
        if first == "exams/2024.md":
            assert '<topic slug="laplace" name="Laplace">\nd\n- Klausur 2023, Aufgabe 1 (Tier A)\n</topic>' in texts[-1]
        if first == "exercises/loesung1.md":
            assert texts[1].startswith('<document title="exercises/uebung1.md">')
            assert '<topic slug="exam-tips"' in texts[-1]
        return {"language": "German", **self.REPLIES[first]}


class FakeOCR:
    def __init__(self):
        self.calls = 0

    async def convert(self, pdf_bytes):
        self.calls += 1
        return [{"markdown": "# Aufgabe 1\n\nGegeben $x^2$:\n\n![img-0.jpeg](img-0.jpeg)",
                 "images": [{"id": "img-0.jpeg", "data": b"jpeg"}]},
                {"markdown": "Text", "images": []}]


def test_inline_math():
    assert inline_math("Kosten $c_+ = 1$ und $$E = mc^2$$") == "Kosten \\(c_+ = 1\\) und $$E = mc^2$$"
    assert inline_math("`echo $a$` kostet \\$5 bis \\$10") == "`echo $a$` kostet \\$5 bis \\$10"
    assert inline_math("```\n$t0$\n```") == "```\n$t0$\n```"


def test_ingest_unit_by_unit_and_resume(store):
    store.write_text("notes.md", "notes")
    for f in ("exams/2023", "exams/2024", "exercises/uebung1", "exercises/loesung1", "exercises/uebung2"):
        store.write_bytes(f"sources/{f}.pdf", b"%PDF")

    ai, ocr = FakeAI(fail_on="exercises/uebung2.md"), FakeOCR()
    with pytest.raises(RuntimeError):
        asyncio.run(ingest(store, ai, ocr, report=lambda s: None))
    assert ocr.calls == 5
    assert store.read_text("sources/exams/2023.md") == (
        "<!-- page 1 -->\n\n# Aufgabe 1\n\nGegeben \\(x^2\\):\n\n![p1-img-0.jpeg](2023/p1-img-0.jpeg)\n\n"
        "<!-- page 2 -->\n\nText\n")
    assert store.read_bytes("sources/exams/2023/p1-img-0.jpeg") == b"jpeg"
    assert ai.calls[:3] == [("topic_extraction", "exams/2023.md"), ("topic_extraction", "exams/2023.md"),
                            ("topic_extraction", "exams/2024.md")]
    assert sorted(ai.calls[3:]) == [("task_assignment", "exercises/loesung1.md"),
                                    ("task_assignment", "exercises/uebung2.md")]
    assert not store.exists("topics.json")

    ai, ocr = FakeAI(), FakeOCR()
    asyncio.run(ingest(store, ai, ocr, report=lambda s: None))
    assert ai.calls[:2] == [("task_assignment", "exercises/uebung2.md"), ("task_grouping", None)] and ocr.calls == 0
    assert sorted(ai.calls[2:]) == [("solution_writing", t) for t in ("laplace", "other-tasks", "registers", "sketch")]
    assert store.read_text("topics/laplace/solutions.md").endswith(
        "## Klausur 2023, Aufgabe 1\n\n> **Values read from a figure.** They may be misread; check them against the "
        "figure.\n\n\\(x = 1\\)\n")
    assert not store.exists("topics/sketch/solutions.md")

    listed = store.read_json("topics.json")
    assert [(t["slug"], t["priority"]) for t in listed] == [
        ("laplace", "high"), ("exam-tips", "high"), ("sketch", "medium"), ("registers", "low"), ("other-tasks", "low")]
    assert [s["task"] for s in listed[3]["sources"]] == ["Übung 1, Aufgabe 2"]
    assert [s["task"] for s in listed[4]["sources"]] == ["Übung 2, Aufgabe 2"]
    assert listed[0]["sources"] == [
        {"id": "laplace/1", "task": "Klausur 2023, Aufgabe 1", "tier": "A", "fit": "clear",
         "blocks": [{"file": "exams/2023.md", "blocks": "2-4", "pages": "1"}]},
        {"id": "laplace/2", "task": "Klausur 2024, Aufgabe 1", "tier": "A", "fit": "clear",
         "blocks": [{"file": "exams/2024.md", "blocks": "2-4", "pages": "1"}]},
        {"id": "laplace/3", "task": "Übung 1, Aufgabe 1", "tier": "A", "fit": "loose",
         "blocks": [{"file": "exercises/uebung1.md", "blocks": "2", "pages": "1"},
                    {"file": "exercises/loesung1.md", "blocks": "2-3", "pages": "1"}]}]
    laplace = store.read_text("topics/laplace/topic.md")
    assert "**Priority:** high - asked in 2 of 2 past exams\n\nd\n" in laplace
    assert "- **Klausur 2023, Aufgabe 1** (Tier A): exams/2023.md p. 1" in laplace
    assert "- **Übung 1, Aufgabe 1** (Tier A, loose fit): exercises/uebung1.md p. 1" in laplace
    assert "raised by the notes" in store.read_text("topics/exam-tips/topic.md")
    sketch = store.read_text("topics/sketch/topic.md")
    assert "## Out of Reach\n\n- **Klausur 2023, Aufgabe 2** (Tier C): exams/2023.md p. 1-2" in sketch
    assert "## Sources\n\n- **Übung 2, Aufgabe 1** (Tier A): exercises/uebung2.md p. 1" in sketch

    ai = FakeAI()
    asyncio.run(ingest(store, ai, FakeOCR(), report=lambda s: None))
    assert ai.calls == []
