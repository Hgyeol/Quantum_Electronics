"""Technical indicator catalog and calculation service.

This layer exposes KIS strategy-builder indicators without changing the
existing quant signal engine.
"""

from __future__ import annotations

import inspect
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from analysis.models import AnalysisError

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_STRATEGY_TOOLS = _PROJECT_ROOT / "tools" / "strategy"
if str(_STRATEGY_TOOLS) not in sys.path:
    sys.path.insert(0, str(_STRATEGY_TOOLS))

from core import data_fetcher, indicators  # noqa: E402


_DEFAULT_PARAM_OVERRIDES: dict[str, dict[str, Any]] = {
    "ma": {"period": 20},
    "std": {"period": 20},
    "returns": {"period": 20},
    "high_since": {"days": 20},
    "low_since": {"days": 20},
}

_CATEGORY_BY_ID: list[tuple[set[str], str]] = [
    (
        {
            "ma",
            "ema",
            "bb_middle",
            "hma",
            "dema",
            "tema",
            "kama",
            "alma",
            "lwma",
            "trima",
            "t3",
            "zlema",
            "wma",
            "frama",
            "vidya",
        },
        "moving_average",
    ),
    (
        {
            "returns",
            "daily_change",
            "momentum",
            "roc",
            "rsi",
            "macd",
            "macd_signal",
            "macd_histogram",
            "stochastic_k",
            "stochastic_d",
            "stochrsi",
            "cci",
            "williams_r",
            "mfi",
            "apo",
            "ppo",
            "cmo",
            "ao",
            "cho",
            "ultosc",
            "trix",
            "tsi",
            "rvi",
            "dpo",
            "kvo",
            "kst",
            "coppock",
            "schaff",
            "fisher",
        },
        "oscillator",
    ),
    (
        {
            "volatility",
            "atr",
            "natr",
            "bb_upper",
            "bb_lower",
            "bb_width",
            "bb_percent",
            "keltner_upper",
            "keltner_lower",
            "donchian_upper",
            "donchian_lower",
            "variance",
            "accbands_upper",
            "accbands_lower",
            "mass_index",
        },
        "volatility",
    ),
    (
        {
            "adx",
            "adxr",
            "aroon_up",
            "aroon_down",
            "supertrend",
            "sar",
            "ichimoku_tenkan",
            "ichimoku_kijun",
            "vortex_plus",
            "vortex_minus",
            "chop",
            "regression_slope",
            "regression_intercept",
        },
        "trend",
    ),
    (
        {
            "obv",
            "volume_ma",
            "vwap",
            "cmf",
            "ad",
            "adl",
            "force",
            "vwma",
            "eom",
        },
        "volume",
    ),
    (
        {
            "consecutive_days",
            "strong_close_ratio",
            "high_since",
            "low_since",
            "latest_close",
            "prev_close",
            "disparity",
            "beta",
            "alpha",
            "midpoint",
            "midprice",
            "logr",
            "bop",
            "pivot",
            "augen",
        },
        "price",
    ),
]


@dataclass(frozen=True)
class IndicatorParameter:
    name: str
    default: Any
    required: bool = False


@dataclass(frozen=True)
class IndicatorDefinition:
    id: str
    label: str
    function_name: str
    category: str
    parameters: list[IndicatorParameter] = field(default_factory=list)
    uses_benchmark: bool = False


@dataclass
class IndicatorValue:
    id: str
    label: str
    category: str
    value: Any
    series: list[dict[str, Any]]
    parameters: dict[str, Any]
    uses_default_benchmark: bool = False
    error: str | None = None


@dataclass
class IndicatorCalculationResult:
    stock_code: str
    days: int
    indicators: list[IndicatorValue] = field(default_factory=list)
    errors: list[AnalysisError] = field(default_factory=list)


def list_indicator_definitions() -> list[IndicatorDefinition]:
    definitions = []
    for name, fn in inspect.getmembers(indicators, inspect.isfunction):
        if not (name.startswith("calc_") or name.startswith("get_")):
            continue
        indicator_id = _indicator_id(name)
        definitions.append(_build_definition(indicator_id, name, fn))
    return sorted(definitions, key=lambda item: (item.category, item.id))


def calculate_indicators(
    stock_code: str,
    *,
    indicator_ids: list[str] | None = None,
    days: int = 260,
    env_dv: str = "real",
) -> IndicatorCalculationResult:
    days = max(30, min(days, 1000))
    definitions = list_indicator_definitions()
    definition_by_id = {definition.id: definition for definition in definitions}
    selected_ids = indicator_ids or [definition.id for definition in definitions]

    unknown_ids = [indicator_id for indicator_id in selected_ids if indicator_id not in definition_by_id]
    selected = [definition_by_id[indicator_id] for indicator_id in selected_ids if indicator_id in definition_by_id]

    result = IndicatorCalculationResult(stock_code=stock_code, days=days)
    for indicator_id in unknown_ids:
        result.errors.append(
            AnalysisError(
                source="technical_indicators",
                code="unknown_indicator",
                message=f"Unknown indicator id: {indicator_id}",
            )
        )

    df = data_fetcher.get_daily_prices(stock_code, days, env_dv)
    if df.empty:
        result.errors.append(
            AnalysisError(
                source="technical_indicators",
                code="price_data_unavailable",
                message=f"Daily price data is unavailable for {stock_code}",
            )
        )
        return result

    for definition in selected:
        result.indicators.append(_calculate_one(definition, df))
    return result


def _build_definition(indicator_id: str, function_name: str, fn) -> IndicatorDefinition:
    signature = inspect.signature(fn)
    parameters = []
    uses_benchmark = False
    for param in signature.parameters.values():
        if param.name == "df":
            continue
        if param.name == "benchmark":
            uses_benchmark = True
            continue

        override = _DEFAULT_PARAM_OVERRIDES.get(indicator_id, {}).get(param.name)
        has_default = param.default is not inspect.Parameter.empty
        default = override if override is not None else (param.default if has_default else None)
        parameters.append(
            IndicatorParameter(
                name=param.name,
                default=default,
                required=default is None,
            )
        )

    return IndicatorDefinition(
        id=indicator_id,
        label=_label_for(fn, indicator_id),
        function_name=function_name,
        category=_category_for(indicator_id),
        parameters=parameters,
        uses_benchmark=uses_benchmark,
    )


def _calculate_one(definition: IndicatorDefinition, df: pd.DataFrame) -> IndicatorValue:
    fn = getattr(indicators, definition.function_name)
    params = {param.name: param.default for param in definition.parameters if param.default is not None}
    kwargs = dict(params)
    uses_default_benchmark = False
    if definition.uses_benchmark:
        kwargs["benchmark"] = df["close"]
        uses_default_benchmark = True

    try:
        raw_value = fn(df, **kwargs)
        latest, series = _format_output(raw_value, df)
        return IndicatorValue(
            id=definition.id,
            label=definition.label,
            category=definition.category,
            value=latest,
            series=series,
            parameters=params,
            uses_default_benchmark=uses_default_benchmark,
        )
    except Exception as exc:  # noqa: BLE001 - expose per-indicator failures without failing the page.
        return IndicatorValue(
            id=definition.id,
            label=definition.label,
            category=definition.category,
            value=None,
            series=[],
            parameters=params,
            uses_default_benchmark=uses_default_benchmark,
            error=str(exc),
        )


def _format_output(raw_value: Any, df: pd.DataFrame) -> tuple[Any, list[dict[str, Any]]]:
    if isinstance(raw_value, pd.Series):
        tail = raw_value.tail(30)
        dates = df["date"].tail(len(tail)).tolist() if "date" in df else list(range(len(tail)))
        series = [
            {"date": str(date), "value": _clean_number(value)}
            for date, value in zip(dates, tail.tolist(), strict=False)
        ]
        latest = next((point["value"] for point in reversed(series) if point["value"] is not None), None)
        return latest, series
    return _clean_number(raw_value), []


def _clean_number(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, str)):
        return value
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return value
    if math.isnan(as_float) or math.isinf(as_float):
        return None
    return round(as_float, 6)


def _indicator_id(function_name: str) -> str:
    if function_name.startswith("calc_"):
        return function_name.removeprefix("calc_")
    return function_name.removeprefix("get_")


def _label_for(fn, indicator_id: str) -> str:
    doc = inspect.getdoc(fn) or ""
    first_line = doc.splitlines()[0].strip() if doc else ""
    return first_line or indicator_id.replace("_", " ").upper()


def _category_for(indicator_id: str) -> str:
    for ids, category in _CATEGORY_BY_ID:
        if indicator_id in ids:
            return category
    return "other"
