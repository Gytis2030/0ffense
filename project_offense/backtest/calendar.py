from __future__ import annotations

import pandas as pd


def monthly_rebalance_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    if not index.is_monotonic_increasing:
        index = index.sort_values()
    return pd.DatetimeIndex(pd.Series(index, index=index).groupby(index.to_period("M")).first())
