"""FastAPI entry point for Quantum Electronics."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from datetime import date

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from pydantic import BaseModel

from analysis.models import OutlookReport
from chart.analyzer import analyze_chart
from chart.models import ChartAnalysis
from services.auth import check_admin_credentials, load_watchlist_codes, save_watchlist_codes
from services.outlook import OutlookService, _build_market_quote, lookup_stock_master, search_stock_master, load_all_stock_names, load_search_priority_from_db
from services.position import _kis_current_price_quote
from services.ranking import fetch_volume_rank, fetch_foreign_institution_rank, fetch_fluctuation_rank, RankItem
from services.screener_conditions import run_screener
from services.screener_db import get_last_collected
from services.technical_indicators import calculate_indicators, list_indicator_definitions
from services.watchlist import WatchlistItem as _WatchlistItem, fetch_multi_price
from services.realtime import get_manager, refresh_approval_key

_DEFAULT_CORS_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"
_SESSION_SECRET = os.getenv("SESSION_SECRET", "quantum-session-secret-change-me")
# 프로덕션(HTTPS)에서는 SESSION_SAME_SITE=none, SESSION_HTTPS_ONLY=true 로 설정
_SESSION_SAME_SITE = os.getenv("SESSION_SAME_SITE", "lax")          # lax | none
_SESSION_HTTPS_ONLY = os.getenv("SESSION_HTTPS_ONLY", "false").lower() in {"1", "true", "yes"}

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
    load_search_priority_from_db()
    svr = os.getenv("KIS_SERVER", "prod")
    app.state.kis_authenticated = initialize_kis_auth()
    if app.state.kis_authenticated:
        try:
            from services.realtime import get_approval_key
            key = get_approval_key(svr=svr)
            if key:
                logger.info("KIS WebSocket approval key 발급 완료")
            else:
                logger.warning("KIS WebSocket approval key 발급 실패")
        except Exception as exc:
            logger.warning("KIS WebSocket auth 실패: %s", exc)
    manager = get_manager(svr=svr)
    manager.start()
    yield
    manager.stop()


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

# SessionMiddleware must be added before CORSMiddleware so CORS headers wrap the session
app.add_middleware(SessionMiddleware, secret_key=_SESSION_SECRET, same_site=_SESSION_SAME_SITE, https_only=_SESSION_HTTPS_ONLY, max_age=60 * 60 * 24 * 7)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


def require_admin(request: Request) -> None:
    if not request.session.get("admin"):
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")


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
    import subprocess
    try:
        sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        sha = "unknown"
    return {"status": "ok", "service": "quantum-electronics", "deploy": sha}


# ── 인증 ─────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/auth/login")
def login(body: LoginRequest, request: Request):
    if not check_admin_credentials(body.username, body.password):
        raise HTTPException(status_code=401, detail="사용자명 또는 비밀번호가 올바르지 않습니다")
    request.session["admin"] = True
    return {"ok": True}


@app.post("/auth/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/auth/me")
def auth_me(request: Request):
    if not request.session.get("admin"):
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")
    return {"authenticated": True}


# ── 관심종목 (서버 저장) ──────────────────────────────────────────────────────

class WatchlistUpdateRequest(BaseModel):
    codes: list[str]


@app.get("/me/watchlist", dependencies=[Depends(require_admin)])
def get_my_watchlist():
    return load_watchlist_codes()


@app.post("/me/watchlist", dependencies=[Depends(require_admin)])
def set_my_watchlist(body: WatchlistUpdateRequest):
    codes = [c.strip() for c in body.codes if c.strip()][:50]
    save_watchlist_codes(codes)
    return {"ok": True, "count": len(codes)}


@app.get("/search", dependencies=[Depends(require_admin)])
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


@app.get("/ranking/volume", response_model=list[RankItemResponse], dependencies=[Depends(require_admin)])
def get_volume_ranking(
    sort: str = Query("volume", description="volume: 거래량순 | amount: 거래대금순"),
    limit: int = Query(30, ge=1, le=30, description="반환 종목 수"),
):
    """거래량/거래대금 순위."""
    if sort not in ("volume", "amount"):
        raise HTTPException(status_code=422, detail="sort must be 'volume' or 'amount'")
    items = fetch_volume_rank(sort=sort, limit=limit)
    return [RankItemResponse(**item.__dict__) for item in items]


@app.get("/ranking/fluctuation", response_model=list[RankItemResponse], dependencies=[Depends(require_admin)])
def get_fluctuation_ranking(
    limit: int = Query(30, ge=1, le=50, description="반환 종목 수"),
):
    """등락률 상위(급등주) 순위."""
    items = fetch_fluctuation_rank(limit=limit)
    return [RankItemResponse(**item.__dict__) for item in items]


@app.get("/ranking/foreign", response_model=list[RankItemResponse], dependencies=[Depends(require_admin)])
def get_foreign_ranking(
    investor: str = Query("foreign", description="foreign: 외국인 | institution: 기관"),
    limit: int = Query(30, ge=1, le=100, description="반환 종목 수"),
):
    """외국인/기관 순매수 순위."""
    if investor not in ("foreign", "institution"):
        raise HTTPException(status_code=422, detail="investor must be 'foreign' or 'institution'")
    items = fetch_foreign_institution_rank(investor=investor, limit=limit)
    return [RankItemResponse(**item.__dict__) for item in items]


@app.get("/", response_class=HTMLResponse)
def indicator_frontend():
    index_path = _PROJECT_ROOT / "web" / "static" / "indicators.html"
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


@app.get("/outlook/stock/{code}", response_model=OutlookReport, dependencies=[Depends(require_admin)])
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


@app.get("/chart/{code}", response_model=ChartAnalysis, dependencies=[Depends(require_admin)])
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


@app.get("/quote/{code}", dependencies=[Depends(require_admin)])
def get_market_quote(code: str):
    """종목 현재가 시세 — 고가·저가·거래량·52W 포함 (전망 보기 없이 즉시 조회)."""
    quote_dict = _kis_current_price_quote(code)
    market_quote = _build_market_quote(quote_dict)
    if market_quote is None:
        raise HTTPException(status_code=404, detail="시세 조회 실패")
    return market_quote


@app.get("/watchlist", response_model=list[WatchlistItemResponse], dependencies=[Depends(require_admin)])
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
    """관심종목 실시간 체결가 스트림 (fan-out)."""
    await websocket.accept()
    code_list = [c.strip() for c in codes.split(",") if c.strip()][:40]
    if not code_list:
        await websocket.close(code=1008)
        return

    manager = get_manager()
    queue = await manager.subscribe(code_list)
    try:
        while True:
            try:
                tick = await asyncio.wait_for(queue.get(), timeout=30)
                await websocket.send_json(tick)
            except asyncio.TimeoutError:
                # 30초간 tick 없으면 ping으로 연결 유지 확인
                await websocket.send_json({"type": "ping"})
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        await manager.unsubscribe(code_list, queue)
        try:
            await websocket.close()
        except Exception:
            pass


@app.get("/technical/indicators", dependencies=[Depends(require_admin)])
def get_technical_indicators():
    return {"indicators": list_indicator_definitions()}


@app.get("/technical/indicators/{code}", dependencies=[Depends(require_admin)])
def get_stock_technical_indicators(
    code: str,
    ids: str | None = Query(None, description="Comma-separated indicator ids. Defaults to all."),
    days: int = Query(260, ge=30, le=1000, description="Daily candle lookback window."),
):
    indicator_ids = [item.strip() for item in ids.split(",") if item.strip()] if ids else None
    return calculate_indicators(code, indicator_ids=indicator_ids, days=days)


# ── Screener ─────────────────────────────────────────────────────────────────

_AVAILABLE_CONDITIONS = ["volume_surge", "golden_cross", "frgn_buy", "orgn_buy"]


class ScreenerResultResponse(BaseModel):
    stock_code: str
    stock_name: str
    close: int
    volume: int
    matched_conditions: list[str]


@app.get("/screener", response_model=list[ScreenerResultResponse], dependencies=[Depends(require_admin)])
def get_screener(
    conditions: str = Query(
        ...,
        description=f"Comma-separated conditions. Available: {', '.join(_AVAILABLE_CONDITIONS)}",
    ),
    volume_threshold: float = Query(2.0, ge=1.0, description="거래량 급등 배수 (기본 2.0 = 20일 평균의 2배)"),
    consecutive_days: int = Query(3, ge=1, le=10, description="외국인/기관 연속 순매수 일수"),
    price_surge_threshold: float = Query(5.0, ge=0.1, description="급등주 등락률 기준 (기본 5%)"),
):
    cond_list = [c.strip() for c in conditions.split(",") if c.strip()]
    if not cond_list:
        raise HTTPException(status_code=422, detail="conditions is required")

    name_map: dict[str, str] = {}
    try:
        name_map = load_all_stock_names()
    except Exception:
        pass

    try:
        results = run_screener(
            conditions=cond_list,
            name_map=name_map,
            volume_threshold=volume_threshold,
            consecutive_days=consecutive_days,
            price_surge_threshold=price_surge_threshold,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return [ScreenerResultResponse(**r.__dict__) for r in results]


@app.get("/screener/status", dependencies=[Depends(require_admin)])
def get_screener_status():
    return {"last_collected": get_last_collected()}
