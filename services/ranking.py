"""거래량/거래대금 순위 및 외국인/기관 순매수 순위 서비스."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_VOLUME_RANK_URL = "/uapi/domestic-stock/v1/quotations/volume-rank"
_VOLUME_RANK_TR_ID = "FHPST01710000"

_FOREIGN_INST_URL = "/uapi/domestic-stock/v1/quotations/foreign-institution-total"
_FOREIGN_INST_TR_ID = "FHPTJ04400000"

_FLUCTUATION_RANK_URL = "/uapi/domestic-stock/v1/ranking/fluctuation"
_FLUCTUATION_RANK_TR_ID = "FHPST01700000"

_VOLUME_POWER_URL = "/uapi/domestic-stock/v1/ranking/volume-power"
_VOLUME_POWER_TR_ID = "FHPST01680000"

_NEAR_HIGHLOW_URL = "/uapi/domestic-stock/v1/ranking/near-new-highlow"
_NEAR_HIGHLOW_TR_ID = "FHPST01870000"

_UPPER_LIMIT_URL = "/uapi/domestic-stock/v1/quotations/capture-uplowprice"
_UPPER_LIMIT_TR_ID = "FHKST130000C0"


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
    거래량/거래대금 순위 조회. tr_cont 페이지네이션으로 limit개까지 수집.
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


def fetch_volume_power_rank(limit: int = 50) -> list[RankItem]:
    """체결강도 상위 순위 조회. API: FHPST01680000"""
    try:
        import kis_auth as ka
    except Exception as exc:
        logger.warning("kis_auth not available: %s", exc)
        return []

    params = {
        "fid_trgt_exls_cls_code": "0",
        "fid_cond_mrkt_div_code": "J",
        "fid_cond_scr_div_code": "20168",
        "fid_input_iscd": "0000",
        "fid_div_cls_code": "0",
        "fid_input_price_1": "",
        "fid_input_price_2": "",
        "fid_vol_cnt": "",
        "fid_trgt_cls_code": "0",
    }

    try:
        res = ka._url_fetch(_VOLUME_POWER_URL, _VOLUME_POWER_TR_ID, "", params)
    except Exception as exc:
        logger.warning("volume_power_rank call failed: %s", exc)
        return []

    if not res.isOK():
        logger.warning("volume_power_rank API error")
        return []

    rows = res.getBody().output
    if not isinstance(rows, list):
        rows = [rows] if rows else []

    items: list[RankItem] = []
    for i, row in enumerate(rows[:limit]):
        try:
            code = (row.get("mksc_shrn_iscd") or row.get("stck_shrn_iscd") or "").strip()
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
            ))
        except (ValueError, TypeError):
            continue

    return items


def fetch_near_new_highlow_rank(near_type: str = "high", limit: int = 50) -> list[RankItem]:
    """신고/신저 근접종목 상위. API: FHPST01870000
    near_type: "high" = 신고근접, "low" = 신저근접
    """
    prc_cls = "0" if near_type == "high" else "1"

    try:
        import kis_auth as ka
    except Exception as exc:
        logger.warning("kis_auth not available: %s", exc)
        return []

    params = {
        "fid_aply_rang_vol": "0",
        "fid_cond_mrkt_div_code": "J",
        "fid_cond_scr_div_code": "20187",
        "fid_div_cls_code": "0",
        "fid_input_cnt_1": "0",
        "fid_input_cnt_2": "100",
        "fid_prc_cls_code": prc_cls,
        "fid_input_iscd": "0000",
        "fid_trgt_cls_code": "0",
        "fid_trgt_exls_cls_code": "0",
        "fid_aply_rang_prc_1": "0",
        "fid_aply_rang_prc_2": "1000000",
    }

    try:
        res = ka._url_fetch(_NEAR_HIGHLOW_URL, _NEAR_HIGHLOW_TR_ID, "", params)
    except Exception as exc:
        logger.warning("near_new_highlow_rank call failed: %s", exc)
        return []

    if not res.isOK():
        logger.warning("near_new_highlow_rank API error")
        return []

    rows = res.getBody().output
    if not isinstance(rows, list):
        rows = [rows] if rows else []

    items: list[RankItem] = []
    for i, row in enumerate(rows[:limit]):
        try:
            code = (row.get("stck_shrn_iscd") or row.get("mksc_shrn_iscd") or "").strip()
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
            ))
        except (ValueError, TypeError):
            continue

    return items


def fetch_upper_limit_stocks() -> list[RankItem]:
    """상한가 포착 종목 조회. API: FHKST130000C0"""
    try:
        import kis_auth as ka
    except Exception as exc:
        logger.warning("kis_auth not available: %s", exc)
        return []

    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_COND_SCR_DIV_CODE": "11300",
        "FID_PRC_CLS_CODE": "0",
        "FID_DIV_CLS_CODE": "0",
        "FID_INPUT_ISCD": "0000",
        "FID_TRGT_CLS_CODE": "",
        "FID_TRGT_EXLS_CLS_CODE": "",
        "FID_INPUT_PRICE_1": "",
        "FID_INPUT_PRICE_2": "",
        "FID_VOL_CNT": "",
    }

    try:
        res = ka._url_fetch(_UPPER_LIMIT_URL, _UPPER_LIMIT_TR_ID, "", params)
    except Exception as exc:
        logger.warning("upper_limit_stocks call failed: %s", exc)
        return []

    if not res.isOK():
        logger.warning("upper_limit_stocks API error")
        return []

    rows = res.getBody().output
    if not isinstance(rows, list):
        rows = [rows] if rows else []

    items: list[RankItem] = []
    for i, row in enumerate(rows):
        try:
            code = (row.get("mksc_shrn_iscd") or row.get("stck_shrn_iscd") or "").strip()
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
            ))
        except (ValueError, TypeError):
            continue

    return items


def _fluctuation_rank_from_db(limit: int) -> list[RankItem]:
    """KIS API 대신 screener DB에서 등락률 상위 종목 반환."""
    try:
        from services.screener_db import get_top_fluctuation
        rows = get_top_fluctuation(limit)
    except Exception as exc:
        logger.warning("screener_db fluctuation fallback failed: %s", exc)
        return []
    items: list[RankItem] = []
    for i, row in enumerate(rows):
        items.append(RankItem(
            rank=i + 1,
            stock_code=row["stock_code"],
            stock_name=row["stock_name"],
            price=int(row["price"] or 0),
            change=int(row["change_val"] or 0),
            change_rate=float(row["change_rate"] or 0),
            volume=int(row["volume"] or 0),
            trade_value=0,
        ))
    return items


def fetch_fluctuation_rank(limit: int = 30) -> list[RankItem]:
    """등락률 상위(급등주) 순위 조회. API: FHPST01700000. 빈 응답 시 screener DB 폴백."""
    try:
        import kis_auth as ka
    except Exception as exc:
        logger.warning("kis_auth not available: %s", exc)
        return _fluctuation_rank_from_db(limit)

    params = {
        "fid_rsfl_rate2": "",
        "fid_cond_mrkt_div_code": "J",
        "fid_cond_scr_div_code": "20170",
        "fid_input_iscd": "0000",
        "fid_rank_sort_cls_code": "0000",  # 등락률 상위
        "fid_input_cnt_1": "0",
        "fid_prc_cls_code": "0",
        "fid_input_price_1": "0",
        "fid_input_price_2": "0",
        "fid_vol_cnt": "100000",
        "fid_trgt_cls_code": "0",
        "fid_trgt_exls_cls_code": "0",
        "fid_div_cls_code": "0",
        "fid_rsfl_rate1": "0",
    }

    try:
        res = ka._url_fetch(_FLUCTUATION_RANK_URL, _FLUCTUATION_RANK_TR_ID, "", params)
    except Exception as exc:
        logger.warning("fluctuation_rank call failed: %s", exc)
        return []

    if not res.isOK():
        logger.warning("fluctuation_rank API error — falling back to screener DB")
        return _fluctuation_rank_from_db(limit)

    rows = res.getBody().output
    if not isinstance(rows, list):
        rows = [rows] if rows else []

    items: list[RankItem] = []
    for i, row in enumerate(rows[:limit]):
        try:
            code = (row.get("stck_shrn_iscd") or row.get("mksc_shrn_iscd") or "").strip()
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

    if not items:
        logger.info("fluctuation_rank API returned empty — falling back to screener DB")
        return _fluctuation_rank_from_db(limit)

    return items
