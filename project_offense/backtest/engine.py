from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from project_offense.backtest.calendar import monthly_rebalance_dates
from project_offense.backtest.costs import trade_costs
from project_offense.backtest.metrics import performance_metrics
from project_offense.config import StrategyConfig
from project_offense.data.validation import DataValidationError, PriceData
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
    data_audit: dict[str, object]


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


def run_backtest(price_data: PriceData, config: StrategyConfig = StrategyConfig()) -> BacktestResult:
    if not isinstance(price_data, PriceData):
        raise TypeError("run_backtest() requires validated PriceData. Use run_backtest_unsafe_from_dataframe(..., allow_unsafe=True) only for tests/debugging.")
    _require_validated_price_data(price_data, config)
    return _run_backtest_from_prices(price_data.prices, config, _build_data_audit(price_data, config))


def run_backtest_unsafe_from_dataframe(
    prices: pd.DataFrame,
    config: StrategyConfig = StrategyConfig(),
    *,
    allow_unsafe: bool = False,
) -> BacktestResult:
    """Run a backtest from a raw DataFrame for tests/debugging only.

    This bypasses PriceData metadata and validation. Production research must
    use run_backtest() with validated PriceData.
    """
    if not allow_unsafe:
        raise RuntimeError("Unsafe raw DataFrame backtests are disabled unless allow_unsafe=True.")
    audit = {
        "source_name": "unsafe_dataframe",
        "is_synthetic": None,
        "price_type": None,
        "currency": None,
        "validation_status": "unsafe_bypassed",
        "validation_warnings": ("Raw DataFrame validation was explicitly bypassed.",),
        "validation_errors": (),
    }
    return _run_backtest_from_prices(prices, config, audit)


def _require_validated_price_data(price_data: PriceData, config: StrategyConfig) -> None:
    result = price_data.validation_result
    if result is None or not result.validated:
        raise DataValidationError("run_backtest() requires PriceData returned by validate_price_data().")
    if result.errors:
        raise DataValidationError(f"Validated PriceData contains fatal errors: {'; '.join(result.errors)}")
    if price_data.metadata.is_synthetic and not result.allow_synthetic:
        raise DataValidationError("Synthetic PriceData is not allowed unless it was validated with allow_synthetic=True.")
    if config.benchmark_symbol not in price_data.prices.columns:
        raise ValueError(f"Benchmark {config.benchmark_symbol!r} is missing from validated PriceData.")
    benchmark = price_data.prices[config.benchmark_symbol]
    if benchmark.isna().any():
        raise DataValidationError(f"Benchmark {config.benchmark_symbol!r} contains NaNs after validation.")
    expected_dates = pd.bdate_range(price_data.prices.index.min(), price_data.prices.index.max())
    missing_dates = expected_dates.difference(price_data.prices.index)
    if not missing_dates.empty:
        first_missing = missing_dates[0].date().isoformat()
        raise DataValidationError(
            f"Benchmark {config.benchmark_symbol!r} has missing business dates after validation; first missing date is {first_missing}."
        )


def _build_data_audit(price_data: PriceData, config: StrategyConfig) -> dict[str, object]:
    result = price_data.validation_result
    return {
        "source_name": price_data.metadata.source_name,
        "is_synthetic": price_data.metadata.is_synthetic,
        "price_type": price_data.metadata.price_type,
        "currency": price_data.metadata.currency,
        "timezone": price_data.metadata.timezone,
        "validation_status": "validated" if result and result.validated else "unvalidated",
        "validation_warnings": result.warnings if result else (),
        "validation_errors": result.errors if result else (),
        "benchmark_ticker": config.benchmark_symbol,
        "data_start_date": price_data.prices.index.min().date().isoformat(),
        "data_end_date": price_data.prices.index.max().date().isoformat(),
        "row_count": int(len(price_data.prices)),
        "ticker_count": int(len(price_data.prices.columns)),
    }


def _run_backtest_from_prices(prices: pd.DataFrame, config: StrategyConfig, data_audit: dict[str, object]) -> BacktestResult:
    prices = prices.sort_index().dropna(how="all")
    if config.benchmark_symbol not in prices.columns:
        raise ValueError(f"Benchmark {config.benchmark_symbol!r} is missing from prices.")
    benchmark = prices[config.benchmark_symbol]
    assets = prices.drop(columns=[config.benchmark_symbol])
    if config.active_universe is not None:
        allowed = [ticker for ticker in config.active_universe if ticker in assets.columns]
        missing = sorted(set(config.active_universe) - set(assets.columns) - {config.benchmark_symbol})
        if missing:
            raise ValueError(f"Active universe tickers missing from prices: {', '.join(missing)}")
        if not allowed:
            raise ValueError("Active universe has no tradable tickers in prices.")
        assets = assets.loc[:, allowed]
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
        data_audit,
    )
