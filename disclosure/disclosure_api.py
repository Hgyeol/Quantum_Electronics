"""DART disclosure search and document text extraction helpers."""

from __future__ import annotations

import os
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from typing import Any

import requests

from analysis.evidence import normalize_evidence
from analysis.models import AnalysisError, Evidence

DART_DISCLOSURE_LIST_URL = "https://opendart.fss.or.kr/api/list.json"
DART_DOCUMENT_URL = "https://opendart.fss.or.kr/api/document.xml"
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class DisclosureSearchResult:
    evidence: list[Evidence] = field(default_factory=list)
    errors: list[AnalysisError] = field(default_factory=list)


@dataclass
class DisclosureDocumentResult:
    text: str | None = None
    error: AnalysisError | None = None


def get_dart_api_key(api_key: str | None = None) -> str | None:
    return api_key or os.getenv("DART_API_KEY") or os.getenv("DISCLOSURE_CRTFC_KEY")


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return None


def search_disclosures(
    corp_code: str,
    bgn_de: str,
    end_de: str,
    api_key: str | None = None,
    page_no: int = 1,
    page_count: int = 10,
    session: Any = requests,
    timeout: float = 10.0,
) -> DisclosureSearchResult:
    dart_key = get_dart_api_key(api_key)
    if not dart_key:
        return DisclosureSearchResult(
            errors=[
                AnalysisError(
                    source="dart_disclosure",
                    code="missing_api_key",
                    message="DART_API_KEY is not configured",
                )
            ]
        )

    response = session.get(
        DART_DISCLOSURE_LIST_URL,
        params={
            "crtfc_key": dart_key,
            "corp_code": corp_code,
            "bgn_de": bgn_de,
            "end_de": end_de,
            "page_no": page_no,
            "page_count": page_count,
        },
        timeout=timeout,
    )
    if response.status_code != 200:
        return DisclosureSearchResult(
            errors=[
                AnalysisError(
                    source="dart_disclosure",
                    code="http_error",
                    message=f"DART disclosure API returned HTTP {response.status_code}",
                )
            ]
        )

    payload = response.json()
    if payload.get("status") not in (None, "000"):
        if payload.get("status") == "013":
            return DisclosureSearchResult()
        return DisclosureSearchResult(
            errors=[
                AnalysisError(
                    source="dart_disclosure",
                    code=str(payload.get("status")),
                    message=str(payload.get("message") or "DART disclosure API error"),
                )
            ]
        )

    evidence = [
        Evidence(
            evidence_id=f"disclosure-{item.get('rcept_no') or idx + 1}",
            kind="disclosure",
            source="DART",
            title=item.get("report_nm") or "Untitled disclosure",
            published_at=_parse_date(item.get("rcept_dt")),
            url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={item.get('rcept_no')}",
            metadata={
                "corp_code": corp_code,
                "corp_name": item.get("corp_name"),
                "rcept_no": item.get("rcept_no"),
                "stock_code": item.get("stock_code"),
            },
        )
        for idx, item in enumerate(payload.get("list", []))
    ]

    return DisclosureSearchResult(evidence=normalize_evidence(evidence))


def download_disclosure_text(
    rcept_no: str,
    api_key: str | None = None,
    session: Any = requests,
    timeout: float = 10.0,
) -> DisclosureDocumentResult:
    dart_key = get_dart_api_key(api_key)
    if not dart_key:
        return DisclosureDocumentResult(
            error=AnalysisError(
                source="dart_disclosure",
                code="missing_api_key",
                message="DART_API_KEY is not configured",
            )
        )

    response = session.get(
        DART_DOCUMENT_URL,
        params={"crtfc_key": dart_key, "rcept_no": rcept_no},
        timeout=timeout,
    )
    if response.status_code != 200:
        return DisclosureDocumentResult(
            error=AnalysisError(
                source="dart_disclosure",
                code="http_error",
                message=f"DART document API returned HTTP {response.status_code}",
            )
        )

    try:
        with zipfile.ZipFile(BytesIO(response.content)) as archive:
            texts = []
            for name in archive.namelist():
                raw = archive.read(name).decode("utf-8", errors="ignore")
                texts.append(_TAG_RE.sub(" ", raw))
    except zipfile.BadZipFile:
        text = response.text if hasattr(response, "text") else response.content.decode("utf-8", errors="ignore")
        return DisclosureDocumentResult(text=_TAG_RE.sub(" ", text).strip() or None)

    return DisclosureDocumentResult(text="\n".join(texts).strip() or None)
