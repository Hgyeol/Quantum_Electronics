"""KIS WebSocket real-time price streamer for the watchlist."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator

logger = logging.getLogger(__name__)

_KIS_WS_PROD  = "ws://ops.koreainvestment.com:21000"
_KIS_WS_PAPER = "ws://ops.koreainvestment.com:31000"
_TR_ID = "H0UNCNT0"  # 국내주식 실시간체결가 (통합)

# H0UNCNT0 응답 컬럼 순서 (ccnl_total.py 참조)
_COLUMNS = [
    "MKSC_SHRN_ISCD", "STCK_CNTG_HOUR", "STCK_PRPR",
    "PRDY_VRSS_SIGN", "PRDY_VRSS", "PRDY_CTRT",
    "WGHN_AVRG_STCK_PRC", "STCK_OPRC", "STCK_HGPR", "STCK_LWPR",
    "ASKP1", "BIDP1", "CNTG_VOL", "ACML_VOL", "ACML_TR_PBMN",
    "SELN_CNTG_CSNU", "SHNU_CNTG_CSNU", "NTBY_CNTG_CSNU", "CTTR",
    "SELN_CNTG_SMTN", "SHNU_CNTG_SMTN", "CNTG_CLS_CODE", "SHNU_RATE",
    "PRDY_VOL_VRSS_ACML_VOL_RATE", "OPRC_HOUR", "OPRC_VRSS_PRPR_SIGN",
    "OPRC_VRSS_PRPR", "HGPR_HOUR", "HGPR_VRSS_PRPR_SIGN", "HGPR_VRSS_PRPR",
    "LWPR_HOUR", "LWPR_VRSS_PRPR_SIGN", "LWPR_VRSS_PRPR", "BSOP_DATE",
    "NEW_MKOP_CLS_CODE", "TRHT_YN", "ASKP_RSQN1", "BIDP_RSQN1",
    "TOTAL_ASKP_RSQN", "TOTAL_BIDP_RSQN", "VOL_TNRT",
    "PRDY_SMNS_HOUR_ACML_VOL", "PRDY_SMNS_HOUR_ACML_VOL_RATE",
    "HOUR_CLS_CODE", "MRKT_TRTM_CLS_CODE", "VI_STND_PRC",
]


_cached_approval_key: str | None = None


def get_approval_key(svr: str = "prod") -> str | None:
    global _cached_approval_key
    if _cached_approval_key:
        return _cached_approval_key
    try:
        import kis_auth as ka
        ka.auth_ws(svr=svr)
        key = ka._base_headers_ws.get("approval_key")
        if key:
            _cached_approval_key = key
        return key
    except Exception as exc:
        logger.warning("auth_ws failed: %s", exc)
        return None


def _sub_msg(approval_key: str, code: str, tr_type: str = "1") -> str:
    return json.dumps({
        "header": {
            "approval_key": approval_key,
            "custtype": "P",
            "tr_type": tr_type,
            "content-type": "utf-8",
        },
        "body": {"input": {"tr_id": _TR_ID, "tr_key": code}},
    })


async def stream_prices(
    codes: list[str],
    svr: str = "prod",
) -> AsyncGenerator[dict, None]:
    """
    KIS WebSocket에서 실시간 체결가를 수신해 dict를 yield한다.
    keys: stock_code, price, change, change_rate, volume, trade_value
    """
    import websockets

    approval_key = get_approval_key(svr)
    if not approval_key:
        logger.error("approval_key 발급 실패 — 실시간 스트림 중단")
        return

    url = _KIS_WS_PROD if svr == "prod" else _KIS_WS_PAPER
    logger.info("KIS WS 연결: %s (%d 종목)", url, len(codes))

    try:
        async with websockets.connect(url, ping_interval=None) as ws:
            for code in codes:
                await ws.send(_sub_msg(approval_key, code))
                await asyncio.sleep(0.05)

            async for raw in ws:
                try:
                    if raw[0] in ("0", "1"):
                        parts = raw.split("|")
                        if len(parts) < 4 or parts[1] != _TR_ID:
                            continue
                        fields = parts[3].split("^")
                        d = dict(zip(_COLUMNS, fields))
                        code = d.get("MKSC_SHRN_ISCD", "").strip()
                        if not code:
                            continue
                        yield {
                            "stock_code": code,
                            "price": int(d.get("STCK_PRPR") or 0),
                            "change": int(d.get("PRDY_VRSS") or 0),
                            "change_rate": float(d.get("PRDY_CTRT") or 0),
                            "volume": int(d.get("ACML_VOL") or 0),
                            "trade_value": int(d.get("ACML_TR_PBMN") or 0),
                        }
                    else:
                        rdic = json.loads(raw)
                        if rdic.get("header", {}).get("tr_id") == "PINGPONG":
                            await ws.pong(raw)
                except Exception as exc:
                    logger.debug("파싱 오류: %s | raw=%s", exc, raw[:80])

    except Exception as exc:
        logger.warning("KIS WS 연결 오류: %s", exc)
