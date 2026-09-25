import asyncio
import io

import pytest
from pypdf import PdfReader, PdfWriter

from iknownothing.course_store import CourseStore, CourseStoreError
from iknownothing.ingestion.pipeline import by_unit, ingest
from iknownothing.ingestion.topics import page_numbers, validate_extraction


def pdf(pages: int) -> bytes:
    w = PdfWriter()
    for i in range(pages):
        w.add_blank_page(width=100 + i, height=100)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def topic(slug, file="exams/2023.pdf", pages="1-2", tier="A", priority="high"):
    return {"slug": slug, "name": slug.title(), "priority": priority, "description": "d",
            "sources": [{"task": "Aufgabe 1", "tier": tier, "pages": [{"file": file, "pages": pages}]}]}


@pytest.fixture
def store(tmp_path):
    return CourseStore(tmp_path, "alice", "control")


def test_store_confines_paths(store):
    with pytest.raises(CourseStoreError):
        store.path("../bob/x")
    with pytest.raises(CourseStoreError):
        CourseStore(store.root, "../bob", "x")


def test_pages_pdf(store):
    store.write_bytes("sources/exams/a.pdf", pdf(5))
    out = PdfReader(io.BytesIO(store.pages_pdf("sources/exams/a.pdf", [4, 2, 4])))
    assert [float(p.mediabox.width) for p in out.pages] == [101, 103]


def test_by_unit():
    files = [f"sources/exercises/{n}" for n in
             ("uebung10.pdf", "loesung02.pdf", "uebung02.pdf", "extra.pdf", "loesung10.pdf", "uebung1.pdf")]
    assert [f.rsplit("/", 1)[1] for f in by_unit(files)] == [
        "uebung1.pdf", "loesung02.pdf", "uebung02.pdf", "loesung10.pdf", "uebung10.pdf", "extra.pdf"]


def test_page_numbers():
    assert page_numbers("3") == [3]
    assert page_numbers("3 - 5") == [3, 4, 5]
    with pytest.raises(ValueError):
        page_numbers("p. 3")


def test_validate_extraction():
    counts = {"exams/2023.pdf": 4}
    assert validate_extraction({"language": "German", "topics": [topic("laplace")]}, counts) == []
    reply = {"language": "German", "topics": [
        topic("Bad Slug"), topic("x", file="exams/other.pdf"), topic("x", pages="3-9"), topic("y", pages="S. 3"),
    ]}
    assert len(validate_extraction(reply, counts)) == 5
    assert validate_extraction({"language": "German", "topics": []}, counts) == ["no topics"]


class FakeAI:
    def __init__(self):
        self.calls = []

    async def request_json(self, request_type, messages, schema):
        self.calls.append(request_type)
        titles = [b["title"] for b in messages[0]["content"] if b["type"] == "document"]
        assert titles == ["exams/2023.pdf", "exercises/uebung1.pdf", "exercises/loesung2.pdf"]
        assert "<past_exams>1</past_exams>" in messages[0]["content"][-1]["text"]
        if len(messages) == 1:
            return {"language": "German", "topics": [topic("laplace", pages="9")]}
        return {"language": "German", "topics": [
            topic("bode", file="exercises/uebung1.pdf", priority="low"),
            topic("laplace"),
            topic("sketch", tier="C", priority="medium"),
        ]}


def test_ingest_end_to_end_and_resume(store):
    store.write_text("notes.md", "notes")
    store.write_bytes("sources/exams/2023.pdf", pdf(4))
    store.write_bytes("sources/exercises/uebung1.pdf", pdf(2))
    store.write_bytes("sources/exercises/loesung2.pdf", pdf(2))

    ai = FakeAI()
    asyncio.run(ingest(store, ai, report=lambda s: None))

    assert ai.calls == ["topic_extraction", "topic_extraction"]
    listed = store.read_json("topics.json")
    assert [t["slug"] for t in listed] == ["laplace", "sketch", "bode"]
    assert listed[0]["sources"][0]["pages"] == [{"file": "exams/2023.pdf", "pages": "1-2"}]
    assert "## Sources\n\n- **Aufgabe 1** (Tier A): exams/2023.pdf p. 1-2" in store.read_text("topics/laplace/topic.md")
    sketch = store.read_text("topics/sketch/topic.md")
    assert "## Out of Reach" in sketch and "## Sources" not in sketch

    ai = FakeAI()
    asyncio.run(ingest(store, ai, report=lambda s: None))
    assert ai.calls == []
