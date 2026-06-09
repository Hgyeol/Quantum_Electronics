"""KIS WebSocket real-time price streamer — fan-out 구조."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_KST = timezone(timedelta(hours=9))

_KIS_WS_PROD  = "ws://ops.koreainvestment.com:21000"
_KIS_WS_PAPER = "ws://ops.koreainvestment.com:31000"
_TR_ID = "H0UNCNT0"      # 국내주식 실시간체결가 (통합, KRX+NXT)
_TR_ID_NXT = "H0NXCNT0"  # 국내주식 실시간체결가 (NXT 전용, 8:00-20:00)
_TR_IDS = frozenset({_TR_ID, _TR_ID_NXT})


def _active_tr_id() -> str:
    """KST 현재 시각 기준 활성 TR.
    정규장(9:00~15:30)·그 외 → 통합(H0UNCNT0), NXT 전용 시간대(8~9, 15:30~20) → H0NXCNT0.
    통합과 NXT 틱이 동시에 오면 누적거래대금/거래량이 서로 달라(통합 ↔ NXT 전용) 깜빡이므로,
    한 시간대에는 한 종류의 틱만 클라이언트에 전달한다.
    """
    now = datetime.now(_KST)
    minutes = now.hour * 60 + now.minute
    nxt_only = (8 * 60 <= minutes < 9 * 60) or (15 * 60 + 30 <= minutes < 20 * 60)
    return _TR_ID_NXT if nxt_only else _TR_ID

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


def refresh_approval_key(svr: str = "prod") -> str | None:
    global _cached_approval_key
    _cached_approval_key = None
    return get_approval_key(svr=svr)


def _sub_msg(approval_key: str, code: str, tr_type: str = "1", tr_id: str = _TR_ID) -> str:
    return json.dumps({
        "header": {
            "approval_key": approval_key,
            "custtype": "P",
            "tr_type": tr_type,
            "content-type": "utf-8",
        },
        "body": {"input": {"tr_id": tr_id, "tr_key": code}},
    })


def _parse_tick(raw: str) -> dict | None:
    try:
        if raw[0] not in ("0", "1"):
            return None
        parts = raw.split("|")
        if len(parts) < 4 or parts[1] not in _TR_IDS:
            return None
        fields = parts[3].split("^")
        d = dict(zip(_COLUMNS, fields))
        code = d.get("MKSC_SHRN_ISCD", "").strip()
        if not code:
            return None
        return {
            "_tr_id": parts[1],
            "stock_code": code,
            "price": int(d.get("STCK_PRPR") or 0),
            "change": int(d.get("PRDY_VRSS") or 0),
            "change_rate": float(d.get("PRDY_CTRT") or 0),
            "volume": int(d.get("ACML_VOL") or 0),
            "trade_value": int(d.get("ACML_TR_PBMN") or 0),
            "open": int(d.get("STCK_OPRC") or 0),
            "high": int(d.get("STCK_HGPR") or 0),
            "low": int(d.get("STCK_LWPR") or 0),
            "bsop_date": d.get("BSOP_DATE", ""),
        }
    except Exception:
        return None


class KISConnectionManager:
    """KIS WebSocket 1개로 유지하고 모든 클라이언트에 fan-out."""

    def __init__(self, svr: str = "prod") -> None:
        self._svr = svr
        self._url = _KIS_WS_PROD if svr == "prod" else _KIS_WS_PAPER
        # code -> set of queues
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._subscribed_codes: set[str] = set()
        self._ws = None
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def subscribe(self, codes: list[str]) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            new_codes = []
            for code in codes:
                self._subscribers[code].add(queue)
                if code not in self._subscribed_codes:
                    self._subscribed_codes.add(code)
                    new_codes.append(code)
            # 이미 연결된 WS가 있으면 새 종목만 추가 구독 (통합 + NXT 이중 구독)
            if self._ws and new_codes:
                approval_key = get_approval_key(self._svr)
                if approval_key:
                    for code in new_codes:
                        try:
                            await self._ws.send(_sub_msg(approval_key, code, tr_id=_TR_ID))
                            await asyncio.sleep(0.05)
                            await self._ws.send(_sub_msg(approval_key, code, tr_id=_TR_ID_NXT))
                            await asyncio.sleep(0.05)
                        except Exception:
                            pass
        return queue

    async def unsubscribe(self, codes: list[str], queue: asyncio.Queue) -> None:
        async with self._lock:
            for code in codes:
                self._subscribers[code].discard(queue)
                if not self._subscribers[code]:
                    self._subscribed_codes.discard(code)
                    # 구독자 없는 종목은 KIS에 구독 해제 (통합 + NXT 둘 다)
                    if self._ws:
                        approval_key = get_approval_key(self._svr)
                        if approval_key:
                            for tid in (_TR_ID, _TR_ID_NXT):
                                try:
                                    await self._ws.send(_sub_msg(approval_key, code, tr_type="2", tr_id=tid))
                                except Exception:
                                    pass

    async def _run(self) -> None:
        import websockets

        while True:
            # 구독자가 없으면 대기
            if not self._subscribed_codes:
                await asyncio.sleep(1)
                continue

            approval_key = get_approval_key(self._svr)
            if not approval_key:
                logger.error("approval_key 발급 실패 — 5초 후 재시도")
                await asyncio.sleep(5)
                continue

            logger.info("KIS WS 연결: %s (%d 종목)", self._url, len(self._subscribed_codes))
            try:
                async with websockets.connect(self._url, ping_interval=None) as ws:
                    self._ws = ws
                    # 현재 구독 중인 모든 종목 등록
                    async with self._lock:
                        codes_snapshot = list(self._subscribed_codes)
                    for code in codes_snapshot:
                        await ws.send(_sub_msg(approval_key, code, tr_id=_TR_ID))
                        await asyncio.sleep(0.05)
                        await ws.send(_sub_msg(approval_key, code, tr_id=_TR_ID_NXT))
                        await asyncio.sleep(0.05)

                    async for raw in ws:
                        try:
                            rdic = None
                            if raw[0] not in ("0", "1"):
                                rdic = json.loads(raw)
                                if rdic.get("header", {}).get("tr_id") == "PINGPONG":
                                    await ws.pong(raw)
                                continue
                            tick = _parse_tick(raw)
                            if not tick:
                                continue
                            # 비활성 시장 틱은 버림 (통합 ↔ NXT 누적값 깜빡임 방지)
                            if tick.pop("_tr_id", _TR_ID) != _active_tr_id():
                                continue
                            # 해당 종목 구독자에게 브로드캐스트
                            queues = list(self._subscribers.get(tick["stock_code"], []))
                            for q in queues:
                                try:
                                    q.put_nowait(tick)
                                except asyncio.QueueFull:
                                    pass
                        except Exception as exc:
                            logger.debug("파싱 오류: %s", exc)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("KIS WS 연결 오류: %s", exc)
                global _cached_approval_key
                _cached_approval_key = None
            finally:
                self._ws = None

            await asyncio.sleep(2)  # 재연결 전 대기


# 싱글톤 매니저
_manager: KISConnectionManager | None = None


def get_manager(svr: str = "prod") -> KISConnectionManager:
    global _manager
    if _manager is None:
        _manager = KISConnectionManager(svr=svr)
    return _manager
