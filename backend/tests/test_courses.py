import pytest

from iknownothing import courses
from iknownothing.course_store import CourseStore
from test_tutor import pdf, store  # noqa: F401


def material(tmp_path):
    src = tmp_path / "in" / "control"
    (src / "exams").mkdir(parents=True)
    (src / "notes.md").write_text("notes")
    (src / "exams" / "2023.pdf").write_bytes(pdf(2))
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


def test_copy_from(store, tmp_path):  # noqa: F811
    store.write_text("cheatsheet.md", "# Cheatsheet")
    store.write_text("topics/laplace/progress.md", "# Progress")
    copy = CourseStore(store.root.parent.parent, "bob", "control")
    courses.copy_from(copy, store)
    assert copy.files() == [f for f in store.files() if not f.endswith(courses.STUDENT_STATE)]
    assert courses.status(copy) == "ready"
    with pytest.raises(courses.CourseError, match="exists"):
        courses.copy_from(copy, store)
