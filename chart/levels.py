"""Support and resistance level detection via swing-point clustering."""
from __future__ import annotations

import numpy as np
import pandas as pd

from chart.models import SupportResistanceLevel


def _find_swing_points(
    df: pd.DataFrame,
    window: int = 5,
) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """Return (swing_lows, swing_highs) as (date_str, price) tuples."""
    swing_lows: list[tuple[str, float]] = []
    swing_highs: list[tuple[str, float]] = []

    lows = df["low"].values
    highs = df["high"].values
    dates = df["date"].values if "date" in df.columns else df.index.astype(str).values

    for i in range(window, len(df) - window):
        # swing low: local minimum in lows
        if lows[i] == min(lows[i - window : i + window + 1]):
            swing_lows.append((str(dates[i]), float(lows[i])))
        # swing high: local maximum in highs
        if highs[i] == max(highs[i - window : i + window + 1]):
            swing_highs.append((str(dates[i]), float(highs[i])))

    return swing_lows, swing_highs


def _cluster_levels(
    points: list[tuple[str, float]],
    current_price: float,
    tolerance_pct: float = 1.5,
) -> list[tuple[float, int, str]]:
    """Merge nearby price points into clusters.

    Returns list of (price, touch_count, last_date) sorted by price ascending.
    """
    if not points:
        return []

    prices = np.array([p for _, p in points])
    dates = [d for d, _ in points]
    used = [False] * len(prices)
    clusters: list[tuple[float, int, str]] = []

    for i in range(len(prices)):
        if used[i]:
            continue
        group_prices = [prices[i]]
        group_dates = [dates[i]]
        used[i] = True
        for j in range(i + 1, len(prices)):
            if used[j]:
                continue
            # within tolerance of cluster mean
            if abs(prices[j] - np.mean(group_prices)) / current_price * 100 <= tolerance_pct:
                group_prices.append(prices[j])
                group_dates.append(dates[j])
                used[j] = True
        clusters.append((float(np.mean(group_prices)), len(group_prices), max(group_dates)))

    return sorted(clusters, key=lambda x: x[0])


def _strength(touch_count: int) -> str:
    if touch_count >= 4:
        return "strong"
    if touch_count >= 2:
        return "medium"
    return "weak"


def detect_levels(
    df: pd.DataFrame,
    current_price: float,
    swing_window: int = 5,
    tolerance_pct: float = 1.5,
    max_levels: int = 5,
) -> tuple[list[SupportResistanceLevel], list[SupportResistanceLevel]]:
    """Detect support and resistance levels from OHLC data.

    Args:
        df: DataFrame with columns [date, open, high, low, close, volume]
        current_price: latest price for relative distance filtering
        swing_window: candles on each side to qualify a swing point
        tolerance_pct: price proximity threshold for clustering (% of current price)
        max_levels: max levels to return per side

    Returns:
        (support_levels, resistance_levels) sorted by price
    """
    swing_lows, swing_highs = _find_swing_points(df, window=swing_window)

    support_clusters = _cluster_levels(swing_lows, current_price, tolerance_pct)
    resistance_clusters = _cluster_levels(swing_highs, current_price, tolerance_pct)

    # support = clusters below current price within 25%, resistance = clusters above within 25%
    supports = [
        SupportResistanceLevel(
            price=round(price, 0),
            level_type="support",
            strength=_strength(count),
            touch_count=count,
            last_tested_date=last_date,
        )
        for price, count, last_date in support_clusters
        if current_price * 0.75 <= price < current_price * 1.01
    ]

    resistances = [
        SupportResistanceLevel(
            price=round(price, 0),
            level_type="resistance",
            strength=_strength(count),
            touch_count=count,
            last_tested_date=last_date,
        )
        for price, count, last_date in resistance_clusters
        if current_price * 0.99 < price <= current_price * 1.25
    ]

    # closest levels first
    supports = sorted(supports, key=lambda x: x.price, reverse=True)[:max_levels]
    resistances = sorted(resistances, key=lambda x: x.price)[:max_levels]

    return supports, resistances
