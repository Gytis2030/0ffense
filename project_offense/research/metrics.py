from __future__ import annotations

import numpy as np
import pandas as pd


TRADING_DAYS_PER_YEAR = 252
CALENDAR_DAYS_PER_YEAR = 365.25


def cagr(returns: pd.Series, periods_per_year: int = 252) -> float:
    returns = returns.dropna()
    if returns.empty:
        return 0.0
    total = float((1.0 + returns).prod())
    years = len(returns) / periods_per_year
    return float(total ** (1.0 / years) - 1.0) if years > 0 and total > 0 else 0.0


def cagr_from_equity(equity_curve: pd.Series) -> float:
    """Calculate CAGR from first and last valid net equity values.

    The annualization convention is actual elapsed calendar days divided by
    365.25. This keeps partial-year and multi-year tests tied to the reported
    net equity curve instead of to an intermediate return series.
    """
    equity = equity_curve.dropna()
    if len(equity) < 2:
        return 0.0
    start = float(equity.iloc[0])
    end = float(equity.iloc[-1])
    if start <= 0 or end <= 0:
        return 0.0
    elapsed_days = (pd.Timestamp(equity.index[-1]) - pd.Timestamp(equity.index[0])).days
    if elapsed_days <= 0:
        return 0.0
    years = elapsed_days / CALENDAR_DAYS_PER_YEAR
    return float((end / start) ** (1.0 / years) - 1.0)


def annualized_volatility(returns: pd.Series, periods_per_year: int = 252) -> float:
    returns = returns.dropna()
    return float(returns.std() * np.sqrt(periods_per_year)) if len(returns) > 1 else 0.0


def sharpe_ratio(returns: pd.Series, periods_per_year: int = 252, risk_free_rate: float = 0.0) -> float:
    returns = returns.dropna()
    if len(returns) < 2:
        return 0.0
    period_rf = risk_free_rate / periods_per_year
    excess = returns - period_rf
    vol = excess.std()
    return float(excess.mean() / vol * np.sqrt(periods_per_year)) if pd.notna(vol) and vol != 0 else 0.0


def sortino_ratio(returns: pd.Series, periods_per_year: int = 252, risk_free_rate: float = 0.0) -> float:
    returns = returns.dropna()
    if returns.empty:
        return 0.0
    period_mar = risk_free_rate / periods_per_year
    excess = returns - period_mar
    downside = np.minimum(excess, 0.0)
    downside_deviation = float(np.sqrt(np.mean(np.square(downside))) * np.sqrt(periods_per_year))
    return float(excess.mean() * periods_per_year / downside_deviation) if downside_deviation != 0 else 0.0


def max_drawdown_from_returns(returns: pd.Series) -> float:
    equity = (1.0 + returns.dropna()).cumprod()
    return float((equity / equity.cummax() - 1.0).min()) if not equity.empty else 0.0


def max_drawdown_from_equity(equity_curve: pd.Series) -> float:
    equity = equity_curve.dropna()
    if equity.empty:
        return 0.0
    return float((equity / equity.cummax() - 1.0).min())


def beta_to_benchmark(strategy_returns: pd.Series, benchmark_returns: pd.Series) -> float:
    aligned = _aligned(strategy_returns, benchmark_returns)
    benchmark = aligned["benchmark"]
    return float(aligned["strategy"].cov(benchmark) / benchmark.var()) if benchmark.var() != 0 else 0.0


def tracking_error(strategy_returns: pd.Series, benchmark_returns: pd.Series, periods_per_year: int = 252) -> float:
    aligned = _aligned(strategy_returns, benchmark_returns)
    active = aligned["strategy"] - aligned["benchmark"]
    return float(active.std() * np.sqrt(periods_per_year)) if len(active) > 1 else 0.0


def information_ratio(strategy_returns: pd.Series, benchmark_returns: pd.Series, periods_per_year: int = 252) -> float:
    aligned = _aligned(strategy_returns, benchmark_returns)
    active = aligned["strategy"] - aligned["benchmark"]
    te = tracking_error(strategy_returns, benchmark_returns, periods_per_year)
    return float(active.mean() * periods_per_year / te) if te != 0 else 0.0


def weekly_returns(returns: pd.Series) -> pd.Series:
    return (1.0 + returns).resample("W-FRI").prod() - 1.0


def monthly_returns(returns: pd.Series) -> pd.Series:
    return (1.0 + returns).resample("ME").prod() - 1.0


def rolling_metrics(strategy_returns: pd.Series, benchmark_returns: pd.Series) -> pd.DataFrame:
    aligned = _aligned(strategy_returns, benchmark_returns)
    strategy = aligned["strategy"]
    benchmark = aligned["benchmark"]
    equity = (1.0 + strategy).cumprod()
    rolling_peak = equity.rolling(252, min_periods=20).max()
    benchmark_variance = benchmark.rolling(126, min_periods=40).var().replace(0.0, np.nan)
    return pd.DataFrame(
        {
            "return_3m": equity / equity.shift(63) - 1.0,
            "return_6m": equity / equity.shift(126) - 1.0,
            "return_12m": equity / equity.shift(252) - 1.0,
            "volatility": strategy.rolling(63, min_periods=20).std() * np.sqrt(252),
            "drawdown": equity / rolling_peak - 1.0,
            "beta_to_benchmark": strategy.rolling(126, min_periods=40).cov(benchmark) / benchmark_variance,
        },
        index=aligned.index,
    )


def research_metrics(result) -> dict[str, float]:
    strategy, benchmark = research_return_pair(result)
    weekly = weekly_returns(strategy)
    monthly = monthly_returns(strategy)
    costs = float(result.trades["total_cost"].sum()) if not result.trades.empty and "total_cost" in result.trades else 0.0
    abs_trade_value = result.trades["trade_value"].abs() if not result.trades.empty else pd.Series(dtype=float)
    avg_equity = float(result.equity_curve.mean()) if not result.equity_curve.empty else 0.0
    initial_equity = float(result.equity_curve.iloc[0]) if not result.equity_curve.empty else 0.0
    full_period_cost_drag = float(costs / initial_equity) if initial_equity else 0.0
    years = _elapsed_years(result.equity_curve)
    mdd = max_drawdown_from_equity(result.equity_curve)
    cagr_value = cagr_from_equity(result.equity_curve)
    risk_free_rate = float(getattr(result, "backtest_audit", {}).get("risk_free_rate", 0.0))
    return {
        "CAGR": cagr_value,
        "annualized_volatility": annualized_volatility(strategy),
        "Sharpe_ratio": sharpe_ratio(strategy, risk_free_rate=risk_free_rate),
        "Sortino_ratio": sortino_ratio(strategy, risk_free_rate=risk_free_rate),
        "max_drawdown": mdd,
        "Calmar_ratio": float(cagr_value / abs(mdd)) if mdd < 0 else 0.0,
        "beta_to_benchmark": beta_to_benchmark(strategy, benchmark),
        "tracking_error": tracking_error(strategy, benchmark),
        "information_ratio": information_ratio(strategy, benchmark),
        "hit_rate_vs_benchmark": float((strategy > benchmark).mean()),
        "percentage_negative_weeks": float((weekly < 0).mean()),
        "worst_weekly_return": float(weekly.min()) if not weekly.empty else 0.0,
        "monthly_win_rate": float((monthly > 0).mean()) if not monthly.empty else 0.0,
        "turnover": float(abs_trade_value.sum() / avg_equity) if avg_equity else 0.0,
        "average_trade_size": float(abs_trade_value.mean()) if not abs_trade_value.empty else 0.0,
        "total_cost_drag": full_period_cost_drag,
        "annualized_cost_drag": float(full_period_cost_drag / years) if years > 0 else 0.0,
    }


def research_return_pair(result) -> tuple[pd.Series, pd.Series]:
    """Return strategy and benchmark samples for research metrics.

    Backtest returns intentionally contain an artificial first-day 0.0 return
    because there is no previous equity value. Research metrics exclude that
    first row consistently.
    """
    strategy = exclude_first_artificial_return(result.returns)
    benchmark = result.benchmark_returns.reindex(result.returns.index)
    benchmark = benchmark.loc[strategy.index].dropna()
    strategy = strategy.loc[benchmark.index]
    if strategy.empty or benchmark.empty:
        raise ValueError("No overlapping strategy and benchmark returns after excluding the first artificial return.")
    return strategy, benchmark


def exclude_first_artificial_return(returns: pd.Series) -> pd.Series:
    returns = returns.dropna()
    return returns.iloc[1:]


def _elapsed_years(equity_curve: pd.Series) -> float:
    equity = equity_curve.dropna()
    if len(equity) < 2:
        return 0.0
    elapsed_days = (pd.Timestamp(equity.index[-1]) - pd.Timestamp(equity.index[0])).days
    return float(elapsed_days / CALENDAR_DAYS_PER_YEAR) if elapsed_days > 0 else 0.0


def _aligned(strategy_returns: pd.Series, benchmark_returns: pd.Series) -> pd.DataFrame:
    aligned = pd.concat([strategy_returns.rename("strategy"), benchmark_returns.rename("benchmark")], axis=1).dropna()
    if aligned.empty:
        raise ValueError("No overlapping strategy and benchmark returns.")
    return aligned
