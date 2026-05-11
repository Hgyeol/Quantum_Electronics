"""
퀀트 신호 #4: 외인 순매수 (최근 3일 누적)

PRD §4.2
  positive (+2): 외국인 3일 누적 순매수수량 > 0
  negative (-2): 외국인 3일 누적 순매수수량 < 0
  neutral  ( 0): 0 또는 데이터 없음
KIS API: inquire_investor  (tools/domestic_stock/inquire_investor.py)
"""

from __future__ import annotations

import logging
import sys
import os

import pandas as pd

_HERE = os.path.dirname(__file__)
_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, "../.."))
_DOMESTIC_STOCK_ROOT = os.path.join(_PROJECT_ROOT, "tools", "domestic_stock")
for _p in [_PROJECT_ROOT, _DOMESTIC_STOCK_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from inquire_investor import inquire_investor

from quant.models import QuantSignal

logger = logging.getLogger(__name__)

_LOOKBACK_DAYS = 3   # 누적 집계 기간


def _call_inquire_investor(fetch_fn, *, env_dv: str, stock_code: str) -> pd.DataFrame:
    kwargs = {
        "env_dv": env_dv,
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": stock_code,
    }
    if callable(fetch_fn):
        return fetch_fn(**kwargs)
    if hasattr(fetch_fn, "invoke"):
        return fetch_fn.invoke(kwargs)
    if hasattr(fetch_fn, "func") and callable(fetch_fn.func):
        return fetch_fn.func(**kwargs)
    raise TypeError(f"Unsupported KIS inquire_investor callable: {type(fetch_fn).__name__}")


def get_foreign_investor_signal(
    stock_code: str,
    stock_name: str,
    env_dv: str = "real",
) -> QuantSignal:
    """
    외국인 최근 3일 누적 순매수 기반 QuantSignal 반환.

    Args:
        stock_code: 종목코드 (6자리)
        stock_name: 종목명 (로그용)
        env_dv   : 실전/모의 구분 (real | demo)

    Returns:
        QuantSignal (score +2 / -2 / 0)
        value: 3일 누적 외국인 순매수수량
    """
    _neutral = QuantSignal(
        label="외인 순매수 (3일 누적)",
        direction="neutral",
        score=0,
        value=None,
        api_used="inquire_investor",
    )

    try:
        df = _call_inquire_investor(inquire_investor, env_dv=env_dv, stock_code=stock_code)
    except Exception as exc:
        logger.error(f"외인 순매수 조회 오류 ({stock_name}[{stock_code}]): {exc}")
        return _neutral

    if df is None or df.empty or "frgn_ntby_qty" not in df.columns:
        logger.warning(f"외인 순매수 데이터 없음 ({stock_name}[{stock_code}])")
        return _neutral

    # 최근 3행(=3 거래일) 합산
    net_qty = pd.to_numeric(
        df.head(_LOOKBACK_DAYS)["frgn_ntby_qty"], errors="coerce"
    ).fillna(0).sum()

    if net_qty > 0:
        return QuantSignal(
            label="외인 순매수 (3일 누적)",
            direction="positive",
            score=2,
            value=float(net_qty),
            api_used="inquire_investor",
        )
    if net_qty < 0:
        return QuantSignal(
            label="외인 순매수 (3일 누적)",
            direction="negative",
            score=-2,
            value=float(net_qty),
            api_used="inquire_investor",
        )

    return QuantSignal(
        label="외인 순매수 (3일 누적)",
        direction="neutral",
        score=0,
        value=float(net_qty),
        api_used="inquire_investor",
    )
