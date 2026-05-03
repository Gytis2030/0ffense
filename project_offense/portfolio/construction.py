from __future__ import annotations

import pandas as pd


def cap_and_redistribute(raw_weights: pd.Series, max_weight: float) -> pd.Series:
    weights = raw_weights.copy().astype(float)
    if weights.empty or weights.sum() <= 0:
        return weights * 0.0
    weights = weights / weights.sum()
    capped = pd.Series(False, index=weights.index)
    for _ in range(len(weights) + 1):
        over = (weights > max_weight) & ~capped
        if not over.any():
            break
        weights.loc[over] = max_weight
        capped.loc[over] = True
        remaining = ~capped
        budget = 1.0 - weights.loc[capped].sum()
        if not remaining.any() or budget <= 0:
            weights.loc[remaining] = 0.0
            break
        base = raw_weights.loc[remaining].clip(lower=0)
        weights.loc[remaining] = budget * base / base.sum()
    return weights.clip(upper=max_weight)


def inverse_vol_weights(
    scores: pd.Series,
    volatility: pd.Series,
    top_n: int = 5,
    max_weight: float = 0.20,
    exposure: float = 1.0,
) -> pd.Series:
    valid = pd.concat([scores.rename("score"), volatility.rename("vol")], axis=1).dropna()
    valid = valid[valid["vol"] > 0]
    selected = valid.sort_values("score", ascending=False).head(top_n)
    if selected.empty:
        return pd.Series(0.0, index=scores.index)
    weights = cap_and_redistribute(1.0 / selected["vol"], max_weight=max_weight)
    result = pd.Series(0.0, index=scores.index)
    result.loc[weights.index] = weights * exposure
    return result
