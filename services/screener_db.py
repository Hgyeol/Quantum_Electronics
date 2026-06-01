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
                market     TEXT
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
