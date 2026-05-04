from __future__ import annotations

import pandas as pd

from project_offense.features.indicators import build_features


def cross_sectional_rank(frame: pd.DataFrame, higher_is_better: bool = True) -> pd.DataFrame:
    return frame.rank(axis=1, pct=True, ascending=not higher_is_better)


def ranking_scores(
    prices: pd.DataFrame,
    *,
    lookback_12m: int = 252,
    skip_recent_month: int = 21,
    lookback_6m: int = 126,
    volatility_lookback: int = 126,
    trend_ma_window: int = 200,
) -> pd.DataFrame:
    features = build_features(
        prices,
        lookback_12m=lookback_12m,
        skip_recent_month=skip_recent_month,
        lookback_6m=lookback_6m,
        volatility_lookback=volatility_lookback,
        trend_ma_window=trend_ma_window,
    )
    score = (
        0.35 * cross_sectional_rank(features["mom_12_1"], True)
        + 0.25 * cross_sectional_rank(features["mom_6"], True)
        + 0.15 * features["trend_200"]
        + 0.15 * cross_sectional_rank(features["vol_6"], False)
        + 0.10 * cross_sectional_rank(features["drawdown_6"], True)
    )
    return score.where(prices.notna())
