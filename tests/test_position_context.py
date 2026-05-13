"""Unit tests for the deterministic position-context computation."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from analysis.models import POSITION_DISCLAIMER
from services.position import compute_position_context


def _fixed_quote(price: float, w52_high: float | None = 16000, w52_low: float | None = 9500):
    def _fetch(stock_code: str):
        return {"price": price, "w52_high": w52_high, "w52_low": w52_low}
    return _fetch


_NOW = datetime(2026, 5, 13, tzinfo=timezone.utc)


class PositionContextTests(unittest.TestCase):
    def test_profit_position(self):
        ctx = compute_position_context(
            stock_code="005930",
            avg_price=12660,
            quantity=2200,
            held_since="2024-03-15",
            price_quote_fn=_fixed_quote(13200),
            now=_NOW,
        )
        assert ctx is not None
        self.assertEqual(ctx.unrealized_pnl_amount, 1188000.0)
        self.assertAlmostEqual(ctx.unrealized_pnl_pct, 4.2654, places=3)
        self.assertEqual(ctx.breakeven_required_pct, 0.0)
        self.assertGreater(ctx.distance_to_52w_low_pct, 0)
        self.assertGreater(ctx.distance_to_52w_high_pct, 0)
        self.assertEqual(ctx.disclaimer, POSITION_DISCLAIMER)

    def test_underwater_position_requires_breakeven(self):
        ctx = compute_position_context(
            stock_code="005930",
            avg_price=15000,
            quantity=10,
            price_quote_fn=_fixed_quote(12000),
        )
        assert ctx is not None
        self.assertLess(ctx.unrealized_pnl_amount, 0)
        self.assertGreater(ctx.breakeven_required_pct, 0)
        self.assertAlmostEqual(ctx.breakeven_required_pct, 25.0, places=3)

    def test_breakeven_clamped_at_zero_when_in_profit(self):
        ctx = compute_position_context(
            stock_code="005930",
            avg_price=10000,
            quantity=5,
            price_quote_fn=_fixed_quote(12000),
        )
        assert ctx is not None
        self.assertEqual(ctx.breakeven_required_pct, 0.0)

    def test_returns_none_when_avg_price_missing(self):
        ctx = compute_position_context(
            stock_code="005930",
            avg_price=None,
            quantity=10,
            price_quote_fn=_fixed_quote(12000),
        )
        self.assertIsNone(ctx)

    def test_returns_none_when_quantity_missing(self):
        ctx = compute_position_context(
            stock_code="005930",
            avg_price=10000,
            quantity=None,
            price_quote_fn=_fixed_quote(12000),
        )
        self.assertIsNone(ctx)

    def test_returns_none_when_quote_unavailable(self):
        ctx = compute_position_context(
            stock_code="005930",
            avg_price=10000,
            quantity=10,
            price_quote_fn=lambda _code: None,
        )
        self.assertIsNone(ctx)

    def test_zero_price_treated_as_missing(self):
        # PRD §5.3 forbids non-positive prices from yielding a context.
        ctx = compute_position_context(
            stock_code="005930",
            avg_price=10000,
            quantity=10,
            price_quote_fn=lambda _code: {"price": 0, "w52_high": 0, "w52_low": 0},
        )
        self.assertIsNone(ctx)

    def test_holding_days_from_held_since(self):
        ctx = compute_position_context(
            stock_code="005930",
            avg_price=10000,
            quantity=1,
            held_since="2026-05-01",
            price_quote_fn=_fixed_quote(11000),
            now=_NOW,
        )
        assert ctx is not None
        self.assertEqual(ctx.holding_days, 12)

    def test_missing_held_since_yields_none_days(self):
        ctx = compute_position_context(
            stock_code="005930",
            avg_price=10000,
            quantity=1,
            price_quote_fn=_fixed_quote(11000),
            now=_NOW,
        )
        assert ctx is not None
        self.assertIsNone(ctx.holding_days)

    def test_missing_w52_yields_none_distances(self):
        ctx = compute_position_context(
            stock_code="005930",
            avg_price=10000,
            quantity=1,
            price_quote_fn=lambda _code: {"price": 11000, "w52_high": None, "w52_low": None},
        )
        assert ctx is not None
        self.assertIsNone(ctx.distance_to_52w_low_pct)
        self.assertIsNone(ctx.distance_to_52w_high_pct)

    def test_disclaimer_is_constant(self):
        ctx = compute_position_context(
            stock_code="005930",
            avg_price=10000,
            quantity=1,
            price_quote_fn=_fixed_quote(11000),
        )
        assert ctx is not None
        # Static-grep equivalent of PRD §7.2: no buy/sell recommendation wording.
        forbidden = ("매수하세요", "사세요", "팔아야", "손절하세요", "추천")
        for word in forbidden:
            self.assertNotIn(word, ctx.disclaimer)


if __name__ == "__main__":
    unittest.main()
