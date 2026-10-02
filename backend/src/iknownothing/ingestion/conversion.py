"""Conversion: every source PDF to Markdown, with the figures OCR cuts out as images next to it."""

import asyncio
import re
from pathlib import PurePosixPath

from iknownothing.course_store import CourseStore
from iknownothing.ocr_client import OCRClient

PAGE_MARKER = "<!-- page {} -->"
PARALLEL = 4

PAGE = re.compile(r"^<!-- page (\d+) -->$")
FIGURE = re.compile(r"!\[[^\]]*\]\(([^)]*)\)")

_CODE = re.compile(r"(```[\s\S]*?(?:```|$)|`[^`\n]*`)")
_INLINE_DOLLAR_MATH = re.compile(r"(?<![\\$])\$(?!\$)([^$\n]+?)(?<![\\$])\$(?!\$)")


def markdown_path(source: str) -> str:
    return source.removesuffix(".pdf") + ".md"


def blocks(markdown: str) -> list[str]:
    """The blocks of a conversion: its paragraphs, split at blank lines outside code and `$$` math, each page
    marker a block of its own. Block `n` is `blocks(...)[n - 1]`."""
    out: list[str] = []
    current: list[str] = []
    fenced = False

    def end() -> None:
        if current:
            out.append("\n".join(current))
            current.clear()

    for line in markdown.splitlines():
        if not fenced and PAGE.match(line.strip()):
            end()
            out.append(line.strip())
            continue
        if line.startswith("```") or line.strip() == "$$":
            fenced = not fenced
        if line.strip() or fenced:
            current.append(line)
        else:
            end()
    end()
    return out


def page_of(blocks: list[str], n: int) -> int:
    """The page block `n` stands on."""
    return max((int(m[1]) for b in blocks[:n] if (m := PAGE.match(b))), default=1)


def inline_math(markdown: str) -> str:
    """Rewrites inline math from `$…$` to `\\(…\\)`, outside of code."""
    parts = _CODE.split(markdown)
    return "".join(part if i % 2 else _INLINE_DOLLAR_MATH.sub(r"\\(\1\\)", part) for i, part in enumerate(parts))


async def convert(store: CourseStore, ocr: OCRClient, sources: list[str]) -> None:
    """Converts the sources that have no Markdown yet."""
    limit = asyncio.Semaphore(PARALLEL)

    async def one(source: str) -> None:
        async with limit:
            await _convert(store, ocr, source)

    await asyncio.gather(*(one(s) for s in sources if not store.exists(markdown_path(s))))


async def _convert(store: CourseStore, ocr: OCRClient, source: str) -> None:
    pages = await ocr.convert(await asyncio.to_thread(store.read_bytes, source))
    stem = source.removesuffix(".pdf")
    name = PurePosixPath(stem).name
    parts = []
    for n, page in enumerate(pages, 1):
        markdown = inline_math(page["markdown"])
        for img in page["images"]:
            figure = f"p{n}-{img['id']}"
            await asyncio.to_thread(store.write_bytes, f"{stem}/{figure}", img["data"])
            markdown = markdown.replace(f"![{img['id']}]({img['id']})", f"![{figure}]({name}/{figure})")
        parts.append(f"{PAGE_MARKER.format(n)}\n\n{markdown.strip()}")
    # written last: a Markdown file that exists belongs to a complete conversion
    await asyncio.to_thread(store.write_text, markdown_path(source), "\n\n".join(parts) + "\n")
