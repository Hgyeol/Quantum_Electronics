"""업종별 종목 추천 서비스.

스코어 = 0.6 × 20일 가격 모멘텀 + 0.4 × 거래량 서지 비율
(5일 평균 거래량 / 20일 평균 거래량 − 1)
"""

from __future__ import annotations

from dataclasses import dataclass

from services.screener_db import get_all_sectors, get_prices, get_stocks_by_sector


@dataclass
class SectorPick:
    stock_code: str
    name: str
    market: str
    close: int
    change_rate: float
    score: float


def list_sectors() -> list[dict]:
    """업종명 + 종목수 반환 (daily_price 데이터 있는 종목 기준)."""
    return get_all_sectors()


def get_picks(sector: str, top_n: int = 3) -> list[SectorPick]:
    stocks = get_stocks_by_sector(sector)
    if not stocks:
        return []

    scored: list[tuple[float, SectorPick]] = []

    for s in stocks:
        code = s["stock_code"]
        prices = get_prices(code, days=25)
        if len(prices) < 5:
            continue

        closes = [p["close"] for p in prices]
        volumes = [p["volume"] for p in prices]

        close_now = closes[-1]
        close_20 = closes[0] if len(closes) >= 20 else closes[0]

        if close_20 == 0:
            continue

        momentum = (close_now - close_20) / close_20 * 100

        vol_5 = sum(volumes[-5:]) / 5
        vol_20 = sum(volumes) / len(volumes)
        vol_surge = (vol_5 / vol_20 - 1) * 100 if vol_20 > 0 else 0

        score = 0.6 * momentum + 0.4 * vol_surge

        prev_close = closes[-2] if len(closes) >= 2 else close_now
        change_rate = (close_now - prev_close) / prev_close * 100 if prev_close else 0.0

        scored.append((
            score,
            SectorPick(
                stock_code=code,
                name=s["name"] or code,
                market=s["market"] or "",
                close=close_now,
                change_rate=round(change_rate, 2),
                score=round(score, 2),
            ),
        ))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [pick for _, pick in scored[:top_n]]
