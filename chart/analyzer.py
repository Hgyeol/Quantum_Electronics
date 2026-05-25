"""Main chart analysis orchestrator."""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone

import pandas as pd

from chart.indicators import calc_bollinger_bands, calc_macd, calc_rsi, calc_stochastic
from chart.levels import detect_levels
from chart.models import ChartAnalysis, EntryExitSignal, OHLCVBar, SupportResistanceLevel, TechnicalIndicators

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
    pos = (price - lower) / band_width
    if price > upper:
        return "above_upper"
    if pos > 0.80:
        return "near_upper"
    if pos < 0.20:
        return "near_lower"
    if price < lower:
        return "below_lower"
    return "middle"


def _fill_missing_levels(
    supports: list[SupportResistanceLevel],
    resistances: list[SupportResistanceLevel],
    current_price: float,
    close: pd.Series,
    bb_upper: float | None,
    bb_lower: float | None,
) -> tuple[list[SupportResistanceLevel], list[SupportResistanceLevel]]:
    """MA20/MA60 및 볼린저밴드로 스윙포인트 레벨 보충."""

    ma20 = float(close.rolling(20).mean().iloc[-1])
    ma60 = float(close.rolling(60).mean().iloc[-1]) if len(close) >= 60 else None

    # 지지선 보충 (현재가 아래)
    if len(supports) == 0:
        if ma20 < current_price * 1.0:
            supports.append(SupportResistanceLevel(
                price=round(ma20, 0),
                level_type="support",
                strength="medium",
                touch_count=0,
                source="ma20",
            ))
        if ma60 and ma60 < current_price * 1.0 and abs(ma60 - ma20) / current_price > 0.02:
            supports.append(SupportResistanceLevel(
                price=round(ma60, 0),
                level_type="support",
                strength="medium",
                touch_count=0,
                source="ma60",
            ))
        if bb_lower and bb_lower < current_price:
            supports.append(SupportResistanceLevel(
                price=round(bb_lower, 0),
                level_type="support",
                strength="weak",
                touch_count=0,
                source="bb_lower",
            ))
        supports = sorted(supports, key=lambda x: x.price, reverse=True)[:3]

    # 저항선 보충 (현재가 위)
    if len(resistances) == 0:
        if bb_upper and bb_upper > current_price:
            resistances.append(SupportResistanceLevel(
                price=round(bb_upper, 0),
                level_type="resistance",
                strength="weak",
                touch_count=0,
                source="bb_upper",
            ))
        resistances = sorted(resistances, key=lambda x: x.price)[:3]

    return supports, resistances


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
    buy_score = 0
    sell_score = 0
    reasons: list[str] = []

    # RSI
    if rsi is not None:
        if rsi < 30:
            buy_score += 2
            reasons.append(f"RSI {rsi:.1f} — 단기 급락으로 반등 가능성 높음")
        elif rsi < 40:
            buy_score += 1
            reasons.append(f"RSI {rsi:.1f} — 저평가 구간, 매수 검토 가능")
        elif rsi > 70:
            sell_score += 2
            reasons.append(f"RSI {rsi:.1f} — 단기 과열, 차익 실현 고려")
        elif rsi > 60:
            sell_score += 1
            reasons.append(f"RSI {rsi:.1f} — 상단 접근 중, 신규 매수 부담")

    # MACD
    if macd_crossover == "bullish":
        buy_score += 2
        reasons.append("추세 전환 신호 — 하락에서 상승으로 반전 감지")
    elif macd_crossover == "bearish":
        sell_score += 2
        reasons.append("추세 전환 신호 — 상승에서 하락으로 반전 감지")
    elif macd_hist is not None:
        if macd_hist > 0:
            buy_score += 1
            reasons.append("상승 모멘텀 유지 중")
        else:
            sell_score += 1
            reasons.append("하락 모멘텀 지속 중")

    # Bollinger Bands
    if bb_pos in ("below_lower", "near_lower"):
        buy_score += 1
        reasons.append("가격이 밴드 하단 — 과매도 후 반등 구간")
    elif bb_pos in ("above_upper", "near_upper"):
        sell_score += 1
        reasons.append("가격이 밴드 상단 — 단기 조정 가능 구간")

    # Stochastic
    if stoch_k is not None and stoch_d is not None:
        if stoch_k < 20 and stoch_d < 20:
            buy_score += 1
            reasons.append(f"단기 지표 과매도 — 저점 매수 기회")
        elif stoch_k > 80 and stoch_d > 80:
            sell_score += 1
            reasons.append(f"단기 지표 과매수 — 고점 부근")

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

    primary_target = resistances[0].price if resistances else None
    secondary_target = resistances[1].price if len(resistances) > 1 else None

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
    df = _fetch_prices(stock_code, days=period_days)

    if df.empty or len(df) < 30:
        raise ValueError(f"가격 데이터 부족: {stock_code} ({len(df)}일)")

    close = df["close"]
    high = df["high"]
    low = df["low"]
    current_price = float(close.iloc[-1])

    rsi_series = calc_rsi(close)
    rsi_val = float(rsi_series.iloc[-1]) if not rsi_series.isna().all() else None

    macd_line, signal_line, histogram = calc_macd(close)
    macd_val = float(macd_line.iloc[-1]) if not macd_line.isna().all() else None
    macd_sig = float(signal_line.iloc[-1]) if not signal_line.isna().all() else None
    macd_hist = float(histogram.iloc[-1]) if not histogram.isna().all() else None

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

    supports, resistances = detect_levels(df, current_price)
    supports, resistances = _fill_missing_levels(
        supports, resistances, current_price, close, bb_upper, bb_lower
    )

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

    ohlcv_bars: list[OHLCVBar] = []
    for _, row in df.iterrows():
        try:
            date_raw = str(row["date"])
            # Normalize date to YYYY-MM-DD
            if len(date_raw) == 8 and date_raw.isdigit():
                date_str = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}"
            else:
                date_str = date_raw[:10]
            ohlcv_bars.append(OHLCVBar(
                date=date_str,
                open=float(row.get("open", row["close"])),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row.get("volume", 0)),
            ))
        except Exception:
            pass

    return ChartAnalysis(
        stock_code=stock_code,
        stock_name=stock_name,
        generated_at=datetime.now(timezone.utc),
        current_price=current_price,
        analysis_period_days=len(df),
        ohlcv=ohlcv_bars,
        support_levels=supports,
        resistance_levels=resistances,
        indicators=indicators,
        signal=signal,
    )
