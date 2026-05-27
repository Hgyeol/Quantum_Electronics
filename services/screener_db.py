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


def log_collection(collected_at: str, stock_count: int, duration_sec: float) -> None:
    with closing(get_conn()) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO collect_log (collected_at, stock_count, duration_sec)
               VALUES (?, ?, ?)""",
            (collected_at, stock_count, duration_sec),
        )


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


def get_latest_price_date() -> str | None:
    """daily_price 전체에서 가장 최근 날짜 반환."""
    with closing(get_conn()) as conn:
        row = conn.execute("SELECT MAX(date) AS d FROM daily_price").fetchone()
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
