"""DART single-account financial statement collection helpers.

This module is import-safe: it does not read local CSV files, load secrets, or
call the DART API until a function is called.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd
import requests

from analysis.models import AnalysisError

REPORT_CODES = {
    "11013": "1분기보고서",
    "11012": "반기보고서",
    "11014": "3분기보고서",
    "11011": "사업보고서",
}

ERROR_MESSAGES = {
    "010": "등록되지 않은 키입니다.",
    "011": "사용할 수 없는 키입니다.",
    "012": "접근할 수 없는 IP입니다.",
    "013": "조회된 데이타가 없습니다.",
    "014": "파일이 존재하지 않습니다.",
    "020": "요청 제한을 초과하였습니다.",
    "021": "조회 가능한 회사 개수가 초과하였습니다.",
    "100": "필드의 부적절한 값입니다.",
    "101": "부적절한 접근입니다.",
    "800": "시스템 점검으로 인한 서비스가 중지 중입니다.",
    "900": "정의되지 않은 오류가 발생하였습니다.",
    "901": "사용자 계정의 개인정보 보유기간이 만료되어 사용할 수 없는 키입니다.",
}


@dataclass
class FinancialStatementFetchResult:
    dataframe: pd.DataFrame
    errors: list[AnalysisError] = field(default_factory=list)


def get_dart_api_key(api_key: str | None = None) -> str | None:
    return api_key or os.getenv("DISCLOSURE_CRTFC_KEY") or os.getenv("DART_API_KEY")


def fetch_financial_statements(
    corp_code: str,
    bsns_year: str,
    reprt_code: str,
    api_key: str | None = None,
    timeout: float = 10.0,
    session: Any = requests,
) -> list[dict[str, Any]]:
    dart_key = get_dart_api_key(api_key)
    if not dart_key:
        raise ValueError("DISCLOSURE_CRTFC_KEY is not configured")

    url = "https://opendart.fss.or.kr/api/fnlttSinglAcnt.xml"
    params = {
        "crtfc_key": dart_key,
        "corp_code": corp_code,
        "bsns_year": bsns_year,
        "reprt_code": reprt_code,
    }

    response = session.get(url, params=params, timeout=timeout)
    if response.status_code != 200:
        raise RuntimeError(f"DART HTTP error: {response.status_code}")

    root = ET.fromstring(response.content)
    status = root.findtext("status")
    message = root.findtext("message")
    if status != "000":
        error_desc = ERROR_MESSAGES.get(status or "", "알 수 없는 오류입니다.")
        if status == "013":
            return []
        raise RuntimeError(f"DART API error {status}: {error_desc} ({message})")

    results: list[dict[str, Any]] = []
    for item in root.findall("list"):
        results.append(
            {
                "bsns_year": bsns_year,
                "reprt_code": reprt_code,
                "report_type": REPORT_CODES[reprt_code],
                "rcept_no": item.findtext("rcept_no"),
                "account_nm": item.findtext("account_nm"),
                "fs_div": item.findtext("fs_div"),
                "sj_div": item.findtext("sj_div"),
                "thstrm_nm": item.findtext("thstrm_nm"),
                "thstrm_dt": item.findtext("thstrm_dt"),
                "thstrm_amount": item.findtext("thstrm_amount"),
                "frmtrm_nm": item.findtext("frmtrm_nm"),
                "frmtrm_dt": item.findtext("frmtrm_dt"),
                "frmtrm_amount": item.findtext("frmtrm_amount"),
                "currency": item.findtext("currency"),
            }
        )

    return results


def fetch_all_reports_last_n_years(
    corp_code: str,
    years: int = 2,
    api_key: str | None = None,
    current_year: int | None = None,
) -> FinancialStatementFetchResult:
    dart_key = get_dart_api_key(api_key)
    if not dart_key:
        return FinancialStatementFetchResult(
            dataframe=pd.DataFrame(),
            errors=[
                AnalysisError(
                    source="dart_financial",
                    code="missing_api_key",
                    message="DISCLOSURE_CRTFC_KEY is not configured",
                )
            ],
        )

    base_year = current_year or datetime.now().year
    target_years = [str(base_year - offset) for offset in range(years, 0, -1)]
    rows: list[dict[str, Any]] = []
    errors: list[AnalysisError] = []

    for year in target_years:
        for code in REPORT_CODES:
            try:
                rows.extend(fetch_financial_statements(corp_code, year, code, api_key=dart_key))
            except Exception as exc:
                errors.append(
                    AnalysisError(
                        source="dart_financial",
                        code="fetch_failed",
                        message=f"{year} {REPORT_CODES[code]}: {exc}",
                    )
                )

    return FinancialStatementFetchResult(dataframe=pd.DataFrame(rows), errors=errors)
