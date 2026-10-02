"""The only caller of the Mistral OCR API."""

import asyncio
import base64
import logging

import httpx

from iknownothing.config import Settings

log = logging.getLogger(__name__)

URL = "https://api.mistral.ai/v1/ocr"
MODEL = "mistral-ocr-latest"
MAX_ATTEMPTS = 6


class OCRError(Exception):
    pass


class OCRClient:
    def __init__(self, settings: Settings, user: str, course: str):
        self._key = settings.mistral_api_key
        self._http = httpx.AsyncClient(timeout=600)
        self._user = user
        self._course = course
        self.pages = 0

    async def close(self) -> None:
        await self._http.aclose()

    async def convert(self, pdf: bytes) -> list[dict]:
        """The PDF's pages in order, each as `{"markdown": str, "images": [{"id": str, "data": bytes}]}`;
        the Markdown references an image as `![<id>](<id>)`."""
        if not self._key:
            raise OCRError("MISTRAL_API_KEY is not set")
        body = {
            "model": MODEL,
            "document": {"type": "document_url",
                         "document_url": "data:application/pdf;base64," + base64.standard_b64encode(pdf).decode("ascii")},
            "include_image_base64": True,
        }
        for attempt in range(MAX_ATTEMPTS):
            try:
                r = await self._http.post(URL, json=body, headers={"Authorization": f"Bearer {self._key}"})
            except httpx.TransportError as e:
                error = repr(e)
            else:
                if r.is_success:
                    break
                error = f"{r.status_code} {r.text}"
                if r.status_code != 429 and r.status_code < 500:
                    raise OCRError(f"OCR request failed: {error}")
            await asyncio.sleep(2 ** attempt)
        else:
            raise OCRError(f"OCR request failed after {MAX_ATTEMPTS} attempts: {error}")

        reply = r.json()
        pages = reply["usage_info"]["pages_processed"]
        self.pages += pages
        log.info("usage user=%s course=%s type=ocr model=%s pages=%d", self._user, self._course, reply["model"], pages)
        return [
            {"markdown": p["markdown"],
             "images": [{"id": img["id"], "data": base64.b64decode(img["image_base64"].partition(";base64,")[2])}
                        for img in p["images"]]}
            for p in sorted(reply["pages"], key=lambda p: p["index"])
        ]
