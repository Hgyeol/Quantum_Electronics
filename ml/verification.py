"""Dataset verification against the signal-learning PRD success criteria."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ml.dataset import FEATURE_COLUMNS, LABEL_COLUMNS


@dataclass
class VerificationIssue:
    code: str
    message: str
    severity: str = "error"


@dataclass
class VerificationResult:
    ok: bool
    rows: int
    stock_count: int
    date_count: int
    start_date: str | None
    end_date: str | None
    issues: list[VerificationIssue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "rows": self.rows,
            "stock_count": self.stock_count,
            "date_count": self.date_count,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "issues": [issue.__dict__ for issue in self.issues],
        }


def _issue(code: str, message: str, severity: str = "error") -> VerificationIssue:
    return VerificationIssue(code=code, message=message, severity=severity)


def verify_labeled_dataset(
    dataset: pd.DataFrame,
    min_calendar_days: int = 90,
    min_stocks: int = 3,
) -> VerificationResult:
    issues: list[VerificationIssue] = []
    required = FEATURE_COLUMNS + LABEL_COLUMNS
    missing = [column for column in required if column not in dataset.columns]
    if missing:
        issues.append(_issue("missing_columns", f"Dataset is missing required columns: {missing}"))

    if "date" not in dataset.columns or "stock_code" not in dataset.columns:
        return VerificationResult(
            ok=False,
            rows=len(dataset),
            stock_count=0,
            date_count=0,
            start_date=None,
            end_date=None,
            issues=issues,
        )

    checked = dataset.copy()
    checked["date"] = pd.to_datetime(checked["date"], errors="coerce")
    invalid_dates = int(checked["date"].isna().sum())
    if invalid_dates:
        issues.append(_issue("invalid_dates", f"{invalid_dates} rows have invalid dates"))

    duplicates = checked.duplicated(subset=["date", "stock_code"]).sum()
    if duplicates:
        issues.append(_issue("duplicate_rows", f"{int(duplicates)} duplicate date/stock_code rows found"))

    stock_count = int(checked["stock_code"].nunique())
    if stock_count < min_stocks:
        issues.append(_issue("too_few_stocks", f"Dataset has {stock_count} stocks; expected at least {min_stocks}"))

    valid_dates = checked["date"].dropna()
    date_count = int(valid_dates.nunique())
    start_date = valid_dates.min().date().isoformat() if not valid_dates.empty else None
    end_date = valid_dates.max().date().isoformat() if not valid_dates.empty else None
    calendar_days = (valid_dates.max() - valid_dates.min()).days + 1 if len(valid_dates) else 0
    if calendar_days < min_calendar_days:
        issues.append(
            _issue(
                "insufficient_history",
                f"Dataset spans {calendar_days} calendar days; expected at least {min_calendar_days}",
            )
        )

    for column in ["next_day_return", "target_up"]:
        if column in checked.columns and checked[column].isna().any():
            issues.append(_issue("missing_labels", f"{column} contains missing values"))

    if "target_up" in checked.columns:
        classes = set(pd.to_numeric(checked["target_up"], errors="coerce").dropna().astype(int).unique())
        if not {0, 1}.issubset(classes):
            issues.append(_issue("single_class_target", "target_up must contain both 0 and 1 classes"))

    return VerificationResult(
        ok=not any(issue.severity == "error" for issue in issues),
        rows=len(checked),
        stock_count=stock_count,
        date_count=date_count,
        start_date=start_date,
        end_date=end_date,
        issues=issues,
    )
