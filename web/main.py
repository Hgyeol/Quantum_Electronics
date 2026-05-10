"""FastAPI entry point for Quantum Electronics."""

from __future__ import annotations

from fastapi import Depends, FastAPI

from analysis.models import OutlookReport
from services.outlook import OutlookQuery, OutlookService

app = FastAPI(
    title="Quantum Electronics",
    description="AI-assisted Korean stock investment outlook API",
    version="1.0.0",
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
