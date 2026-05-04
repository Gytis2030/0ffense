from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Any

import yaml


REQUIRED_FIELDS = {"ticker", "exchange", "currency", "asset_class", "role", "minimum_trade_size"}
SUPPORTED_CURRENCIES = {"USD"}
TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.-]{0,14}$")


class UniverseValidationError(ValueError):
    """Raised when a universe config is missing required data or has invalid values."""


@dataclass(frozen=True)
class UniverseAsset:
    ticker: str
    exchange: str
    currency: str
    asset_class: str
    role: str
    minimum_trade_size: float


@dataclass(frozen=True)
class Universe:
    assets: tuple[UniverseAsset, ...]

    @property
    def tickers(self) -> tuple[str, ...]:
        return tuple(asset.ticker for asset in self.assets)

    @property
    def tradable_tickers(self) -> tuple[str, ...]:
        return tuple(asset.ticker for asset in self.assets if asset.role != "benchmark")

    def minimum_trade_sizes(self) -> dict[str, float]:
        return {asset.ticker: asset.minimum_trade_size for asset in self.assets}


def load_universe(path: str | Path) -> Universe:
    with Path(path).open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    return validate_universe(raw)


def validate_universe(raw: Any) -> Universe:
    if not isinstance(raw, dict):
        raise UniverseValidationError("Universe config must be a mapping with an 'assets' list.")
    assets_raw = raw.get("assets")
    if not isinstance(assets_raw, list) or not assets_raw:
        raise UniverseValidationError("Universe config must contain a non-empty 'assets' list.")

    seen: set[str] = set()
    assets: list[UniverseAsset] = []
    for index, item in enumerate(assets_raw):
        if not isinstance(item, dict):
            raise UniverseValidationError(f"Asset at index {index} must be a mapping.")
        missing = REQUIRED_FIELDS - set(item)
        if missing:
            fields = ", ".join(sorted(missing))
            raise UniverseValidationError(f"Asset at index {index} is missing required fields: {fields}.")

        ticker = _validate_text(item["ticker"], "ticker", index).upper()
        if ticker in seen:
            raise UniverseValidationError(f"Duplicate ticker in universe: {ticker}.")
        if not TICKER_PATTERN.fullmatch(ticker):
            raise UniverseValidationError(f"Invalid ticker at index {index}: {ticker!r}.")
        seen.add(ticker)

        currency = _validate_text(item["currency"], "currency", index).upper()
        if currency not in SUPPORTED_CURRENCIES:
            raise UniverseValidationError(f"Unsupported currency for {ticker}: {currency}.")

        minimum_trade_size = _validate_minimum_trade_size(item["minimum_trade_size"], ticker)
        assets.append(
            UniverseAsset(
                ticker=ticker,
                exchange=_validate_text(item["exchange"], "exchange", index).upper(),
                currency=currency,
                asset_class=_validate_text(item["asset_class"], "asset_class", index),
                role=_validate_text(item["role"], "role", index),
                minimum_trade_size=minimum_trade_size,
            )
        )

    if not any(asset.role != "benchmark" for asset in assets):
        raise UniverseValidationError("Universe must contain at least one tradable asset.")
    return Universe(tuple(assets))


def _validate_text(value: Any, field: str, index: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UniverseValidationError(f"Asset at index {index} has invalid {field}.")
    return value.strip()


def _validate_minimum_trade_size(value: Any, ticker: str) -> float:
    if isinstance(value, bool):
        raise UniverseValidationError(f"Invalid minimum_trade_size for {ticker}.")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise UniverseValidationError(f"Invalid minimum_trade_size for {ticker}.") from exc
    if parsed <= 0:
        raise UniverseValidationError(f"minimum_trade_size must be positive for {ticker}.")
    return parsed
