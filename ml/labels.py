"""Label helpers for return prediction datasets."""

from __future__ import annotations

import pandas as pd


def add_next_day_return_labels(prices: pd.DataFrame) -> pd.DataFrame:
    labeled = prices.copy()
    labeled["date"] = pd.to_datetime(labeled["date"]).dt.date
    labeled = labeled.sort_values(["stock_code", "date"]).reset_index(drop=True)
    labeled["close"] = pd.to_numeric(labeled["close"], errors="coerce")
    labeled["next_close"] = labeled.groupby("stock_code")["close"].shift(-1)
    labeled["next_day_return"] = (labeled["next_close"] - labeled["close"]) / labeled["close"]
    labeled["target_up"] = (labeled["next_day_return"] > 0).astype(int)
    return labeled
