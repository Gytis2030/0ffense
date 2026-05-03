from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from project_offense.backtest.calendar import monthly_rebalance_dates
from project_offense.backtest.costs import trade_costs
from project_offense.backtest.metrics import performance_metrics
from project_offense.config import StrategyConfig
from project_offense.features.indicators import build_features, rolling_max_drawdown, simple_moving_average
from project_offense.portfolio.construction import inverse_vol_weights
from project_offense.reports.orders import build_order_report
from project_offense.signals.ranking import ranking_scores


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    returns: pd.Series
    weights: pd.DataFrame
    trades: pd.DataFrame
    order_report: pd.DataFrame
    metrics: dict[str, float]
    benchmark_returns: pd.Series


def regime_exposure(benchmark_prices: pd.Series, asof_date: pd.Timestamp) -> float:
    hist = benchmark_prices.loc[:asof_date].dropna()
    if len(hist) < 200:
        return 0.0
    exposure = 1.0
    if hist.iloc[-1] < simple_moving_average(hist, 200).iloc[-1]:
        exposure *= 0.50
    if rolling_max_drawdown(hist, 126).iloc[-1] < -0.10:
        exposure *= 0.50
    return exposure


def run_backtest(prices: pd.DataFrame, config: StrategyConfig = StrategyConfig()) -> BacktestResult:
    prices = prices.sort_index().dropna(how="all")
    if config.benchmark_symbol not in prices.columns:
        raise ValueError(f"Benchmark {config.benchmark_symbol!r} is missing from prices.")
    benchmark = prices[config.benchmark_symbol]
    assets = prices.drop(columns=[config.benchmark_symbol])
    asset_returns = assets.pct_change().fillna(0.0)
    benchmark_returns = benchmark.pct_change().fillna(0.0)
    scores = ranking_scores(assets)
    vol_6 = build_features(assets)["vol_6"]
    rebalances = set(monthly_rebalance_dates(prices.index))
    weights = pd.DataFrame(0.0, index=prices.index, columns=assets.columns)
    returns = pd.Series(0.0, index=prices.index, name="strategy_return")
    equity = pd.Series(config.starting_cash, index=prices.index, name="equity")
    current_weights = pd.Series(0.0, index=assets.columns)
    trade_rows = []

    for i, date in enumerate(prices.index):
        if i > 0:
            returns.iloc[i] = float((current_weights * asset_returns.loc[date]).sum())
            equity.iloc[i] = equity.iloc[i - 1] * (1.0 + returns.iloc[i])
        weights.loc[date] = current_weights

        if date in rebalances and i > 0:
            asof_date = prices.index[i - 1]
            target = inverse_vol_weights(
                scores.loc[asof_date],
                vol_6.loc[asof_date],
                top_n=config.top_n,
                max_weight=config.max_position_weight,
                exposure=regime_exposure(benchmark, asof_date),
            ).reindex(assets.columns).fillna(0.0)
            delta = target - current_weights
            executed_costs = trade_costs(delta, float(equity.iloc[i]), config.cost)
            executed_symbols = {cost.symbol for cost in executed_costs}
            current_weights = (current_weights + delta.where(delta.index.isin(executed_symbols), 0.0)).clip(lower=0.0)
            cost_total = sum(cost.total for cost in executed_costs)
            if cost_total:
                returns.iloc[i] -= cost_total / float(equity.iloc[i])
                equity.iloc[i] -= cost_total
            for cost in executed_costs:
                trade_rows.append(
                    {
                        "date": date,
                        "signal_asof_date": asof_date,
                        "symbol": cost.symbol,
                        "trade_value": cost.trade_value,
                        "commission": cost.commission,
                        "slippage": cost.slippage,
                        "total_cost": cost.total,
                        "target_weight": target.loc[cost.symbol],
                    }
                )
            weights.loc[date] = current_weights

    trades = pd.DataFrame(trade_rows)
    return BacktestResult(
        equity,
        returns,
        weights,
        trades,
        build_order_report(current_weights, prices.iloc[-1], float(equity.iloc[-1])),
        performance_metrics(returns.iloc[1:], benchmark_returns.iloc[1:]),
        benchmark_returns,
    )
