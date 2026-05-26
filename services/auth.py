"""단일 관리자 계정 세션 인증 헬퍼."""
from __future__ import annotations

import json
import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_WATCHLIST_FILE = _PROJECT_ROOT / "data" / "watchlist.json"


def get_admin_credentials() -> tuple[str, str]:
    return (
        os.getenv("ADMIN_USERNAME", "admin"),
        os.getenv("ADMIN_PASSWORD", "quantum1234"),
    )


def check_admin_credentials(username: str, password: str) -> bool:
    expected_user, expected_pass = get_admin_credentials()
    return username == expected_user and password == expected_pass


def load_watchlist_codes() -> list[str]:
    if not _WATCHLIST_FILE.exists():
        return []
    try:
        data = json.loads(_WATCHLIST_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_watchlist_codes(codes: list[str]) -> None:
    _WATCHLIST_FILE.parent.mkdir(exist_ok=True)
    _WATCHLIST_FILE.write_text(json.dumps(codes, ensure_ascii=False), encoding="utf-8")
