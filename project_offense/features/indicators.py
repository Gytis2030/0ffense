from __future__ import annotations

import pandas as pd

TRADING_DAYS_PER_MONTH = 21


def daily_returns(prices: pd.DataFrame) -> pd.DataFrame:
    return prices.pct_change()


def momentum(prices: pd.DataFrame, lookback_days: int, skip_days: int = 0) -> pd.DataFrame:
    end_prices = prices.shift(skip_days)
    start_prices = prices.shift(lookback_days + skip_days)
    return end_prices / start_prices - 1.0


def simple_moving_average(prices: pd.DataFrame | pd.Series, window: int) -> pd.DataFrame | pd.Series:
    return prices.rolling(window=window, min_periods=window).mean()


def realized_volatility(prices: pd.DataFrame, window: int = 126) -> pd.DataFrame:
    return daily_returns(prices).rolling(window=window, min_periods=window).std() * (252**0.5)


def rolling_max_drawdown(prices: pd.DataFrame | pd.Series, window: int = 126) -> pd.DataFrame | pd.Series:
    rolling_peak = prices.rolling(window=window, min_periods=window).max()
    return prices / rolling_peak - 1.0


def build_features(prices: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {
        "mom_12_1": momentum(prices, 252, skip_days=TRADING_DAYS_PER_MONTH),
        "mom_6": momentum(prices, 126),
        "sma_200": simple_moving_average(prices, 200),
        "trend_200": (prices > simple_moving_average(prices, 200)).astype(float),
        "vol_6": realized_volatility(prices, 126),
        "drawdown_6": rolling_max_drawdown(prices, 126),
    }
