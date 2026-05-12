"""Dataset assembly for next-day stock movement learning."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

FEATURE_COLUMNS = [
    "date",
    "stock_code",
    "stock_name",
    "quant_score",
    "ai_score",
    "financial_score",
    "total_rule_score",
    "golden_cross_score",
    "disparity_score",
    "momentum_score",
    "foreign_investor_score",
    "volume_score",
    "llm_direction",
    "llm_score",
    "llm_confidence",
    "financial_revenue_growth_score",
    "financial_margin_score",
    "financial_debt_score",
    "news_count",
    "disclosure_count",
    "financial_evidence_count",
]
PRICE_COLUMNS = ["date", "stock_code", "close"]
LABEL_COLUMNS = ["close", "next_close", "next_day_return", "target_up"]
DIRECTION_MAP = {"negative": -1, "neutral": 0, "positive": 1}


def read_csv(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"stock_code": str})


def _normalize_dates(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    raw_dates = normalized["date"].astype(str).str.strip()
    compact_dates = raw_dates.str.fullmatch(r"\d{8}")
    parsed = pd.to_datetime(raw_dates, errors="coerce")
    if compact_dates.any():
        parsed.loc[compact_dates] = pd.to_datetime(raw_dates.loc[compact_dates], format="%Y%m%d", errors="coerce")
    normalized["date"] = parsed.dt.date
    return normalized


def _validate_columns(df: pd.DataFrame, required: list[str], name: str) -> None:
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"{name} is missing required columns: {missing}")


def validate_feature_rows(features: pd.DataFrame) -> None:
    _validate_columns(features, ["date", "stock_code"], "features")
    duplicated = features.duplicated(subset=["date", "stock_code"])
    if duplicated.any():
        duplicates = features.loc[duplicated, ["date", "stock_code"]].to_dict("records")
        raise ValueError(f"features contains duplicate date/stock_code rows: {duplicates[:5]}")


def attach_next_day_labels(features: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Attach next trading-day close return and binary target labels."""
    validate_feature_rows(features)
    _validate_columns(prices, PRICE_COLUMNS, "prices")

    feature_rows = _normalize_dates(features)
    price_rows = _normalize_dates(prices[PRICE_COLUMNS])
    price_rows = price_rows.sort_values(["stock_code", "date"]).copy()
    price_rows["close"] = pd.to_numeric(price_rows["close"], errors="coerce")
    price_rows["next_close"] = price_rows.groupby("stock_code")["close"].shift(-1)
    price_rows["next_day_return"] = (price_rows["next_close"] - price_rows["close"]) / price_rows["close"]
    price_rows["target_up"] = (price_rows["next_day_return"] > 0).astype(int)

    labeled = feature_rows.merge(
        price_rows[["date", "stock_code", *LABEL_COLUMNS]],
        on=["date", "stock_code"],
        how="left",
    )
    return labeled.dropna(subset=LABEL_COLUMNS).reset_index(drop=True)


def prepare_model_features(dataset: pd.DataFrame, feature_columns: list[str] | None = None) -> pd.DataFrame:
    """Return numeric model features with stable handling for llm_direction."""
    columns = feature_columns or [
        "quant_score",
        "ai_score",
        "financial_score",
        "total_rule_score",
        "golden_cross_score",
        "disparity_score",
        "momentum_score",
        "foreign_investor_score",
        "volume_score",
        "llm_direction",
        "llm_score",
        "llm_confidence",
        "financial_revenue_growth_score",
        "financial_margin_score",
        "financial_debt_score",
        "news_count",
        "disclosure_count",
        "financial_evidence_count",
    ]
    missing = [column for column in columns if column not in dataset.columns]
    if missing:
        raise ValueError(f"dataset is missing model feature columns: {missing}")

    features = dataset[columns].copy()
    if "llm_direction" in features.columns:
        features["llm_direction"] = features["llm_direction"].map(DIRECTION_MAP).fillna(0)
    return features.apply(pd.to_numeric, errors="coerce").fillna(0.0)


def build_labeled_dataset(
    features_csv: str | Path,
    prices_csv: str | Path,
    output_csv: str | Path | None = None,
) -> pd.DataFrame:
    labeled = attach_next_day_labels(read_csv(features_csv), read_csv(prices_csv))
    if output_csv is not None:
        output_path = Path(output_csv)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        labeled.to_csv(output_path, index=False)
    return labeled
