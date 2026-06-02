"""Support and resistance level detection via Volume Profile + Anchored VWAP (hybrid)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from chart.models import SupportResistanceLevel
from chart.volume_profile import (
    compute_anchored_vwap,
    compute_volume_profile,
    find_hvn_zones,
    find_poc,
    get_anchor_positions,
)

_STRENGTH_RANK = {"strong": 3, "medium": 2, "weak": 1}


def _find_swing_points(
    df: pd.DataFrame,
    window: int = 5,
) -> tuple[list[float], list[float]]:
    """Local low/high 가격 목록 반환 (HVN 교차검증용)."""
    lows = df["low"].values.astype(float)
    highs = df["high"].values.astype(float)
    swing_lows: list[float] = []
    swing_highs: list[float] = []

    for i in range(window, len(df) - window):
        if lows[i] == lows[i - window : i + window + 1].min():
            swing_lows.append(lows[i])
        if highs[i] == highs[i - window : i + window + 1].max():
            swing_highs.append(highs[i])

    return swing_lows, swing_highs


def _in_any_hvn(price: float, hvn_zones: list[tuple[float, float, float]]) -> bool:
    return any(lo <= price <= hi for _, lo, hi in hvn_zones)


def _near_price(a: float, b: float, current_price: float, pct: float = 1.0) -> bool:
    return abs(a - b) / current_price * 100 <= pct


def _deduplicate(
    levels: list[SupportResistanceLevel],
    current_price: float,
    tolerance_pct: float = 2.0,
) -> list[SupportResistanceLevel]:
    """2% 이내 중복 레벨 제거 — 강도 높은 것 우선."""
    levels = sorted(levels, key=lambda x: -_STRENGTH_RANK[x.strength])
    result: list[SupportResistanceLevel] = []
    for level in levels:
        if not any(
            abs(level.price - ex.price) / current_price * 100 <= tolerance_pct
            for ex in result
        ):
            result.append(level)
    return result


def detect_levels(
    df: pd.DataFrame,
    current_price: float,
    n_buckets: int = 100,
    max_levels: int = 5,
) -> tuple[list[SupportResistanceLevel], list[SupportResistanceLevel]]:
    """Volume Profile + Anchored VWAP 기반 지지/저항 탐지.

    1. Volume Profile → POC (strong) + HVN 존 (medium/strong)
    2. Anchored VWAP 3종 → medium 레벨
    3. Swing point가 HVN 존 내에 있으면 해당 HVN을 strong으로 승격
    4. 2% 이내 중복 제거 후 max_levels 반환
    """
    prices_arr, volumes_arr = compute_volume_profile(df, n_buckets=n_buckets)

    # ── 1. POC ─────────────────────────────────────────────────────────────
    poc_price = find_poc(prices_arr, volumes_arr)

    # ── 2. HVN 존 ─────────────────────────────────────────────────────────
    hvn_zones = find_hvn_zones(prices_arr, volumes_arr, threshold_std=1.0)

    # ── 3. Anchored VWAP ───────────────────────────────────────────────────
    anchor_positions = get_anchor_positions(df)
    vwap_map: dict[str, float] = {
        name: compute_anchored_vwap(df, pos)
        for name, pos in anchor_positions.items()
    }

    # ── 4. Swing points (교차검증용) ────────────────────────────────────────
    swing_lows, swing_highs = _find_swing_points(df, window=5)

    supports: list[SupportResistanceLevel] = []
    resistances: list[SupportResistanceLevel] = []

    lo_bound = current_price * 0.75
    hi_bound = current_price * 1.25
    sup_ceiling = current_price * 0.99
    res_floor = current_price * 1.01

    # ── POC ────────────────────────────────────────────────────────────────
    if lo_bound <= poc_price <= hi_bound:
        lvl = SupportResistanceLevel(
            price=round(poc_price, 0),
            level_type="support" if poc_price <= sup_ceiling else "resistance",
            strength="strong",
            touch_count=0,
            source="poc",
        )
        (supports if poc_price <= sup_ceiling else resistances).append(lvl)

    # ── HVN 존 ─────────────────────────────────────────────────────────────
    for center, zone_lo, zone_hi in hvn_zones:
        if not (lo_bound <= center <= hi_bound):
            continue

        # swing point가 이 존 안에 있으면 strong, 아니면 medium
        swing_in_zone = (
            any(zone_lo <= p <= zone_hi for p in swing_lows)
            or any(zone_lo <= p <= zone_hi for p in swing_highs)
        )
        strength = "strong" if swing_in_zone else "medium"

        lvl = SupportResistanceLevel(
            price=round(center, 0),
            level_type="support" if center <= sup_ceiling else "resistance",
            strength=strength,
            touch_count=0,
            source="hvn",
        )
        (supports if center <= sup_ceiling else resistances).append(lvl)

    # ── Anchored VWAP ──────────────────────────────────────────────────────
    for name, vwap in vwap_map.items():
        if not (lo_bound <= vwap <= hi_bound):
            continue
        # VWAP이 HVN 존과 겹치면 이미 HVN 레벨로 커버되므로 추가만
        lvl = SupportResistanceLevel(
            price=round(vwap, 0),
            level_type="support" if vwap <= sup_ceiling else "resistance",
            strength="medium",
            touch_count=0,
            source="vwap",
        )
        (supports if vwap <= sup_ceiling else resistances).append(lvl)

    # ── 중복 제거 & 정렬 ────────────────────────────────────────────────────
    supports = _deduplicate(supports, current_price)
    resistances = _deduplicate(resistances, current_price)

    supports = sorted(supports, key=lambda x: x.price, reverse=True)[:max_levels]
    resistances = sorted(resistances, key=lambda x: x.price)[:max_levels]

    return supports, resistances
