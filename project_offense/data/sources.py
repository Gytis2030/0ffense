from __future__ import annotations

import pandas as pd

from project_offense.data.provider import LocalCSVDataProvider, SyntheticDemoDataProvider
from project_offense.data.validation import PriceData


def read_price_csv(path: str) -> PriceData:
    """Legacy-compatible CSV loader returning unvalidated PriceData.

    Production callers must pass the result through validate_price_data()
    before run_backtest().
    """
    return LocalCSVDataProvider(path).load()


def download_yfinance(symbols: list[str], start: str, end: str | None = None) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("Install optional data dependency with: pip install -e '.[data]'") from exc

    data = yf.download(symbols, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(data.columns, pd.MultiIndex):
        prices = data["Close"]
    else:
        prices = data[["Close"]].rename(columns={"Close": symbols[0]})
    return prices.dropna(how="all").sort_index()


def make_demo_prices(
    symbols: list[str] | None = None,
    benchmark: str = "SPY",
    start: str = "2015-01-01",
    periods: int = 2600,
    seed: int = 7,
) -> PriceData:
    """Synthetic demo data for smoke tests only.

    The returned PriceData is intentionally unvalidated and synthetic. It must
    be validated with allow_synthetic=True before run_backtest() accepts it.
    """
    return SyntheticDemoDataProvider(benchmark=benchmark, start=start, periods=periods, seed=seed).load(symbols)
