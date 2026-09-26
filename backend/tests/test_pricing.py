import pytest

from iknownothing import pricing


def test_price():
    assert pricing.eur("claude-sonnet-5", 1_000_000, 0, 0, 0) == pytest.approx(2.0 * pricing.EUR_PER_USD)
    assert pricing.eur("claude-sonnet-5-20260101", 0, 0, 1_000_000, 1_000_000) == pytest.approx((0.2 + 2.5) * pricing.EUR_PER_USD)
    assert pricing.eur("claude-opus-5-5", 0, 1_000_000, 0, 0) == pytest.approx(20.0 * pricing.EUR_PER_USD)
    assert pricing.eur("unknown", 1, 1, 1, 1) == 0.0
