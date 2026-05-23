"""Main chart analysis orchestrator."""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone

import pandas as pd

from chart.indicators import calc_bollinger_bands, calc_macd, calc_rsi, calc_stochastic
from chart.levels import detect_levels
from chart.models import ChartAnalysis, EntryExitSignal, TechnicalIndicators

_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
_TOOLS_DOMESTIC = os.path.join(_ROOT, "tools", "domestic_stock")
_TOOLS_STRATEGY = os.path.join(_ROOT, "tools", "strategy")
for _p in [_ROOT, _TOOLS_DOMESTIC, _TOOLS_STRATEGY]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

logger = logging.getLogger(__name__)


def _fetch_prices(stock_code: str, days: int = 120) -> pd.DataFrame:
    """Fetch OHLCV data via KIS API. Returns DataFrame with columns
    [date, open, high, low, close, volume] sorted oldest→newest."""
    try:
        from core.data_fetcher import get_daily_prices
        df = get_daily_prices(stock_code, days=days)
        if df is not None and not df.empty:
            return df
    except Exception as exc:
        logger.debug("data_fetcher unavailable: %s", exc)

    # fallback: use inquire_daily_itemchartprice directly
    try:
        from datetime import timedelta
        from inquire_daily_itemchartprice import inquire_daily_itemchartprice

        end = datetime.now()
        start = end - timedelta(days=days * 2)
        _, df2 = inquire_daily_itemchartprice(
            env_dv="real",
            fid_cond_mrkt_div_code="J",
            fid_input_iscd=stock_code,
            fid_input_date_1=start.strftime("%Y%m%d"),
            fid_input_date_2=end.strftime("%Y%m%d"),
            fid_period_div_code="D",
            fid_org_adj_prc="0",
        )
        if df2 is None or df2.empty:
            return pd.DataFrame()

        col_map = {
            "stck_bsop_date": "date",
            "stck_oprc": "open",
            "stck_hgpr": "high",
            "stck_lwpr": "low",
            "stck_clpr": "close",
            "acml_vol": "volume",
        }
        df2 = df2.rename(columns={k: v for k, v in col_map.items() if k in df2.columns})
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df2.columns:
                df2[col] = pd.to_numeric(df2[col], errors="coerce")
        df2 = df2.sort_values("date").tail(days).reset_index(drop=True)
        return df2
    except Exception as exc:
        logger.warning("inquire_daily_itemchartprice failed: %s", exc)
        return pd.DataFrame()


def _bb_position(price: float, upper: float, lower: float, middle: float) -> str:
    band_width = upper - lower
    if band_width == 0:
        return "middle"
    pos = (price - lower) / band_width  # 0=lower, 1=upper
    if price > upper:
        return "above_upper"
    if pos > 0.80:
        return "near_upper"
    if pos < 0.20:
        return "near_lower"
    if price < lower:
        return "below_lower"
    return "middle"


def _build_signal(
    current_price: float,
    rsi: float | None,
    macd_hist: float | None,
    macd_crossover: str,
    bb_pos: str,
    stoch_k: float | None,
    stoch_d: float | None,
    supports: list,
    resistances: list,
) -> EntryExitSignal:
    """Combine indicators into a single entry/exit recommendation."""
    buy_score = 0
    sell_score = 0
    reasons: list[str] = []

    # RSI
    if rsi is not None:
        if rsi < 30:
            buy_score += 2
            reasons.append(f"RSI {rsi:.1f} — 과매도 구간 (매수 신호)")
        elif rsi < 40:
            buy_score += 1
            reasons.append(f"RSI {rsi:.1f} — 저평가 구간")
        elif rsi > 70:
            sell_score += 2
            reasons.append(f"RSI {rsi:.1f} — 과매수 구간 (매도 신호)")
        elif rsi > 60:
            sell_score += 1
            reasons.append(f"RSI {rsi:.1f} — 고평가 구간")

    # MACD
    if macd_crossover == "bullish":
        buy_score += 2
        reasons.append("MACD 골든크로스 (상승 전환)")
    elif macd_crossover == "bearish":
        sell_score += 2
        reasons.append("MACD 데드크로스 (하락 전환)")
    elif macd_hist is not None:
        if macd_hist > 0:
            buy_score += 1
            reasons.append("MACD 히스토그램 양수 (상승 모멘텀)")
        else:
            sell_score += 1
            reasons.append("MACD 히스토그램 음수 (하락 모멘텀)")

    # Bollinger Bands
    if bb_pos in ("below_lower", "near_lower"):
        buy_score += 1
        reasons.append("볼린저밴드 하단 근접 — 반등 가능 구간")
    elif bb_pos in ("above_upper", "near_upper"):
        sell_score += 1
        reasons.append("볼린저밴드 상단 근접 — 조정 가능 구간")

    # Stochastic
    if stoch_k is not None and stoch_d is not None:
        if stoch_k < 20 and stoch_d < 20:
            buy_score += 1
            reasons.append(f"스토캐스틱 {stoch_k:.1f} — 과매도")
        elif stoch_k > 80 and stoch_d > 80:
            sell_score += 1
            reasons.append(f"스토캐스틱 {stoch_k:.1f} — 과매수")

    # Determine action
    net = buy_score - sell_score
    if net >= 3:
        action, confidence = "buy", "high"
    elif net == 2:
        action, confidence = "buy", "medium"
    elif net == 1:
        action, confidence = "buy", "low"
    elif net <= -3:
        action, confidence = "sell", "high"
    elif net == -2:
        action, confidence = "sell", "medium"
    elif net == -1:
        action, confidence = "sell", "low"
    else:
        action, confidence = "hold", "medium"

    # Entry zone: nearest support
    entry_low = entry_high = None
    stop_loss = None
    if supports:
        nearest_support = supports[0].price
        entry_low = nearest_support * 0.995
        entry_high = nearest_support * 1.02
        stop_loss = round(nearest_support * 0.97, 0)

    # Targets: nearest resistances
    primary_target = resistances[0].price if resistances else None
    secondary_target = resistances[1].price if len(resistances) > 1 else None

    # Risk/reward
    rr = None
    if stop_loss and primary_target and entry_high:
        risk = entry_high - stop_loss
        reward = primary_target - entry_high
        if risk > 0:
            rr = round(reward / risk, 2)

    if not reasons:
        reasons.append("뚜렷한 방향성 신호 없음 — 관망 권장")

    return EntryExitSignal(
        action=action,
        confidence=confidence,
        entry_zone_low=round(entry_low, 0) if entry_low else None,
        entry_zone_high=round(entry_high, 0) if entry_high else None,
        primary_target=primary_target,
        secondary_target=secondary_target,
        stop_loss=stop_loss,
        risk_reward_ratio=rr,
        reasoning=reasons,
    )


def analyze_chart(
    stock_code: str,
    stock_name: str | None = None,
    period_days: int = 120,
) -> ChartAnalysis:
    """Fetch price data and run full chart analysis."""
    df = _fetch_prices(stock_code, days=period_days)

    if df.empty or len(df) < 30:
        raise ValueError(f"가격 데이터 부족: {stock_code} ({len(df)}일)")

    close = df["close"]
    high = df["high"]
    low = df["low"]
    current_price = float(close.iloc[-1])

    # Indicators
    rsi_series = calc_rsi(close)
    rsi_val = float(rsi_series.iloc[-1]) if not rsi_series.isna().all() else None

    macd_line, signal_line, histogram = calc_macd(close)
    macd_val = float(macd_line.iloc[-1]) if not macd_line.isna().all() else None
    macd_sig = float(signal_line.iloc[-1]) if not signal_line.isna().all() else None
    macd_hist = float(histogram.iloc[-1]) if not histogram.isna().all() else None

    # MACD crossover: compare last two values
    crossover = "none"
    if len(histogram.dropna()) >= 2:
        prev_hist = float(histogram.dropna().iloc[-2])
        cur_hist = float(histogram.dropna().iloc[-1])
        if prev_hist < 0 <= cur_hist:
            crossover = "bullish"
        elif prev_hist > 0 >= cur_hist:
            crossover = "bearish"

    bb_upper_s, bb_mid_s, bb_lower_s = calc_bollinger_bands(close)
    bb_upper = float(bb_upper_s.iloc[-1]) if not bb_upper_s.isna().all() else None
    bb_mid = float(bb_mid_s.iloc[-1]) if not bb_mid_s.isna().all() else None
    bb_lower = float(bb_lower_s.iloc[-1]) if not bb_lower_s.isna().all() else None

    bb_pos = "middle"
    if bb_upper and bb_lower and bb_mid:
        bb_pos = _bb_position(current_price, bb_upper, bb_lower, bb_mid)

    stoch_k_s, stoch_d_s = calc_stochastic(high, low, close)
    stoch_k = float(stoch_k_s.iloc[-1]) if not stoch_k_s.isna().all() else None
    stoch_d = float(stoch_d_s.iloc[-1]) if not stoch_d_s.isna().all() else None

    rsi_zone = (
        "oversold" if (rsi_val or 50) < 30
        else "overbought" if (rsi_val or 50) > 70
        else "neutral"
    )
    stoch_zone = (
        "oversold" if (stoch_k or 50) < 20
        else "overbought" if (stoch_k or 50) > 80
        else "neutral"
    )

    indicators = TechnicalIndicators(
        rsi=round(rsi_val, 2) if rsi_val is not None else None,
        rsi_zone=rsi_zone,
        macd=round(macd_val, 2) if macd_val is not None else None,
        macd_signal=round(macd_sig, 2) if macd_sig is not None else None,
        macd_histogram=round(macd_hist, 2) if macd_hist is not None else None,
        macd_crossover=crossover,
        bb_upper=round(bb_upper, 0) if bb_upper is not None else None,
        bb_middle=round(bb_mid, 0) if bb_mid is not None else None,
        bb_lower=round(bb_lower, 0) if bb_lower is not None else None,
        bb_position=bb_pos,
        stoch_k=round(stoch_k, 2) if stoch_k is not None else None,
        stoch_d=round(stoch_d, 2) if stoch_d is not None else None,
        stoch_zone=stoch_zone,
    )

    # Support / Resistance
    supports, resistances = detect_levels(df, current_price)

    # Entry / Exit signal
    signal = _build_signal(
        current_price=current_price,
        rsi=rsi_val,
        macd_hist=macd_hist,
        macd_crossover=crossover,
        bb_pos=bb_pos,
        stoch_k=stoch_k,
        stoch_d=stoch_d,
        supports=supports,
        resistances=resistances,
    )

    return ChartAnalysis(
        stock_code=stock_code,
        stock_name=stock_name,
        generated_at=datetime.now(timezone.utc),
        current_price=current_price,
        analysis_period_days=len(df),
        support_levels=supports,
        resistance_levels=resistances,
        indicators=indicators,
        signal=signal,
    )
