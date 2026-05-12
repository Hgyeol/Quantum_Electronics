"""FastAPI entry point for Quantum Electronics."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI

from analysis.models import OutlookReport
from services.outlook import OutlookQuery, OutlookService

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


def get_outlook_service() -> OutlookService:
    return OutlookService()


@app.get("/health")
def health():
    return {"status": "ok", "service": "quantum-electronics"}


@app.get("/outlook/stock/{code}", response_model=OutlookReport)
def get_stock_outlook(
    code: str,
    stock_name: str | None = None,
    service: OutlookService = Depends(get_outlook_service),
) -> OutlookReport:
    return service.build_report(code, stock_name=stock_name)


@app.post("/outlook/query", response_model=OutlookReport)
def post_outlook_query(
    query: OutlookQuery,
    service: OutlookService = Depends(get_outlook_service),
) -> OutlookReport:
    return service.build_report(query.query, stock_name=query.stock_name)


@app.get("/outlook/market")
def get_market_outlook():
    return {
        "status": "partial",
        "message": "Market-wide outlook is not implemented yet.",
        "reports": [],
    }
