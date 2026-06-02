"""Volume Profile and Anchored VWAP calculation from daily OHLCV data."""
from __future__ import annotations

import numpy as np
import pandas as pd


def compute_volume_profile(
    df: pd.DataFrame,
    n_buckets: int = 100,
) -> tuple[np.ndarray, np.ndarray]:
    """일봉 OHLCV에서 Volume Profile 근사화.

    각 일봉의 거래량을 고가~저가 구간에 걸친 버킷에 균등 분배.

    Returns:
        prices: 각 버킷의 중간 가격 배열 (n_buckets,)
        volumes: 각 버킷의 누적 거래량 배열 (n_buckets,)
    """
    lo = float(df["low"].min())
    hi = float(df["high"].max())

    if hi <= lo:
        return np.array([(lo + hi) / 2]), np.array([float(df["volume"].sum())])

    bucket_size = (hi - lo) / n_buckets
    volumes = np.zeros(n_buckets)

    lows = df["low"].values.astype(float)
    highs = df["high"].values.astype(float)
    vols = df["volume"].values.astype(float)

    for candle_lo, candle_hi, vol in zip(lows, highs, vols):
        lo_idx = int((candle_lo - lo) / bucket_size)
        hi_idx = int((candle_hi - lo) / bucket_size)
        lo_idx = max(0, min(lo_idx, n_buckets - 1))
        hi_idx = max(0, min(hi_idx, n_buckets - 1))
        n = hi_idx - lo_idx + 1
        volumes[lo_idx : hi_idx + 1] += vol / n

    prices = np.array([lo + (i + 0.5) * bucket_size for i in range(n_buckets)])
    return prices, volumes


def find_poc(prices: np.ndarray, volumes: np.ndarray) -> float:
    """Point of Control: 거래량이 가장 많이 터진 가격 반환."""
    return float(prices[int(np.argmax(volumes))])


def find_hvn_zones(
    prices: np.ndarray,
    volumes: np.ndarray,
    threshold_std: float = 1.0,
) -> list[tuple[float, float, float]]:
    """High Volume Node 존 탐지 (평균 + threshold_std × 표준편차 이상).

    인접한 HVN 버킷을 하나의 존으로 병합.

    Returns:
        list of (zone_center, zone_low, zone_high) — 거래량 내림차순
    """
    threshold = float(np.mean(volumes) + threshold_std * np.std(volumes))
    bucket_size = float(prices[1] - prices[0]) if len(prices) > 1 else 1.0

    in_zone = False
    zone_start = 0
    zones: list[tuple[float, float, float, float]] = []  # (total_vol, center, lo, hi)

    for i in range(len(volumes)):
        if volumes[i] >= threshold:
            if not in_zone:
                in_zone = True
                zone_start = i
        else:
            if in_zone:
                _flush_zone(prices, volumes, zone_start, i, bucket_size, zones)
                in_zone = False

    if in_zone:
        _flush_zone(prices, volumes, zone_start, len(volumes), bucket_size, zones)

    zones.sort(key=lambda x: x[0], reverse=True)
    return [(z[1], z[2], z[3]) for z in zones]


def _flush_zone(
    prices: np.ndarray,
    volumes: np.ndarray,
    start: int,
    end: int,
    bucket_size: float,
    out: list,
) -> None:
    seg_p = prices[start:end]
    seg_v = volumes[start:end]
    total_vol = float(seg_v.sum())
    center = float(np.average(seg_p, weights=seg_v))
    zone_lo = float(seg_p[0]) - bucket_size / 2
    zone_hi = float(seg_p[-1]) + bucket_size / 2
    out.append((total_vol, center, zone_lo, zone_hi))


def compute_anchored_vwap(df: pd.DataFrame, anchor_pos: int = 0) -> float:
    """anchor_pos 이후 기간의 Anchored VWAP 계산.

    Typical Price = (High + Low + Close) / 3
    """
    sub = df.iloc[anchor_pos:]
    typical = (sub["high"] + sub["low"] + sub["close"]) / 3.0
    total_vol = float(sub["volume"].sum())
    if total_vol == 0:
        return float(sub["close"].iloc[-1])
    return float((typical * sub["volume"]).sum() / total_vol)


def get_anchor_positions(df: pd.DataFrame) -> dict[str, int]:
    """6개월 내 의미 있는 VWAP 기준점 인덱스 반환.

    - "high": 최고가를 기록한 날 (하락 매물 저항 파악)
    - "low":  최저가를 기록한 날 (저점 반등 지지 파악)
    - "vol":  최대 거래량 급등일 (세력/기관 평균 단가 추정)
    """
    n = len(df)
    window = min(n, 126)  # 6개월 ≈ 126 거래일
    start = n - window

    sub_highs = df["high"].values[start:]
    sub_lows = df["low"].values[start:]
    sub_vols = df["volume"].values[start:]

    anchors: dict[str, int] = {
        "high": start + int(sub_highs.argmax()),
        "low": start + int(sub_lows.argmin()),
    }

    # 최근 5일은 제외 (너무 가까우면 의미 없음)
    vol_range = sub_vols[:-5] if len(sub_vols) > 5 else sub_vols
    if len(vol_range) > 0:
        anchors["vol"] = start + int(vol_range.argmax())

    return anchors
