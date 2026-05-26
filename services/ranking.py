"""거래량/거래대금 순위 및 외국인/기관 순매수 순위 서비스."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_VOLUME_RANK_URL = "/uapi/domestic-stock/v1/quotations/volume-rank"
_VOLUME_RANK_TR_ID = "FHPST01710000"

_FOREIGN_INST_URL = "/uapi/domestic-stock/v1/quotations/foreign-institution-total"
_FOREIGN_INST_TR_ID = "FHPTJ04400000"


@dataclass
class RankItem:
    rank: int
    stock_code: str
    stock_name: str
    price: int
    change: int
    change_rate: float
    volume: int
    trade_value: int
    extra_value: int = 0  # 외국인/기관 순매수 수량


def fetch_volume_rank(sort: str = "volume", limit: int = 20) -> list[RankItem]:
    """
    거래량/거래대금 순위 조회.
    sort: "volume" = 거래량순 (FID_BLNG_CLS_CODE=0)
          "amount" = 거래대금순 (FID_BLNG_CLS_CODE=3)
    """
    blng_cls = "0" if sort == "volume" else "3"

    try:
        import kis_auth as ka
    except Exception as exc:
        logger.warning("kis_auth not available: %s", exc)
        return []

    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_COND_SCR_DIV_CODE": "20171",
        "FID_INPUT_ISCD": "0000",
        "FID_DIV_CLS_CODE": "0",
        "FID_BLNG_CLS_CODE": blng_cls,
        "FID_TRGT_CLS_CODE": "111111111",
        "FID_TRGT_EXLS_CLS_CODE": "000000",
        "FID_INPUT_PRICE_1": "0",
        "FID_INPUT_PRICE_2": "0",
        "FID_VOL_CNT": "0",
        "FID_INPUT_DATE_1": "0",
    }

    try:
        res = ka._url_fetch(_VOLUME_RANK_URL, _VOLUME_RANK_TR_ID, "", params)
    except Exception as exc:
        logger.warning("volume_rank call failed: %s", exc)
        return []

    if not res.isOK():
        logger.warning("volume_rank API error")
        return []

    rows = res.getBody().output
    if not isinstance(rows, list):
        rows = [rows]

    items: list[RankItem] = []
    for i, row in enumerate(rows[:limit]):
        try:
            code = (row.get("mksc_shrn_iscd") or "").strip()
            if not code:
                continue
            items.append(RankItem(
                rank=int(row.get("data_rank") or i + 1),
                stock_code=code,
                stock_name=(row.get("hts_kor_isnm") or "").strip(),
                price=int(row.get("stck_prpr") or 0),
                change=int(row.get("prdy_vrss") or 0),
                change_rate=float(row.get("prdy_ctrt") or 0),
                volume=int(row.get("acml_vol") or 0),
                trade_value=int(row.get("acml_tr_pbmn") or 0),
            ))
        except (ValueError, TypeError):
            continue

    return items


def fetch_foreign_institution_rank(investor: str = "foreign", limit: int = 20) -> list[RankItem]:
    """
    외국인/기관 순매수 순위 조회.
    investor: "foreign" = 외국인, "institution" = 기관계
    """
    etc_cls = "1" if investor == "foreign" else "2"
    ntby_qty_key = "frgn_ntby_qty" if investor == "foreign" else "orgn_ntby_qty"

    try:
        import kis_auth as ka
    except Exception as exc:
        logger.warning("kis_auth not available: %s", exc)
        return []

    params = {
        "FID_COND_MRKT_DIV_CODE": "V",
        "FID_COND_SCR_DIV_CODE": "16449",
        "FID_INPUT_ISCD": "0000",
        "FID_DIV_CLS_CODE": "0",       # 수량 정렬
        "FID_RANK_SORT_CLS_CODE": "0",  # 순매수 상위
        "FID_ETC_CLS_CODE": etc_cls,
    }

    try:
        res = ka._url_fetch(_FOREIGN_INST_URL, _FOREIGN_INST_TR_ID, "", params)
    except Exception as exc:
        logger.warning("foreign_institution_rank call failed: %s", exc)
        return []

    if not res.isOK():
        logger.warning("foreign_institution_rank API error")
        return []

    rows = res.getBody().output
    if not isinstance(rows, list):
        rows = [rows]

    items: list[RankItem] = []
    for i, row in enumerate(rows[:limit]):
        try:
            code = (row.get("mksc_shrn_iscd") or "").strip()
            if not code:
                continue
            items.append(RankItem(
                rank=i + 1,
                stock_code=code,
                stock_name=(row.get("hts_kor_isnm") or "").strip(),
                price=int(row.get("stck_prpr") or 0),
                change=int(row.get("prdy_vrss") or 0),
                change_rate=float(row.get("prdy_ctrt") or 0),
                volume=int(row.get("acml_vol") or 0),
                trade_value=0,
                extra_value=int(row.get(ntby_qty_key) or 0),
            ))
        except (ValueError, TypeError):
            continue

    return items
