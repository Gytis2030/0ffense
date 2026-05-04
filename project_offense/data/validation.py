from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


SUPPORTED_PRICE_TYPES = {"adjusted_close", "total_return", "raw_close"}


class DataValidationError(ValueError):
    """Raised when price data fails the research data contract."""


@dataclass(frozen=True)
class DataMetadata:
    source_name: str
    is_synthetic: bool
    price_type: str
    currency: str
    timezone: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    validated: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    allow_synthetic: bool = False


@dataclass(frozen=True)
class PriceData:
    prices: pd.DataFrame
    metadata: DataMetadata
    validation_result: ValidationResult | None = None


@dataclass(frozen=True)
class DataValidationConfig:
    allow_synthetic: bool = False
    required_price_type: str = "adjusted_close"
    supported_currencies: frozenset[str] = frozenset({"USD"})
    stale_price_days: int = 5
    extreme_daily_return: float = 0.50
    max_gap_days: int = 7


def validate_price_data(price_data: PriceData, config: DataValidationConfig = DataValidationConfig()) -> PriceData:
    metadata = price_data.metadata
    prices = price_data.prices
    _validate_metadata(metadata, config)

    if not isinstance(prices, pd.DataFrame) or prices.empty:
        raise DataValidationError("Price data is empty.")
    if prices.columns.empty:
        raise DataValidationError("Price data has no asset columns.")
    if not isinstance(prices.index, pd.DatetimeIndex):
        raise DataValidationError("Price data index must be a DatetimeIndex.")
    if prices.index.has_duplicates:
        raise DataValidationError("Price data contains duplicate dates.")
    if not prices.index.is_monotonic_increasing:
        raise DataValidationError("Price data dates must be strictly increasing.")
    if prices.isna().any().any():
        raise DataValidationError("Price data contains NaNs.")
    if (prices <= 0).any().any():
        raise DataValidationError("Price data contains non-positive prices.")
    if prices.columns.to_series().duplicated().any():
        raise DataValidationError("Price data contains duplicate ticker columns.")

    if config.max_gap_days > 0:
        gaps = prices.index.to_series().diff().dt.days.iloc[1:]
        long_gaps = gaps[gaps > config.max_gap_days]
        if not long_gaps.empty:
            first_gap_end = long_gaps.index[0].date().isoformat()
            raise DataValidationError(
                f"Price data contains a date gap longer than {config.max_gap_days} calendar days; first gap ends on {first_gap_end}."
            )

    returns = prices.pct_change().iloc[1:]
    if returns.abs().gt(config.extreme_daily_return).any().any():
        raise DataValidationError("Price data contains extreme daily returns.")

    if config.stale_price_days > 1:
        unchanged = prices.eq(prices.shift(1))
        stale = unchanged.rolling(config.stale_price_days, min_periods=config.stale_price_days).sum()
        if stale.ge(config.stale_price_days).any().any():
            raise DataValidationError("Price data contains stale prices.")

    return PriceData(
        prices=prices.copy(),
        metadata=metadata,
        validation_result=ValidationResult(validated=True, warnings=(), errors=(), allow_synthetic=config.allow_synthetic),
    )


def _validate_metadata(metadata: DataMetadata, config: DataValidationConfig) -> None:
    if not metadata.source_name.strip():
        raise DataValidationError("Data metadata source_name is required.")
    if metadata.price_type not in SUPPORTED_PRICE_TYPES:
        raise DataValidationError(f"Unsupported price_type: {metadata.price_type}.")
    if metadata.price_type != config.required_price_type:
        raise DataValidationError(
            f"Price data must be {config.required_price_type}; received {metadata.price_type}."
        )
    currency = metadata.currency.upper()
    if currency not in config.supported_currencies:
        raise DataValidationError(f"Unsupported data currency: {metadata.currency}.")
    if metadata.is_synthetic and not config.allow_synthetic:
        raise DataValidationError("Synthetic data is not allowed unless allow_synthetic=True.")
