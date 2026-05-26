"""FastAPI entry point for Quantum Electronics."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from datetime import date

from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel

from analysis.models import OutlookReport
from chart.analyzer import analyze_chart
from chart.models import ChartAnalysis
from services.outlook import OutlookService, lookup_stock_master, search_stock_master
from services.ranking import fetch_volume_rank, fetch_foreign_institution_rank, RankItem
from services.technical_indicators import calculate_indicators, list_indicator_definitions
from services.watchlist import WatchlistItem as _WatchlistItem, fetch_multi_price
from services.realtime import stream_prices

_DEFAULT_CORS_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"

logger = logging.getLogger(__name__)
_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_dotenv_file(path: Path = _PROJECT_ROOT / ".env") -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def initialize_kis_auth() -> bool:
    if os.getenv("KIS_AUTO_AUTH", "1").lower() in {"0", "false", "no"}:
        return False

    try:
        import kis_auth

        kis_auth.auth(svr=os.getenv("KIS_SERVER", "prod"))
    except Exception as exc:
        logger.warning("KIS auth initialization failed: %s", exc)
        return False
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv_file()
    app.state.kis_authenticated = initialize_kis_auth()
    if app.state.kis_authenticated:
        try:
            from services.realtime import get_approval_key
            key = get_approval_key(svr=os.getenv("KIS_SERVER", "prod"))
            if key:
                logger.info("KIS WebSocket approval key 발급 완료")
            else:
                logger.warning("KIS WebSocket approval key 발급 실패")
        except Exception as exc:
            logger.warning("KIS WebSocket auth 실패: %s", exc)
    yield


app = FastAPI(
    title="Quantum Electronics",
    description="AI-assisted Korean stock investment outlook API",
    version="1.0.0",
    lifespan=lifespan,
)

_origins = [
    origin.strip()
    for origin in os.getenv("OUTLOOK_CORS_ORIGINS", _DEFAULT_CORS_ORIGINS).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["GET"],
    allow_headers=["*"],
)


def get_outlook_service() -> OutlookService:
    return OutlookService()


class WatchlistItemResponse(BaseModel):
    stock_code: str
    stock_name: str | None
    price: int
    change: int
    change_rate: float
    volume: int
    trade_value: int = 0


@app.get("/health")
def health():
    return {"status": "ok", "service": "quantum-electronics"}


@app.get("/search")
def search_stocks(q: str = Query(..., min_length=1, description="종목코드 또는 종목명 (부분 일치)")):
    """종목 검색 — 코드·이름 부분 일치, 최대 10개 반환."""
    return search_stock_master(q, limit=10)


class RankItemResponse(BaseModel):
    rank: int
    stock_code: str
    stock_name: str
    price: int
    change: int
    change_rate: float
    volume: int
    trade_value: int
    extra_value: int = 0


@app.get("/ranking/volume", response_model=list[RankItemResponse])
def get_volume_ranking(
    sort: str = Query("volume", description="volume: 거래량순 | amount: 거래대금순"),
):
    """거래량/거래대금 순위 TOP 20."""
    if sort not in ("volume", "amount"):
        raise HTTPException(status_code=422, detail="sort must be 'volume' or 'amount'")
    items = fetch_volume_rank(sort=sort, limit=20)
    return [RankItemResponse(**item.__dict__) for item in items]


@app.get("/ranking/foreign", response_model=list[RankItemResponse])
def get_foreign_ranking(
    investor: str = Query("foreign", description="foreign: 외국인 | institution: 기관"),
):
    """외국인/기관 순매수 순위 TOP 20."""
    if investor not in ("foreign", "institution"):
        raise HTTPException(status_code=422, detail="investor must be 'foreign' or 'institution'")
    items = fetch_foreign_institution_rank(investor=investor, limit=20)
    return [RankItemResponse(**item.__dict__) for item in items]


@app.get("/", response_class=HTMLResponse)
def indicator_frontend():
    index_path = _PROJECT_ROOT / "web" / "static" / "indicators.html"
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


@app.get("/outlook/stock/{code}", response_model=OutlookReport)
def get_stock_outlook(
    code: str,
    avg_price: float | None = Query(None, gt=0, description="Position average price (KRW)"),
    quantity: int | None = Query(None, gt=0, description="Position share count"),
    held_since: date | None = Query(None, description="Position open date (YYYY-MM-DD)"),
    service: OutlookService = Depends(get_outlook_service),
) -> OutlookReport:
    if held_since is not None and held_since > date.today():
        raise HTTPException(status_code=422, detail="held_since cannot be in the future")
    return service.build_report(
        code,
        avg_price=avg_price,
        quantity=quantity,
        held_since=held_since.isoformat() if held_since else None,
    )


@app.get("/chart/{code}", response_model=ChartAnalysis)
def get_chart_analysis(
    code: str,
    days: int = Query(120, ge=60, le=365, description="분석 기간 (거래일 기준)"),
):
    """종목 차트 분석 — 지지/저항 레벨, RSI/MACD/볼린저밴드, 진입·이탈 시그널"""
    from services.outlook import lookup_stock_master

    stock_name = None
    master = lookup_stock_master(code)
    if master:
        stock_name = master.get("corp_name")

    try:
        return analyze_chart(stock_code=code, stock_name=stock_name, period_days=days)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.exception("chart analysis failed for %s", code)
        raise HTTPException(status_code=500, detail=f"차트 분석 오류: {exc}")


@app.get("/watchlist", response_model=list[WatchlistItemResponse])
def get_watchlist(
    codes: str = Query(..., description="콤마 구분 종목코드 목록 (최대 30)"),
):
    """관심종목 멀티 시세 조회."""
    code_list = [c.strip() for c in codes.split(",") if c.strip()][:30]
    if not code_list:
        raise HTTPException(status_code=422, detail="codes 파라미터가 비어 있습니다")

    name_map: dict[str, str] = {}
    for code in code_list:
        master = lookup_stock_master(code)
        if master:
            name_map[code] = master["corp_name"]

    items = fetch_multi_price(code_list, name_map)
    return [
        WatchlistItemResponse(
            stock_code=item.stock_code,
            stock_name=item.stock_name,
            price=item.price,
            change=item.change,
            change_rate=item.change_rate,
            volume=item.volume,
            trade_value=item.trade_value,
        )
        for item in items
    ]


@app.websocket("/ws/watchlist")
async def ws_watchlist(websocket: WebSocket, codes: str = Query(...)):
    """관심종목 실시간 체결가 스트림 (KIS WebSocket relay)."""
    await websocket.accept()
    code_list = [c.strip() for c in codes.split(",") if c.strip()][:40]
    if not code_list:
        await websocket.close(code=1008)
        return

    try:
        async for tick in stream_prices(code_list):
            try:
                await websocket.send_json(tick)
            except WebSocketDisconnect:
                break
            except Exception:
                break
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("ws_watchlist 오류: %s", exc)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@app.get("/technical/indicators")
def get_technical_indicators():
    return {"indicators": list_indicator_definitions()}


@app.get("/technical/indicators/{code}")
def get_stock_technical_indicators(
    code: str,
    ids: str | None = Query(None, description="Comma-separated indicator ids. Defaults to all."),
    days: int = Query(260, ge=30, le=1000, description="Daily candle lookback window."),
):
    indicator_ids = [item.strip() for item in ids.split(",") if item.strip()] if ids else None
    return calculate_indicators(code, indicator_ids=indicator_ids, days=days)
