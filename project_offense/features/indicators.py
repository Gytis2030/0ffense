from __future__ import annotations

import pandas as pd

TRADING_DAYS_PER_MONTH = 21


def daily_returns(prices: pd.DataFrame) -> pd.DataFrame:
    return prices.pct_change(fill_method=None)


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


def build_features(
    prices: pd.DataFrame,
    *,
    lookback_12m: int = 252,
    skip_recent_month: int = TRADING_DAYS_PER_MONTH,
    lookback_6m: int = 126,
    volatility_lookback: int = 126,
    trend_ma_window: int = 200,
) -> dict[str, pd.DataFrame]:
    return {
        "mom_12_1": momentum(prices, lookback_12m, skip_days=skip_recent_month),
        "mom_6": momentum(prices, lookback_6m),
        "sma_200": simple_moving_average(prices, trend_ma_window),
        "trend_200": (prices > simple_moving_average(prices, trend_ma_window)).astype(float),
        "vol_6": realized_volatility(prices, volatility_lookback),
        "drawdown_6": rolling_max_drawdown(prices, volatility_lookback),
    }
