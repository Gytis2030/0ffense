from __future__ import annotations

from pathlib import Path
from typing import Protocol, Sequence

import numpy as np
import pandas as pd

from project_offense.data.validation import DataMetadata, PriceData


class DataProvider(Protocol):
    def load(self, symbols: Sequence[str] | None = None) -> PriceData:
        """Load daily price data and associated metadata."""


class LocalCSVDataProvider:
    def __init__(
        self,
        path: str | Path,
        *,
        source_name: str = "local_csv",
        is_synthetic: bool = False,
        price_type: str = "adjusted_close",
        currency: str = "USD",
        timezone: str | None = None,
    ) -> None:
        self.path = Path(path)
        self.metadata = DataMetadata(
            source_name=source_name,
            is_synthetic=is_synthetic,
            price_type=price_type,
            currency=currency,
            timezone=timezone,
        )

    def load(self, symbols: Sequence[str] | None = None) -> PriceData:
        prices = pd.read_csv(self.path, index_col=0, parse_dates=True)
        prices = prices.astype(float)
        if symbols is not None:
            missing = sorted(set(symbols) - set(prices.columns))
            if missing:
                raise ValueError(f"CSV is missing requested symbols: {', '.join(missing)}")
            prices = prices.loc[:, list(symbols)]
        return PriceData(prices=prices, metadata=self.metadata)


class SyntheticDemoDataProvider:
    """Synthetic data provider for demos and smoke tests only.

    The generated data is not market data and must not be used for production
    backtests or financial conclusions.
    """

    def __init__(
        self,
        *,
        benchmark: str = "SPY",
        start: str = "2015-01-01",
        periods: int = 2600,
        seed: int = 7,
        currency: str = "USD",
    ) -> None:
        self.benchmark = benchmark
        self.start = start
        self.periods = periods
        self.seed = seed
        self.metadata = DataMetadata(
            source_name="synthetic_demo",
            is_synthetic=True,
            price_type="adjusted_close",
            currency=currency,
            timezone=None,
        )

    def load(self, symbols: Sequence[str] | None = None) -> PriceData:
        symbols = list(symbols or ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "JPM", "XLV"])
        symbols = [symbol for symbol in symbols if symbol != self.benchmark]
        rng = np.random.default_rng(self.seed)
        dates = pd.bdate_range(self.start, periods=self.periods)
        all_symbols = symbols + [self.benchmark]
        drift = np.linspace(0.00018, 0.00045, len(all_symbols))
        vol = np.linspace(0.012, 0.022, len(all_symbols))
        shocks = rng.normal(drift, vol, size=(self.periods, len(all_symbols)))
        market = rng.normal(0.00025, 0.009, size=(self.periods, 1))
        returns = shocks * 0.55 + market * 0.45
        prices = 100 * np.exp(np.cumsum(returns, axis=0))
        frame = pd.DataFrame(prices, index=dates, columns=all_symbols)
        return PriceData(prices=frame, metadata=self.metadata)
