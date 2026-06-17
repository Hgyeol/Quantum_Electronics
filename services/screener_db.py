"""SQLite layer for the screener data pipeline."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

_DB_PATH = Path(__file__).parent.parent / "data" / "screener.db"


def get_conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they don't exist."""
    with closing(get_conn()) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS stocks (
                stock_code TEXT PRIMARY KEY,
                name       TEXT,
                market     TEXT,
                sector     TEXT
            );

            CREATE TABLE IF NOT EXISTS daily_price (
                stock_code TEXT NOT NULL,
                date       TEXT NOT NULL,
                open       INTEGER,
                high       INTEGER,
                low        INTEGER,
                close      INTEGER,
                volume     INTEGER,
                PRIMARY KEY (stock_code, date)
            );

            CREATE TABLE IF NOT EXISTS daily_investor (
                stock_code    TEXT NOT NULL,
                date          TEXT NOT NULL,
                frgn_ntby_qty INTEGER,
                orgn_ntby_qty INTEGER,
                PRIMARY KEY (stock_code, date)
            );

            CREATE TABLE IF NOT EXISTS collect_log (
                collected_at TEXT PRIMARY KEY,
                stock_count  INTEGER,
                duration_sec REAL
            );
        """)


def upsert_stocks(rows: list[dict]) -> None:
    """rows: list of {stock_code, name, market}"""
    if not rows:
        return
    with closing(get_conn()) as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO stocks (stock_code, name, market)
               VALUES (:stock_code, :name, :market)""",
            rows,
        )
        conn.commit()


def upsert_sectors(rows: list[dict]) -> None:
    """rows: list of {stock_code, sector}"""
    if not rows:
        return
    with closing(get_conn()) as conn:
        existing_cols = [
            row[1] for row in conn.execute("PRAGMA table_info(stocks)").fetchall()
        ]
        if "sector" not in existing_cols:
            conn.execute("ALTER TABLE stocks ADD COLUMN sector TEXT")
        conn.executemany(
            "UPDATE stocks SET sector = :sector WHERE stock_code = :stock_code",
            rows,
        )
        conn.commit()


def get_all_sectors() -> list[dict]:
    """업종명 + 종목수 목록 반환 (sector가 있고 daily_price 데이터도 있는 종목 기준)."""
    with closing(get_conn()) as conn:
        rows = conn.execute(
            """SELECT s.sector, COUNT(DISTINCT s.stock_code) AS stock_count
               FROM stocks s
               WHERE s.sector IS NOT NULL AND s.sector != ''
                 AND EXISTS (
                     SELECT 1 FROM daily_price dp WHERE dp.stock_code = s.stock_code
                 )
               GROUP BY s.sector
               ORDER BY s.sector"""
        ).fetchall()
    return [dict(r) for r in rows]


def get_stocks_by_sector(sector: str) -> list[dict]:
    """업종 내 종목 중 daily_price 데이터가 있는 것만 반환."""
    with closing(get_conn()) as conn:
        rows = conn.execute(
            """SELECT s.stock_code, s.name, s.market
               FROM stocks s
               WHERE s.sector = ?
                 AND EXISTS (
                     SELECT 1 FROM daily_price dp WHERE dp.stock_code = s.stock_code
                 )""",
            (sector,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_stock_names() -> dict[str, str]:
    """stock_code → name 전체 반환 (stocks 테이블)."""
    with closing(get_conn()) as conn:
        rows = conn.execute("SELECT stock_code, name FROM stocks").fetchall()
    return {r["stock_code"]: r["name"] for r in rows}


def upsert_prices(rows: list[dict]) -> None:
    """rows: list of {stock_code, date, open, high, low, close, volume}"""
    if not rows:
        return
    with closing(get_conn()) as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO daily_price
               (stock_code, date, open, high, low, close, volume)
               VALUES (:stock_code, :date, :open, :high, :low, :close, :volume)""",
            rows,
        )
        conn.commit()


def upsert_investor(rows: list[dict]) -> None:
    """rows: list of {stock_code, date, frgn_ntby_qty, orgn_ntby_qty}"""
    if not rows:
        return
    with closing(get_conn()) as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO daily_investor
               (stock_code, date, frgn_ntby_qty, orgn_ntby_qty)
               VALUES (:stock_code, :date, :frgn_ntby_qty, :orgn_ntby_qty)""",
            rows,
        )
        conn.commit()


def log_collection(collected_at: str, stock_count: int, duration_sec: float) -> None:
    with closing(get_conn()) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO collect_log (collected_at, stock_count, duration_sec)
               VALUES (?, ?, ?)""",
            (collected_at, stock_count, duration_sec),
        )
        conn.commit()


def get_last_collected() -> str | None:
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT collected_at FROM collect_log ORDER BY collected_at DESC LIMIT 1"
        ).fetchone()
    return row["collected_at"] if row else None


def get_prices(stock_code: str, days: int = 30) -> list[dict]:
    with closing(get_conn()) as conn:
        rows = conn.execute(
            """SELECT date, open, high, low, close, volume
               FROM daily_price
               WHERE stock_code = ?
               ORDER BY date DESC LIMIT ?""",
            (stock_code, days),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def get_investor(stock_code: str, days: int = 10) -> list[dict]:
    with closing(get_conn()) as conn:
        rows = conn.execute(
            """SELECT date, frgn_ntby_qty, orgn_ntby_qty
               FROM daily_investor
               WHERE stock_code = ?
               ORDER BY date DESC LIMIT ?""",
            (stock_code, days),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def get_all_stock_codes() -> list[str]:
    with closing(get_conn()) as conn:
        rows = conn.execute(
            "SELECT DISTINCT stock_code FROM daily_price"
        ).fetchall()
    return [r["stock_code"] for r in rows]


def get_all_daily_closes() -> dict[str, list[tuple[str, float]]]:
    """전 종목 일봉 종가를 {stock_code: [(date, close), ...]} 로 일괄 반환 (날짜 오름차순).

    차트 패턴 매칭처럼 전 종목을 한 번에 스캔하는 용도. 종가가 0 이하인 행은 제외.
    """
    with closing(get_conn()) as conn:
        rows = conn.execute(
            """SELECT stock_code, date, close
               FROM daily_price
               WHERE close > 0
               ORDER BY stock_code, date"""
        ).fetchall()
    out: dict[str, list[tuple[str, float]]] = {}
    for r in rows:
        out.setdefault(r["stock_code"], []).append((r["date"], float(r["close"])))
    return out


def get_closes_between(stock_code: str, start: str, end: str) -> list[tuple[str, float]]:
    """특정 종목의 [start, end] 구간 종가 (날짜 오름차순). 날짜는 YYYYMMDD 또는 YYYY-MM-DD."""
    s = start.replace("-", "")
    e = end.replace("-", "")
    with closing(get_conn()) as conn:
        rows = conn.execute(
            """SELECT date, close FROM daily_price
               WHERE stock_code = ? AND replace(date,'-','') BETWEEN ? AND ? AND close > 0
               ORDER BY date""",
            (stock_code, s, e),
        ).fetchall()
    return [(r["date"], float(r["close"])) for r in rows]


def get_top_fluctuation(limit: int = 30) -> list[dict]:
    """최근 거래일 기준 등락률 상위 종목. KIS API 폴백용."""
    with closing(get_conn()) as conn:
        rows = conn.execute(
            """
            SELECT
                t.stock_code,
                COALESCE(s.name, t.stock_code) AS stock_name,
                t.close  AS price,
                (t.close - p.close) AS change_val,
                ROUND((t.close - p.close) * 100.0 / p.close, 2) AS change_rate,
                t.volume
            FROM daily_price t
            JOIN daily_price p ON t.stock_code = p.stock_code
            LEFT JOIN stocks s ON t.stock_code = s.stock_code
            WHERE t.date = (SELECT MAX(date) FROM daily_price)
              AND p.date = (
                    SELECT MAX(date) FROM daily_price
                    WHERE date < (SELECT MAX(date) FROM daily_price)
                  )
              AND p.close > 0
            ORDER BY change_rate DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_latest_price_date() -> str | None:
    """daily_price 전체에서 가장 최근 날짜 반환."""
    with closing(get_conn()) as conn:
        row = conn.execute("SELECT MAX(date) AS d FROM daily_price").fetchone()
    return row["d"] if row and row["d"] else None


def get_oldest_price_date(stock_code: str) -> str | None:
    """해당 종목의 가장 오래된 가격 데이터 날짜 반환."""
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT MIN(date) AS d FROM daily_price WHERE stock_code = ?",
            (stock_code,),
        ).fetchone()
    return row["d"] if row and row["d"] else None


def has_data_for_date(stock_code: str, date: str) -> bool:
    """price와 investor 둘 다 해당 날짜 데이터가 있으면 True."""
    with closing(get_conn()) as conn:
        p = conn.execute(
            "SELECT 1 FROM daily_price WHERE stock_code=? AND date=? LIMIT 1",
            (stock_code, date),
        ).fetchone()
        i = conn.execute(
            "SELECT 1 FROM daily_investor WHERE stock_code=? AND date=? LIMIT 1",
            (stock_code, date),
        ).fetchone()
    return p is not None and i is not None
