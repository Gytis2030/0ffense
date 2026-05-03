from __future__ import annotations

import numpy as np
import pandas as pd


def read_price_csv(path: str) -> pd.DataFrame:
    prices = pd.read_csv(path, index_col=0, parse_dates=True).sort_index()
    return prices.astype(float)


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
) -> pd.DataFrame:
    symbols = symbols or ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "JPM", "XLV"]
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, periods=periods)
    all_symbols = symbols + [benchmark]
    drift = np.linspace(0.00018, 0.00045, len(all_symbols))
    vol = np.linspace(0.012, 0.022, len(all_symbols))
    shocks = rng.normal(drift, vol, size=(periods, len(all_symbols)))
    market = rng.normal(0.00025, 0.009, size=(periods, 1))
    returns = shocks * 0.55 + market * 0.45
    prices = 100 * np.exp(np.cumsum(returns, axis=0))
    return pd.DataFrame(prices, index=dates, columns=all_symbols)
