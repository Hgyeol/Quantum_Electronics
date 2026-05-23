"""FastAPI entry point for Quantum Electronics."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from datetime import date

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from analysis.models import OutlookReport
from services.outlook import OutlookService
from services.technical_indicators import calculate_indicators, list_indicator_definitions

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


@app.get("/health")
def health():
    return {"status": "ok", "service": "quantum-electronics"}


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
