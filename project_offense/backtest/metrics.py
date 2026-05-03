from __future__ import annotations

import numpy as np
import pandas as pd


def max_drawdown(equity: pd.Series) -> float:
    return float((equity / equity.cummax() - 1.0).min())


def performance_metrics(strategy_returns: pd.Series, benchmark_returns: pd.Series) -> dict[str, float]:
    aligned = pd.concat([strategy_returns.rename("strategy"), benchmark_returns.rename("benchmark")], axis=1).dropna()
    if aligned.empty:
        raise ValueError("No overlapping strategy and benchmark returns.")
    strategy = aligned["strategy"]
    benchmark = aligned["benchmark"]
    equity = (1.0 + strategy).cumprod()
    years = len(strategy) / 252.0
    active = strategy - benchmark
    tracking_error = float(active.std() * np.sqrt(252))
    downside = strategy[strategy < 0].std() * np.sqrt(252)
    weekly = (1.0 + strategy).resample("W-FRI").prod() - 1.0
    return {
        "CAGR": float(equity.iloc[-1] ** (1 / years) - 1) if years > 0 else 0.0,
        "annualized_volatility": float(strategy.std() * np.sqrt(252)),
        "Sharpe_ratio": float(strategy.mean() / strategy.std() * np.sqrt(252)) if strategy.std() != 0 else 0.0,
        "Sortino_ratio": float(strategy.mean() * 252 / downside) if downside and downside != 0 else 0.0,
        "max_drawdown": max_drawdown(equity),
        "beta_to_benchmark": float(strategy.cov(benchmark) / benchmark.var()) if benchmark.var() != 0 else 0.0,
        "tracking_error": tracking_error,
        "information_ratio": float(active.mean() * 252 / tracking_error) if tracking_error != 0 else 0.0,
        "percentage_negative_weeks": float((weekly < 0).mean()),
        "worst_weekly_return": float(weekly.min()),
    }
