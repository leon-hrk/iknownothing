"""The only access path to data/<user>/<course>/."""

import asyncio
import io
import json
import os
import re
import shutil
import tempfile
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter

DOC_TYPES = ("exams", "exercises")

_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

_file_locks: defaultdict[Path, asyncio.Lock] = defaultdict(asyncio.Lock)


class CourseStoreError(Exception):
    pass


class CourseStore:
    def __init__(self, data_dir: Path, user: str, course: str):
        for name in (user, course):
            if not _NAME.match(name):
                raise CourseStoreError(f"invalid name: {name!r}")
        self.root = (data_dir / user / course).resolve()
        self.user = user
        self.course = course

    def path(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if not p.is_relative_to(self.root):
            raise CourseStoreError(f"path outside course: {rel!r}")
        return p

    def exists(self, rel: str = ".") -> bool:
        return self.path(rel).exists()

    def read_bytes(self, rel: str) -> bytes:
        return self.path(rel).read_bytes()

    def read_text(self, rel: str) -> str:
        return self.path(rel).read_text(encoding="utf-8")

    def read_json(self, rel: str) -> Any:
        return json.loads(self.read_text(rel))

    def write_bytes(self, rel: str, data: bytes) -> None:
        """Atomic: a file that exists is complete."""
        target = self.path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, target)
        except BaseException:
            os.unlink(tmp)
            raise

    def write_text(self, rel: str, text: str) -> None:
        self.write_bytes(rel, text.encode("utf-8"))

    def write_json(self, rel: str, data: Any) -> None:
        self.write_text(rel, json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    async def update_text(self, rel: str, change: Callable[[str], str]) -> str:
        """Applies `change` to the file's text (empty if missing) and writes the result; serialized per file."""
        target = self.path(rel)
        async with _file_locks[target]:
            old = target.read_text(encoding="utf-8") if target.exists() else ""
            new = change(old)
            await asyncio.to_thread(self.write_text, rel, new)
            return new

    def delete(self, rel: str) -> None:
        self.path(rel).unlink(missing_ok=True)

    def sources(self, doc_type: str) -> list[str]:
        """Source PDFs of one document type, in file name order."""
        if doc_type not in DOC_TYPES:
            raise CourseStoreError(f"unknown document type: {doc_type!r}")
        d = self.path(f"sources/{doc_type}")
        if not d.is_dir():
            return []
        return [f"sources/{doc_type}/{p.name}" for p in sorted(d.glob("*.pdf"))]

    def page_count(self, rel: str) -> int:
        return len(PdfReader(self.path(rel)).pages)

    def pages_pdf(self, rel: str, pages: list[int]) -> bytes:
        """A PDF of the given 1-based pages of a source, each once, in page order."""
        reader = PdfReader(self.path(rel))
        writer = PdfWriter()
        for n in sorted(set(pages)):
            writer.add_page(reader.pages[n - 1])
        buf = io.BytesIO()
        writer.write(buf)
        return buf.getvalue()

    def files(self) -> list[str]:
        """All files of the course, relative to its directory."""
        return [p.relative_to(self.root).as_posix() for p in sorted(self.root.rglob("*"))
                if p.is_file() and not p.name.startswith(".")]

    def remove(self) -> None:
        shutil.rmtree(self.root)
