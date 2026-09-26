"""Approximate cost of a request from its token usage, at Anthropic's list prices."""

import logging

log = logging.getLogger(__name__)

# USD per million tokens: input, output, cache read. Cache writes cost 1.25 times the input price.
PRICES = {
    "claude-fable-5-1": (10.0, 50.0, 0.25),
    "claude-fable-5": (10.0, 50.0, 1.0),
    "claude-opus-5-5": (4.0, 20.0, 0.2),
    "claude-opus-5": (5.0, 25.0, 0.5),
    "claude-opus-4": (5.0, 25.0, 0.5),
    "claude-sonnet-5": (2.0, 10.0, 0.2),
    "claude-sonnet-4": (3.0, 15.0, 0.3),
    "claude-haiku-4-5": (1.0, 5.0, 0.1),
}

EUR_PER_USD = 0.86


def eur(model: str, input: int, output: int, cache_read: int, cache_write: int) -> float:
    """The cost in euros; 0 for a model without a price."""
    key = max((k for k in PRICES if model.startswith(k)), key=len, default=None)
    if key is None:
        log.warning("no price for model %s", model)
        return 0.0
    price_in, price_out, price_read = PRICES[key]
    usd = (input * price_in + cache_write * price_in * 1.25 + cache_read * price_read + output * price_out) / 1e6
    return usd * EUR_PER_USD
