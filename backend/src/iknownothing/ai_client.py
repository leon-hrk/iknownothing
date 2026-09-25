"""The only caller of the Anthropic API."""

import json
import logging
from collections import defaultdict
from importlib import resources
from typing import Any

import anthropic

from iknownothing.config import Settings

log = logging.getLogger(__name__)

TIERS = {
    "topic_extraction": "large",
}

_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AIError(Exception):
    pass


def load_prompt(name: str) -> str:
    return resources.files("iknownothing.prompts").joinpath(f"{name}.md").read_text(encoding="utf-8")


class AIClient:
    def __init__(self, settings: Settings, user: str, course: str):
        self._client = anthropic.AsyncAnthropic(max_retries=5)
        self._models = {"large": settings.model_large, "small": settings.model_small}
        self._user = user
        self._course = course
        self.usage: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    async def request_json(self, request_type: str, messages: list[dict], schema: dict) -> Any:
        """Sends one request whose reply is JSON matching `schema`; returns the parsed reply."""
        model = self._models[TIERS[request_type]]
        async with self._client.beta.messages.stream(
            model=model,
            max_tokens=64000,
            system=load_prompt(request_type),
            messages=messages,
            thinking={"type": "adaptive"},
            output_config={"format": {"type": "json_schema", "schema": schema}},
            betas=[_FALLBACK_BETA],
            fallbacks="default",
        ) as stream:
            msg = await stream.get_final_message()

        self._record_usage(request_type, msg)

        if msg.stop_reason == "refusal":
            raise AIError(f"{request_type}: request refused by {msg.model}")
        if msg.stop_reason == "max_tokens":
            raise AIError(f"{request_type}: reply exceeded max_tokens")

        # After a server-side fallback, only the text following the last
        # fallback block belongs to the model that answered.
        blocks = list(msg.content)
        last_fallback = max((i for i, b in enumerate(blocks) if b.type == "fallback"), default=-1)
        text = "".join(b.text for b in blocks[last_fallback + 1 :] if b.type == "text")
        return json.loads(text)

    def _record_usage(self, request_type: str, msg: Any) -> None:
        u = msg.usage
        cache_read = u.cache_read_input_tokens or 0
        cache_write = u.cache_creation_input_tokens or 0
        log.info(
            "usage user=%s course=%s type=%s model=%s input=%d output=%d cache_read=%d cache_write=%d",
            self._user, self._course, request_type, msg.model,
            u.input_tokens, u.output_tokens, cache_read, cache_write,
        )
        totals = self.usage[msg.model]
        totals["requests"] += 1
        totals["input"] += u.input_tokens
        totals["output"] += u.output_tokens
        totals["cache_read"] += cache_read
        totals["cache_write"] += cache_write
