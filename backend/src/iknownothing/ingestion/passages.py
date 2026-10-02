"""The passages of a topic's sources as message content, figures included."""

import asyncio
import base64
from pathlib import PurePosixPath

from iknownothing.course_store import CourseStore
from iknownothing.ingestion.conversion import FIGURE, blocks
from iknownothing.ingestion.topics import range_numbers


def _image(rel: str, data: bytes) -> dict:
    media_type = "image/png" if rel.endswith(".png") else "image/jpeg"
    return {"type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": base64.standard_b64encode(data).decode("ascii")}}


async def source_content(store: CourseStore, topic: dict) -> list[dict]:
    """Every source of the topic with its blocks as text and the figures in them as images, where they stand, each
    after its Markdown image line with the path from the course directory. Each passage names its PDF and pages."""
    converted: dict[str, list[str]] = {}
    content: list[dict] = []
    text: list[str] = []

    def flush() -> None:
        if text:
            content.append({"type": "text", "text": "".join(text)})
            text.clear()

    for s in topic["sources"]:
        text.append(f'<source id="{s["id"]}" task="{s["task"]}" tier="{s["tier"]}" fit="{s["fit"]}">\n')
        for r in s["blocks"]:
            rel = f"sources/{r['file']}"
            if rel not in converted:
                converted[rel] = blocks(await asyncio.to_thread(store.read_text, rel))
            pdf = f"sources/{r['file'].removesuffix('.md')}.pdf"
            text.append(f'<passage file="{r["file"]}" blocks="{r["blocks"]}" pdf="{pdf}" pages="{r["pages"]}">\n')
            for n in range_numbers(r["blocks"]):
                block, pos = converted[rel][n - 1], 0
                for m in FIGURE.finditer(block):
                    figure = str(PurePosixPath(rel).parent / m[1])
                    text.append(f"{block[pos:m.start()]}![]({figure})\n")
                    flush()
                    content.append(_image(figure, await asyncio.to_thread(store.read_bytes, figure)))
                    pos = m.end()
                text.append(f"{block[pos:]}\n\n")
            text.append("</passage>\n")
        text.append("</source>\n\n")
    flush()
    return content
