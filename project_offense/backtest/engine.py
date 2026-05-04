from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from project_offense.backtest.costs import calculate_trade_cost
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
    backtest_audit: dict[str, object]
    cash_curve: pd.Series
    positions: pd.DataFrame
    skipped_trades: pd.DataFrame
    reconciliation: pd.DataFrame
    skipped_trade_reason_counts: dict[str, int]


@dataclass
class ExecutionAudit:
    leverage_was_attempted: bool = False
    cash_constraint_triggered: bool = False
    orders_resized_due_to_cash: bool = False
    number_of_cash_resized_orders: int = 0
    total_cash_shortfall_before_resizing: float = 0.0


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
    benchmark_returns = price_data.prices[config.benchmark_symbol].pct_change(fill_method=None).iloc[1:]
    if benchmark_returns.isna().any():
        raise DataValidationError(f"Benchmark {config.benchmark_symbol!r} has missing returns after the first row.")
    gaps = price_data.prices.index.to_series().diff().dt.days.iloc[1:]
    long_gaps = gaps[gaps > 7]
    if not long_gaps.empty:
        first_gap_end = long_gaps.index[0].date().isoformat()
        raise DataValidationError(f"Validated PriceData contains a date gap longer than 7 calendar days; first gap ends on {first_gap_end}.")


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
    """Run the backtest using explicit close-to-close timing.

    Timing convention:
    - signal_date is the last available trading day of each calendar month.
    - decision_date is the same as signal_date, after that day's close.
    - execution_date is the next available trading day after decision_date.

    Signals and target weights are computed only from data available at
    signal_date. Trades are executed on execution_date using execution-date
    prices. If an execution price is missing or unusable, that trade is skipped
    and recorded in skipped_trades.
    """
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
    benchmark_returns = _benchmark_returns(benchmark, validated=data_audit.get("validation_status") == "validated")
    scores = ranking_scores(assets)
    vol_6 = build_features(assets)["vol_6"]
    rebalance_plan = _monthly_rebalance_plan(prices.index)
    plan_by_execution: dict[pd.Timestamp, list[tuple[pd.Timestamp, pd.Timestamp]]] = {}
    for signal_date, decision_date, execution_date in rebalance_plan:
        plan_by_execution.setdefault(execution_date, []).append((signal_date, decision_date))

    weights = pd.DataFrame(0.0, index=prices.index, columns=assets.columns)
    returns = pd.Series(0.0, index=prices.index, name="strategy_return")
    equity = pd.Series(config.starting_cash, index=prices.index, name="equity")
    cash_curve = pd.Series(config.starting_cash, index=prices.index, name="cash")
    positions = pd.DataFrame(0.0, index=prices.index, columns=assets.columns)
    shares = pd.Series(0.0, index=assets.columns)
    cash = float(config.starting_cash)
    trade_rows = []
    skipped_rows = []
    execution_audit = ExecutionAudit()
    cash_went_negative = False

    for i, date in enumerate(prices.index):
        current_prices = assets.loc[date]
        before_value = _portfolio_value(cash, shares, current_prices)

        for signal_date, decision_date in plan_by_execution.get(date, []):
            target = inverse_vol_weights(
                scores.loc[signal_date],
                vol_6.loc[signal_date],
                top_n=config.top_n,
                max_weight=config.max_position_weight,
                exposure=regime_exposure(benchmark, signal_date),
            ).reindex(assets.columns).fillna(0.0)
            _validate_target_weights(target, config)
            cash = _execute_rebalance(
                signal_date=signal_date,
                decision_date=decision_date,
                execution_date=date,
                target_weights=target,
                prices=current_prices,
                shares=shares,
                cash=cash,
                portfolio_value=before_value,
                config=config,
                trade_rows=trade_rows,
                skipped_rows=skipped_rows,
                execution_audit=execution_audit,
            )

        end_value = _portfolio_value(cash, shares, current_prices)
        equity.iloc[i] = end_value
        cash_curve.iloc[i] = cash
        positions.loc[date] = shares
        weights.loc[date] = _current_weights(shares, current_prices, end_value)
        if i > 0:
            returns.iloc[i] = end_value / equity.iloc[i - 1] - 1.0 if equity.iloc[i - 1] else 0.0
        if cash < -1e-8:
            cash_went_negative = True
            execution_audit.leverage_was_attempted = True

    trades = pd.DataFrame(trade_rows)
    skipped_trades = pd.DataFrame(skipped_rows)
    skipped_reason_counts = _skipped_reason_counts(skipped_trades)
    reconciliation = _build_reconciliation(cash_curve, positions, assets, equity)
    backtest_audit = _build_backtest_audit(
        config,
        rebalance_plan,
        trades,
        skipped_trades,
        skipped_reason_counts,
        execution_audit,
        cash_went_negative,
    )
    return BacktestResult(
        equity,
        returns,
        weights,
        trades,
        build_order_report(weights.iloc[-1], prices.iloc[-1], float(equity.iloc[-1])),
        performance_metrics(returns.iloc[1:], benchmark_returns.iloc[1:]),
        benchmark_returns,
        data_audit,
        backtest_audit,
        cash_curve,
        positions,
        skipped_trades,
        reconciliation,
        skipped_reason_counts,
    )


def _benchmark_returns(benchmark: pd.Series, *, validated: bool) -> pd.Series:
    returns = benchmark.pct_change(fill_method=None)
    returns.iloc[0] = 0.0
    missing = returns.iloc[1:].isna()
    if validated and missing.any():
        first_missing = missing[missing].index[0].date().isoformat()
        raise DataValidationError(f"Benchmark returns contain missing values after the first row; first missing date is {first_missing}.")
    return returns.fillna(0.0) if not validated else returns


def _monthly_rebalance_plan(index: pd.DatetimeIndex) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    """Return month-end signal/decision dates and next-trading-day executions."""
    month_ends = list(pd.Series(index, index=index).groupby(index.to_period("M")).last())
    plan = []
    for signal_date in month_ends:
        loc = index.get_loc(signal_date)
        if isinstance(loc, slice):
            loc = loc.stop - 1
        if loc + 1 >= len(index):
            continue
        decision_date = signal_date
        execution_date = index[loc + 1]
        plan.append((signal_date, decision_date, execution_date))
    return plan


def _validate_target_weights(target: pd.Series, config: StrategyConfig) -> None:
    if target.lt(-1e-12).any():
        raise ValueError("Target weights cannot be negative.")
    if target.gt(config.max_position_weight + 1e-12).any():
        raise ValueError("Target weights exceed max_position_weight.")
    if float(target.sum()) > 1.0 + 1e-12:
        raise ValueError("Target weights cannot sum above 1.0.")


def _portfolio_value(cash: float, shares: pd.Series, prices: pd.Series) -> float:
    values = shares * prices
    return float(cash + values.dropna().sum())


def _current_weights(shares: pd.Series, prices: pd.Series, equity: float) -> pd.Series:
    if equity <= 0:
        return pd.Series(0.0, index=shares.index)
    return ((shares * prices).fillna(0.0) / equity).clip(lower=0.0)


def _execute_rebalance(
    *,
    signal_date: pd.Timestamp,
    decision_date: pd.Timestamp,
    execution_date: pd.Timestamp,
    target_weights: pd.Series,
    prices: pd.Series,
    shares: pd.Series,
    cash: float,
    portfolio_value: float,
    config: StrategyConfig,
    trade_rows: list[dict[str, object]],
    skipped_rows: list[dict[str, object]],
    execution_audit: ExecutionAudit,
) -> float:
    current_values = (shares * prices).fillna(0.0)
    target_values = target_weights * _investable_value_after_cost_reserve(portfolio_value, config)
    deltas = target_values - current_values
    for symbol, delta_value in deltas[deltas < 0].sort_values().items():
        cash = _execute_order(
            symbol=symbol,
            desired_trade_value=float(delta_value),
            signal_date=signal_date,
            decision_date=decision_date,
            execution_date=execution_date,
            price=prices.get(symbol),
            shares=shares,
            cash=cash,
            config=config,
            trade_rows=trade_rows,
            skipped_rows=skipped_rows,
            target_weight=float(target_weights.loc[symbol]),
            execution_audit=execution_audit,
        )

    for symbol, delta_value in deltas[deltas > 0].sort_values(ascending=False).items():
        cash = _execute_order(
            symbol=symbol,
            desired_trade_value=float(delta_value),
            signal_date=signal_date,
            decision_date=decision_date,
            execution_date=execution_date,
            price=prices.get(symbol),
            shares=shares,
            cash=cash,
            config=config,
            trade_rows=trade_rows,
            skipped_rows=skipped_rows,
            target_weight=float(target_weights.loc[symbol]),
            execution_audit=execution_audit,
        )
    return cash


def _execute_order(
    *,
    symbol: str,
    desired_trade_value: float,
    signal_date: pd.Timestamp,
    decision_date: pd.Timestamp,
    execution_date: pd.Timestamp,
    price: object,
    shares: pd.Series,
    cash: float,
    config: StrategyConfig,
    trade_rows: list[dict[str, object]],
    skipped_rows: list[dict[str, object]],
    target_weight: float,
    execution_audit: ExecutionAudit,
) -> float:
    if pd.isna(price) or float(price) <= 0:
        _log_skip(skipped_rows, signal_date, decision_date, execution_date, symbol, desired_trade_value, "missing_execution_price")
        return cash
    price = float(price)
    side = "BUY" if desired_trade_value > 0 else "SELL"
    if abs(desired_trade_value) < config.cost.min_trade_value:
        _log_skip(skipped_rows, signal_date, decision_date, execution_date, symbol, desired_trade_value, "below_minimum_trade_size")
        return cash

    trade_value = desired_trade_value
    if side == "SELL":
        max_sell_value = float(shares.loc[symbol] * price)
        trade_value = -min(abs(trade_value), max_sell_value)
    else:
        commission, slippage, total_cost = calculate_trade_cost(trade_value, config.cost)
        if trade_value + total_cost > cash:
            shortfall = trade_value + total_cost - cash
            execution_audit.cash_constraint_triggered = True
            execution_audit.orders_resized_due_to_cash = True
            execution_audit.number_of_cash_resized_orders += 1
            execution_audit.total_cash_shortfall_before_resizing += float(max(0.0, shortfall))
            trade_value = _max_affordable_trade_value(cash, config)
            if trade_value < config.cost.min_trade_value:
                _log_skip(skipped_rows, signal_date, decision_date, execution_date, symbol, desired_trade_value, "insufficient_cash")
                return cash
            commission, slippage, total_cost = calculate_trade_cost(trade_value, config.cost)

    commission, slippage, total_cost = calculate_trade_cost(trade_value, config.cost)
    share_delta = trade_value / price
    if not config.allow_fractional_shares:
        if side == "BUY":
            share_delta = float(int(share_delta))
            if share_delta <= 0:
                _log_skip(skipped_rows, signal_date, decision_date, execution_date, symbol, desired_trade_value, "zero_whole_share_quantity")
                return cash
            trade_value = share_delta * price
        else:
            share_delta = -float(int(abs(share_delta)))
            if share_delta == 0:
                _log_skip(skipped_rows, signal_date, decision_date, execution_date, symbol, desired_trade_value, "zero_whole_share_quantity")
                return cash
            trade_value = share_delta * price
        commission, slippage, total_cost = calculate_trade_cost(trade_value, config.cost)
        if side == "BUY" and abs(trade_value) + total_cost > cash:
            affordable_shares = int(_max_affordable_trade_value(cash, config) // price)
            if affordable_shares <= 0:
                _log_skip(skipped_rows, signal_date, decision_date, execution_date, symbol, desired_trade_value, "insufficient_cash")
                return cash
            share_delta = float(affordable_shares)
            trade_value = share_delta * price
            commission, slippage, total_cost = calculate_trade_cost(trade_value, config.cost)
    shares.loc[symbol] += share_delta
    if side == "BUY":
        cash -= abs(trade_value) + total_cost
    else:
        cash += abs(trade_value) - total_cost
    if cash < -1e-8:
        execution_audit.leverage_was_attempted = True

    trade_rows.append(
        {
            "date": execution_date,
            "signal_asof_date": signal_date,
            "signal_date": signal_date,
            "decision_date": decision_date,
            "execution_date": execution_date,
            "symbol": symbol,
            "side": side,
            "trade_value": trade_value,
            "shares": share_delta,
            "price": price,
            "commission": commission,
            "slippage": slippage,
            "total_cost": total_cost,
            "target_weight": target_weight,
        }
    )
    return cash


def _max_affordable_trade_value(cash: float, config: StrategyConfig) -> float:
    if cash <= config.cost.min_commission:
        return 0.0
    rate = config.cost.commission_pct + config.cost.slippage_bps / 10_000.0
    trade_value = (cash - config.cost.min_commission) / (1.0 + rate)
    commission, slippage, total_cost = calculate_trade_cost(trade_value, config.cost)
    if trade_value + total_cost > cash:
        trade_value = max(0.0, trade_value - (trade_value + total_cost - cash))
    return float(max(0.0, trade_value))


def _investable_value_after_cost_reserve(portfolio_value: float, config: StrategyConfig) -> float:
    rate = config.cost.commission_pct + config.cost.slippage_bps / 10_000.0
    fixed_reserve = config.cost.min_commission * max(1, config.top_n)
    return float(max(0.0, (portfolio_value - fixed_reserve) / (1.0 + rate)))


def _log_skip(
    skipped_rows: list[dict[str, object]],
    signal_date: pd.Timestamp,
    decision_date: pd.Timestamp,
    execution_date: pd.Timestamp,
    symbol: str,
    desired_trade_value: float,
    reason: str,
) -> None:
    skipped_rows.append(
        {
            "signal_date": signal_date,
            "decision_date": decision_date,
            "execution_date": execution_date,
            "symbol": symbol,
            "desired_trade_value": desired_trade_value,
            "reason": reason,
        }
    )


def _build_backtest_audit(
    config: StrategyConfig,
    rebalance_plan: list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]],
    trades: pd.DataFrame,
    skipped_trades: pd.DataFrame,
    skipped_reason_counts: dict[str, int],
    execution_audit: ExecutionAudit,
    cash_went_negative: bool,
) -> dict[str, object]:
    skip_reasons = skipped_trades["reason"] if not skipped_trades.empty else pd.Series(dtype=object)
    return {
        "rebalance_frequency": "monthly",
        "timing_convention": "month-end close signal; after-close decision; next-trading-day close execution",
        "benchmark_ticker": config.benchmark_symbol,
        "min_commission": config.cost.min_commission,
        "commission_pct": config.cost.commission_pct,
        "slippage_bps": config.cost.slippage_bps,
        "minimum_trade_size": config.cost.min_trade_value,
        "allow_fractional_shares": config.allow_fractional_shares,
        "benchmark_return_convention": "first benchmark return set to 0.0; missing benchmark returns after first row are fatal in validated runs",
        "number_of_rebalances": len(rebalance_plan),
        "number_of_trades": int(len(trades)),
        "number_of_skipped_trades": int(len(skipped_trades)),
        "number_of_missing_price_skips": int((skip_reasons == "missing_execution_price").sum()),
        "number_of_minimum_trade_size_skips": int((skip_reasons == "below_minimum_trade_size").sum()),
        "skipped_trade_reason_counts": skipped_reason_counts,
        "leverage_was_attempted": execution_audit.leverage_was_attempted,
        "cash_constraint_triggered": execution_audit.cash_constraint_triggered,
        "orders_resized_due_to_cash": execution_audit.orders_resized_due_to_cash,
        "number_of_cash_resized_orders": execution_audit.number_of_cash_resized_orders,
        "total_cash_shortfall_before_resizing": execution_audit.total_cash_shortfall_before_resizing,
        "cash_went_negative": cash_went_negative,
    }


def _skipped_reason_counts(skipped_trades: pd.DataFrame) -> dict[str, int]:
    if skipped_trades.empty:
        return {}
    return {str(reason): int(count) for reason, count in skipped_trades["reason"].value_counts().sort_index().items()}


def _build_reconciliation(
    cash_curve: pd.Series,
    positions: pd.DataFrame,
    prices: pd.DataFrame,
    equity: pd.Series,
    tolerance: float = 1e-6,
) -> pd.DataFrame:
    market_value = (positions * prices).sum(axis=1)
    recalculated = cash_curve + market_value
    difference = equity - recalculated
    return pd.DataFrame(
        {
            "date": equity.index,
            "cash": cash_curve.values,
            "positions_market_value": market_value.values,
            "reported_equity": equity.values,
            "recalculated_equity": recalculated.values,
            "difference": difference.values,
            "is_reconciled": difference.abs().le(tolerance).values,
        },
        index=equity.index,
    )
