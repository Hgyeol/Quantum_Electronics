"""Deterministic position-context computation for the outlook service.

PRD_의사결정보조.md §5.3 defines the math. This module is intentionally a
pure-Python computation layer so the live KIS adapter can be swapped out in
tests without standing up the full KIS stack.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Callable, Protocol

from analysis.models import POSITION_DISCLAIMER, PositionContext

logger = logging.getLogger(__name__)


class PriceQuote(Protocol):
    """Minimal live-price shape consumed by `compute_position_context`."""

    price: float
    w52_high: float | None
    w52_low: float | None


PriceQuoteFn = Callable[[str], dict[str, Any] | None]


def _kis_current_price_quote(stock_code: str) -> dict[str, Any] | None:
    """Default live quote fetcher backed by KIS `inquire_price`."""
    try:
        import sys
        from pathlib import Path
        strategy_path = str(Path(__file__).resolve().parents[1] / "tools" / "strategy")
        if strategy_path not in sys.path:
            sys.path.insert(0, strategy_path)
        from core import data_fetcher
        return data_fetcher.get_current_price(stock_code)
    except Exception as exc:  # noqa: BLE001 — degrade to None on any KIS failure
        logger.warning("KIS current-price fetch failed for %s: %s", stock_code, exc)
        return None


def _coerce_positive(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _parse_held_since(value: str | date | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).replace(tzinfo=timezone.utc) if "T" in value or " " in value else datetime.combine(date.fromisoformat(value), datetime.min.time(), tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def compute_position_context(
    stock_code: str,
    avg_price: float | None,
    quantity: int | None,
    held_since: str | date | datetime | None = None,
    price_quote_fn: PriceQuoteFn | None = None,
    now: datetime | None = None,
) -> PositionContext | None:
    """Build a PositionContext when both avg_price and quantity are provided.

    Returns None when either input is missing or current-price retrieval fails,
    so callers can simply attach `position_context=...` without branching.
    """
    avg = _coerce_positive(avg_price)
    qty = None
    try:
        if quantity is not None:
            qty = int(quantity)
    except (TypeError, ValueError):
        qty = None
    if avg is None or qty is None or qty <= 0:
        return None

    fetcher = price_quote_fn or _kis_current_price_quote
    quote = fetcher(stock_code)
    if not quote:
        return None
    current_price = _coerce_positive(quote.get("price"))
    if current_price is None:
        return None

    w52_high = _coerce_positive(quote.get("w52_high"))
    w52_low = _coerce_positive(quote.get("w52_low"))

    pnl_amount = (current_price - avg) * qty
    pnl_pct = (current_price - avg) / avg * 100
    breakeven_required = max(0.0, (avg - current_price) / current_price * 100)
    distance_low = ((current_price - w52_low) / current_price * 100) if w52_low else None
    distance_high = ((w52_high - current_price) / current_price * 100) if w52_high else None

    held_at = _parse_held_since(held_since)
    holding_days: int | None = None
    if held_at is not None:
        anchor = now or datetime.now(timezone.utc)
        delta = anchor - held_at
        holding_days = max(0, int(delta.total_seconds() // 86400))

    return PositionContext(
        avg_price=avg,
        quantity=qty,
        held_since=held_at,
        current_price=current_price,
        holding_days=holding_days,
        unrealized_pnl_amount=round(pnl_amount, 2),
        unrealized_pnl_pct=round(pnl_pct, 4),
        breakeven_required_pct=round(breakeven_required, 4),
        distance_to_52w_low_pct=round(distance_low, 4) if distance_low is not None else None,
        distance_to_52w_high_pct=round(distance_high, 4) if distance_high is not None else None,
        disclaimer=POSITION_DISCLAIMER,
    )
