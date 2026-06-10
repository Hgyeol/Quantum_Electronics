"""차트 패턴 유사 사례 검색.

사용자가 고른 종목의 특정 구간(종가 시계열) 모양과 유사했던 과거 사례를
전 종목 일봉에서 찾아주고, 각 사례의 "이후 N일 수익률"을 통계로 집계한다.

흐름:
  1. 질의 구간 종가를 z-정규화 (절대 가격이 아닌 '모양'만 비교).
  2. 전 종목 슬라이딩 윈도우(길이 L)를 z-정규화.
  3. 유클리드 거리로 1차 prefilter → 상위 N개 후보.
  4. DTW(Sakoe-Chiba 밴드)로 정밀 재정렬 → 상위 K개.
  5. 각 사례의 이후 horizon일 수익률을 구해 통계(평균/중앙값/상승비율) 산출.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict

import numpy as np

from services.screener_db import get_all_daily_closes, get_closes_between

logger = logging.getLogger(__name__)

_PREFILTER_TOPN = 150       # 유클리드 1차 통과 개수 (DTW 대상)
_PER_STOCK_PREFILTER = 3    # 종목당 유클리드 후보 상한 (편중 방지)
_DTW_BAND_RATIO = 0.15      # Sakoe-Chiba 밴드 폭 (윈도우 길이 대비)


@dataclass
class SimilarCase:
    stock_code: str
    stock_name: str
    start_date: str
    end_date: str
    similarity: float        # 0~100 (높을수록 유사)
    forward_return: float | None  # 이후 horizon일 수익률 (%)
    window_closes: list[float]    # 매칭 구간 종가 (비교 차트용)
    forward_closes: list[float]   # 이후 horizon일 종가 (비교 차트용)


@dataclass
class PatternMatchResult:
    query_stock_code: str
    query_start: str
    query_end: str
    window_length: int
    horizon: int
    metric: str                   # 사용한 유사도 지표 (dtw/pearson/spearman)
    query_closes: list[float]     # 질의 구간 종가 (비교 차트용)
    cases: list[SimilarCase]
    stats: dict


def _znorm(arr: np.ndarray) -> np.ndarray:
    """행 단위 z-정규화. 표준편차 0이면 0 벡터."""
    arr = arr.astype(np.float64)
    mean = arr.mean(axis=-1, keepdims=True)
    std = arr.std(axis=-1, keepdims=True)
    std = np.where(std < 1e-9, 1.0, std)
    return (arr - mean) / std


def _dtw_distance(a: np.ndarray, b: np.ndarray, band: int) -> float:
    """Sakoe-Chiba 밴드 제약 DTW 거리. a, b는 1D, 길이 동일/유사."""
    n, m = len(a), len(b)
    band = max(band, abs(n - m) + 1)
    inf = float("inf")
    prev = np.full(m + 1, inf)
    prev[0] = 0.0
    for i in range(1, n + 1):
        cur = np.full(m + 1, inf)
        j_start = max(1, i - band)
        j_end = min(m, i + band)
        for j in range(j_start, j_end + 1):
            cost = abs(a[i - 1] - b[j - 1])
            cur[j] = cost + min(prev[j], cur[j - 1], prev[j - 1])
        prev = cur
    return float(prev[m])


def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    """피어슨 상관계수 (-1~1). 분산 0이면 0."""
    a = a - a.mean()
    b = b - b.mean()
    denom = np.sqrt((a * a).sum() * (b * b).sum())
    if denom < 1e-12:
        return 0.0
    return float((a * b).sum() / denom)


def _rankdata(x: np.ndarray) -> np.ndarray:
    """평균 순위 (동점은 평균 처리) — scipy 없이 스피어만용."""
    order = x.argsort()
    ranks = np.empty(len(x), dtype=np.float64)
    ranks[order] = np.arange(len(x), dtype=np.float64)
    # 동점 평균 처리
    _, inv, counts = np.unique(x, return_inverse=True, return_counts=True)
    if (counts > 1).any():
        sums = np.zeros(len(counts))
        np.add.at(sums, inv, ranks)
        means = sums / counts
        ranks = means[inv]
    return ranks


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    """스피어만 순위 상관계수 (-1~1)."""
    return _pearson(_rankdata(a), _rankdata(b))


# 측정 지표: distance_fn(작을수록 유사) 또는 corr_fn(클수록 유사)
_METRICS = ("dtw", "pearson", "spearman")


def find_similar_patterns(
    stock_code: str,
    start_date: str,
    end_date: str,
    name_map: dict[str, str],
    horizon: int = 20,
    top_k: int = 10,
    metric: str = "dtw",
    min_similarity: float = 0.0,
) -> PatternMatchResult:
    if metric not in _METRICS:
        raise ValueError(f"metric은 {_METRICS} 중 하나여야 합니다.")

    # ── 1. 질의 구간 ──────────────────────────────────────────────────────────
    query_rows = get_closes_between(stock_code, start_date, end_date)
    query_closes = np.array([c for _, c in query_rows], dtype=np.float64)
    L = len(query_closes)
    if L < 5:
        raise ValueError("질의 구간이 너무 짧습니다 (최소 5거래일 필요).")

    q_norm = _znorm(query_closes.reshape(1, -1))[0]
    q_start = query_rows[0][0]
    q_end = query_rows[-1][0]

    # ── 2. 전 종목 윈도우 prefilter (유클리드) ────────────────────────────────
    all_closes = get_all_daily_closes()
    band = max(2, int(L * _DTW_BAND_RATIO))

    # (euclid_dist, code, win_start_idx, dates, closes_window) 후보 누적
    cand: list[tuple[float, str, int, list[str], np.ndarray]] = []

    for code, series in all_closes.items():
        n = len(series)
        # 윈도우 끝 뒤로 horizon일이 있어야 '이후 수익률' 계산 가능
        if n < L + horizon:
            continue
        closes = np.array([c for _, c in series], dtype=np.float64)
        dates = [d for d, _ in series]

        # 슬라이딩 윈도우 (끝 + horizon 확보 가능한 위치까지)
        last_start = n - L - horizon  # inclusive
        if last_start < 0:
            continue
        win = np.lib.stride_tricks.sliding_window_view(closes, L)[: last_start + 1]
        if win.shape[0] == 0:
            continue
        win_norm = _znorm(win)

        # 질의와 같은 종목·겹치는 구간은 제외 (자기 자신 매칭 방지)
        dists = np.linalg.norm(win_norm - q_norm, axis=1)

        # 종목당 상위 소수만 추려 후보에 누적 (편중·메모리 절약)
        take = min(_PER_STOCK_PREFILTER, len(dists))
        idxs = np.argpartition(dists, take - 1)[:take]
        for i in idxs:
            i = int(i)
            if code == stock_code:
                w_s, w_e = dates[i], dates[i + L - 1]
                # 질의 구간과 날짜가 겹치면 스킵
                if not (w_e < q_start or w_s > q_end):
                    continue
            cand.append((float(dists[i]), code, i, dates, closes))

    q_closes_list = [round(float(x), 2) for x in query_closes]

    if not cand:
        return PatternMatchResult(
            query_stock_code=stock_code, query_start=q_start, query_end=q_end,
            window_length=L, horizon=horizon, metric=metric, query_closes=q_closes_list,
            cases=[], stats=_empty_stats(),
        )

    # 유클리드 상위 N개로 축소
    cand.sort(key=lambda x: x[0])
    cand = cand[:_PREFILTER_TOPN]

    # ── 3. 선택 지표로 정밀 재정렬 ────────────────────────────────────────────
    # scored: (similarity 0~100, code, i, dates, closes). 높을수록 유사.
    raw_dtw: list[tuple[float, str, int, list, np.ndarray]] = []
    scored: list[tuple[float, str, int, list, np.ndarray]] = []
    for _, code, i, dates, closes in cand:
        w = closes[i : i + L]
        w_norm = _znorm(w.reshape(1, -1))[0]
        if metric == "dtw":
            raw_dtw.append((_dtw_distance(q_norm, w_norm, band), code, i, dates, closes))
        elif metric == "pearson":
            corr = _pearson(q_norm, w_norm)
            scored.append((round(max(0.0, corr) * 100, 1), code, i, dates, closes))
        else:  # spearman
            corr = _spearman(q_norm, w_norm)
            scored.append((round(max(0.0, corr) * 100, 1), code, i, dates, closes))

    if metric == "dtw":
        # DTW 거리는 절대 해석이 어려워 후보 내 상대값(0~100)으로 환산
        raw_dtw.sort(key=lambda x: x[0])
        vals = [d for d, *_ in raw_dtw[: max(top_k * 3, 10)]] or [d for d, *_ in raw_dtw]
        d_min, d_max = (min(vals), max(vals)) if vals else (0.0, 1.0)
        span = (d_max - d_min) or 1.0
        for d, code, i, dates, closes in raw_dtw:
            sim = round((1 - (d - d_min) / span) * 100, 1)
            scored.append((sim, code, i, dates, closes))

    scored.sort(key=lambda x: x[0], reverse=True)

    # ── 4. 종목당 1건만, 컷오프 적용, 상위 top_k ──────────────────────────────
    cases: list[SimilarCase] = []
    seen_codes: set[str] = set()
    for similarity, code, i, dates, closes in scored:
        if code in seen_codes:
            continue
        if similarity < min_similarity:
            continue
        seen_codes.add(code)
        end_idx = i + L - 1
        fwd_idx = end_idx + horizon
        fwd_ret = None
        if fwd_idx < len(closes) and closes[end_idx] > 0:
            fwd_ret = round((closes[fwd_idx] / closes[end_idx] - 1) * 100, 2)
        fwd_end = min(fwd_idx + 1, len(closes))  # 이후 horizon일 (있는 만큼)
        cases.append(SimilarCase(
            stock_code=code,
            stock_name=name_map.get(code, code),
            start_date=dates[i],
            end_date=dates[end_idx],
            similarity=similarity,
            forward_return=fwd_ret,
            window_closes=[round(float(x), 2) for x in closes[i : end_idx + 1]],
            forward_closes=[round(float(x), 2) for x in closes[end_idx + 1 : fwd_end]],
        ))
        if len(cases) >= top_k:
            break

    # ── 5. 통계 ───────────────────────────────────────────────────────────────
    stats = _compute_stats([c.forward_return for c in cases if c.forward_return is not None])

    return PatternMatchResult(
        query_stock_code=stock_code, query_start=q_start, query_end=q_end,
        window_length=L, horizon=horizon, metric=metric, query_closes=q_closes_list,
        cases=cases, stats=stats,
    )


def _compute_stats(returns: list[float]) -> dict:
    if not returns:
        return _empty_stats()
    arr = np.array(returns, dtype=np.float64)
    return {
        "count": len(returns),
        "mean": round(float(arr.mean()), 2),
        "median": round(float(np.median(arr)), 2),
        "max": round(float(arr.max()), 2),
        "min": round(float(arr.min()), 2),
        "positive_ratio": round(float((arr > 0).mean()) * 100, 1),
    }


def _empty_stats() -> dict:
    return {"count": 0, "mean": None, "median": None, "max": None, "min": None, "positive_ratio": None}


def result_to_dict(result: PatternMatchResult) -> dict:
    d = asdict(result)
    return d
