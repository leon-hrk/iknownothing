import pytest

from iknownothing import courses
from iknownothing.course_store import CourseStore


def material(tmp_path):
    src = tmp_path / "in" / "control"
    (src / "exams").mkdir(parents=True)
    (src / "notes.md").write_text("notes")
    (src / "exams" / "2023.pdf").write_bytes(b"%PDF")
    return src


def test_add_from_dir(tmp_path):
    src = material(tmp_path)
    store = CourseStore(tmp_path / "data", "bob", "control")
    courses.add_from_dir(store, src)
    assert store.files() == ["notes.md", "sources/exams/2023.pdf"]
    assert courses.status(store) == "not ingested"
    with pytest.raises(courses.CourseError, match="exists"):
        courses.add_from_dir(store, src)


@pytest.mark.parametrize("change, error", [
    (lambda src: (src / "notes.md").unlink(), "missing"),
    (lambda src: (src / "exams" / "2023.pdf").rename(src / "exams" / "2023.PDF"), "not a .pdf"),
    (lambda src: (src / "exams").rename(src / "exam"), "unexpected"),
    (lambda src: (src / "exams" / "2023.pdf").unlink(), "no PDFs"),
])
def test_add_from_dir_checks(tmp_path, change, error):
    src = material(tmp_path)
    change(src)
    store = CourseStore(tmp_path / "data", "bob", "control")
    with pytest.raises(courses.CourseError, match=error):
        courses.add_from_dir(store, src)
    assert not store.exists()


def test_update_from_dir(tmp_path):
    src = material(tmp_path)
    store = CourseStore(tmp_path / "data", "bob", "control")
    courses.add_from_dir(store, src)
    with pytest.raises(courses.CourseError, match="not an ingested course"):
        courses.update_from_dir(store, src)
    store.write_json("topics.json", [])
    (src / "exercises").mkdir()
    (src / "exercises" / "uebung1.pdf").write_bytes(b"%PDF-1")
    (src / "notes.md").write_text("more notes")
    assert courses.update_from_dir(store, src) == ["sources/exercises/uebung1.pdf"]
    assert store.read_text("notes.md") == "more notes" and store.read_bytes("sources/exercises/uebung1.pdf") == b"%PDF-1"
    assert courses.update_from_dir(store, src) == []
    (src / "exams" / "2023.pdf").write_bytes(b"%PDF-changed")
    with pytest.raises(courses.CourseError, match="changed"):
        courses.update_from_dir(store, src)
