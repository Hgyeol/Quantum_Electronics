"""Evidence normalization helpers."""

from __future__ import annotations

from datetime import datetime

from analysis.models import Evidence


def normalize_evidence(
    evidence: list[Evidence],
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> list[Evidence]:
    seen: set[str] = set()
    normalized: list[Evidence] = []

    for item in evidence:
        if start_date and item.published_at and item.published_at < start_date:
            continue
        if end_date and item.published_at and item.published_at > end_date:
            continue

        key = str(item.url) if item.url else f"{item.kind}:{item.source}:{item.title}"
        if key in seen:
            continue

        seen.add(key)
        normalized.append(item)

    return normalized
