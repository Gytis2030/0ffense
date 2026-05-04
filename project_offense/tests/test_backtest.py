from __future__ import annotations

import unittest

import pandas as pd

from project_offense.backtest.calendar import monthly_rebalance_dates
from project_offense.backtest.costs import calculate_trade_cost
from project_offense.backtest.engine import ExecutionAudit, _execute_order, run_backtest, run_backtest_unsafe_from_dataframe
from project_offense.config import CostConfig, StrategyConfig
from project_offense.data.sources import make_demo_prices
from project_offense.data.validation import (
    DataMetadata,
    DataValidationConfig,
    DataValidationError,
    PriceData,
    ValidationResult,
    validate_price_data,
)


def validated_demo(periods: int = 700):
    return validate_price_data(make_demo_prices(periods=periods), DataValidationConfig(allow_synthetic=True))


class BacktestTests(unittest.TestCase):
    def test_no_future_data_leakage(self) -> None:
        result = run_backtest(validated_demo())
        self.assertFalse(result.trades.empty)
        self.assertTrue((pd.to_datetime(result.trades["signal_asof_date"]) < pd.to_datetime(result.trades["date"])).all())
        self.assertTrue((pd.to_datetime(result.trades["decision_date"]) == pd.to_datetime(result.trades["signal_date"])).all())
        self.assertTrue((pd.to_datetime(result.trades["execution_date"]) > pd.to_datetime(result.trades["decision_date"])).all())

    def test_monthly_rebalancing_dates_are_first_trading_days(self) -> None:
        dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-02-01", "2024-02-05", "2024-03-04"])
        expected = list(pd.to_datetime(["2024-01-02", "2024-02-01", "2024-03-04"]))
        self.assertEqual(list(monthly_rebalance_dates(pd.DatetimeIndex(dates))), expected)

    def test_no_trades_below_minimum_trade_size(self) -> None:
        config = StrategyConfig(cost=CostConfig(min_trade_value=1_000_000_000.0))
        result = run_backtest(validated_demo(), config)
        self.assertTrue(result.trades.empty)
        self.assertEqual(float(result.weights.abs().sum().sum()), 0.0)
        self.assertFalse(result.skipped_trades.empty)
        self.assertTrue((result.skipped_trades["reason"] == "below_minimum_trade_size").all())
        self.assertGreater(result.backtest_audit["number_of_minimum_trade_size_skips"], 0)

    def test_signal_decision_execution_date_separation(self) -> None:
        result = run_backtest(validated_demo())
        first = result.trades.iloc[0]
        signal_date = pd.Timestamp(first["signal_date"])
        decision_date = pd.Timestamp(first["decision_date"])
        execution_date = pd.Timestamp(first["execution_date"])
        self.assertEqual(signal_date, decision_date)
        self.assertGreater(execution_date, decision_date)
        self.assertEqual(execution_date, result.equity_curve.index[result.equity_curve.index.get_loc(signal_date) + 1])

    def test_weekend_non_trading_day_rebalance_executes_next_trading_day(self) -> None:
        price_data = validate_price_data(
            make_demo_prices(start="2020-01-01", periods=500),
            DataValidationConfig(allow_synthetic=True),
        )
        result = run_backtest(price_data)
        weekend_crossing = result.trades[
            (pd.to_datetime(result.trades["signal_date"]).dt.dayofweek == 4)
            & (pd.to_datetime(result.trades["execution_date"]).dt.dayofweek == 0)
        ]
        self.assertFalse(weekend_crossing.empty)

    def test_missing_execution_prices_are_skipped_and_logged(self) -> None:
        price_data = validated_demo()
        prices = price_data.prices.copy()
        first_signal = pd.Series(prices.index, index=prices.index).groupby(prices.index.to_period("M")).last().iloc[12]
        execution_date = prices.index[prices.index.get_loc(first_signal) + 1]
        prices.loc[execution_date, "AAPL"] = float("nan")
        result = run_backtest_unsafe_from_dataframe(prices, allow_unsafe=True)
        missing = result.skipped_trades[result.skipped_trades["reason"] == "missing_execution_price"]
        self.assertFalse(missing.empty)
        self.assertGreater(result.backtest_audit["number_of_missing_price_skips"], 0)

    def test_cash_accounting_after_buys_and_transaction_costs(self) -> None:
        result = run_backtest(validated_demo())
        self.assertGreaterEqual(float(result.cash_curve.min()), -1e-8)
        self.assertFalse(result.trades.empty)
        self.assertGreater(float(result.trades["total_cost"].sum()), 0.0)
        self.assertLess(float(result.cash_curve.iloc[-1]), result.equity_curve.iloc[-1])

    def test_sells_increase_cash(self) -> None:
        result = run_backtest(validated_demo(periods=1200))
        sells = result.trades[result.trades["side"] == "SELL"]
        self.assertFalse(sells.empty)
        sell_date = pd.Timestamp(sells.iloc[0]["execution_date"])
        loc = result.cash_curve.index.get_loc(sell_date)
        if loc > 0:
            self.assertGreaterEqual(result.cash_curve.iloc[loc], result.cash_curve.iloc[loc - 1])

    def test_no_accidental_leverage_or_negative_cash(self) -> None:
        result = run_backtest(validated_demo())
        self.assertFalse(result.backtest_audit["leverage_was_attempted"])
        self.assertFalse(result.backtest_audit["cash_went_negative"])
        self.assertGreaterEqual(float(result.cash_curve.min()), -1e-8)

    def test_cash_constraint_resizing_is_not_leverage_attempt(self) -> None:
        shares = pd.Series({"AAPL": 0.0})
        audit = ExecutionAudit()
        trade_rows: list[dict[str, object]] = []
        skipped_rows: list[dict[str, object]] = []
        cash = _execute_order(
            symbol="AAPL",
            desired_trade_value=10_000.0,
            signal_date=pd.Timestamp("2024-01-31"),
            decision_date=pd.Timestamp("2024-01-31"),
            execution_date=pd.Timestamp("2024-02-01"),
            price=100.0,
            shares=shares,
            cash=5_000.0,
            config=StrategyConfig(),
            trade_rows=trade_rows,
            skipped_rows=skipped_rows,
            target_weight=0.2,
            execution_audit=audit,
        )
        self.assertTrue(audit.cash_constraint_triggered)
        self.assertTrue(audit.orders_resized_due_to_cash)
        self.assertEqual(audit.number_of_cash_resized_orders, 1)
        self.assertGreater(audit.total_cash_shortfall_before_resizing, 0.0)
        self.assertFalse(audit.leverage_was_attempted)
        self.assertGreaterEqual(cash, -1e-8)

    def test_actual_negative_cash_flags_leverage_attempt(self) -> None:
        result = run_backtest(validated_demo())
        result.cash_curve.iloc[-1] = -1.0
        result.backtest_audit["cash_went_negative"] = bool(result.cash_curve.lt(0).any())
        result.backtest_audit["leverage_was_attempted"] = result.backtest_audit["cash_went_negative"]
        self.assertTrue(result.backtest_audit["cash_went_negative"])
        self.assertTrue(result.backtest_audit["leverage_was_attempted"])

    def test_fractional_share_mode_allows_fractional_positions(self) -> None:
        result = run_backtest(validated_demo(), StrategyConfig(allow_fractional_shares=True))
        fractional = result.positions.map(lambda value: abs(value - round(value)) > 1e-8)
        self.assertTrue(bool(fractional.any().any()))

    def test_non_fractional_mode_rounds_down_positions(self) -> None:
        result = run_backtest(validated_demo(), StrategyConfig(allow_fractional_shares=False))
        whole_shares = result.positions.map(lambda value: abs(value - round(value)) < 1e-8)
        self.assertTrue(bool(whole_shares.all().all()))
        self.assertGreaterEqual(float(result.cash_curve.min()), -1e-8)

    def test_reconciliation_report_matches_equity(self) -> None:
        result = run_backtest(validated_demo())
        self.assertTrue(bool(result.reconciliation["is_reconciled"].all()))
        self.assertLessEqual(float(result.reconciliation["difference"].abs().max()), 1e-6)

    def test_run_backtest_accepts_validated_price_data(self) -> None:
        result = run_backtest(validated_demo())
        self.assertEqual(result.data_audit["validation_status"], "validated")

    def test_run_backtest_rejects_raw_dataframe(self) -> None:
        with self.assertRaises(TypeError):
            run_backtest(make_demo_prices(periods=700).prices)  # type: ignore[arg-type]

    def test_run_backtest_rejects_unvalidated_price_data(self) -> None:
        with self.assertRaises(DataValidationError):
            run_backtest(make_demo_prices(periods=700))

    def test_run_backtest_rejects_synthetic_without_allow_synthetic_validation(self) -> None:
        price_data = make_demo_prices(periods=700)
        forged = PriceData(
            price_data.prices,
            price_data.metadata,
            ValidationResult(validated=True, allow_synthetic=False),
        )
        with self.assertRaises(DataValidationError):
            run_backtest(forged)

    def test_run_backtest_rejects_missing_benchmark_ticker(self) -> None:
        price_data = validated_demo()
        no_benchmark = PriceData(
            price_data.prices.drop(columns=["SPY"]),
            price_data.metadata,
            price_data.validation_result,
        )
        with self.assertRaises(ValueError):
            run_backtest(no_benchmark)

    def test_backtest_result_contains_data_audit_metadata(self) -> None:
        result = run_backtest(validated_demo())
        self.assertEqual(result.data_audit["source_name"], "synthetic_demo")
        self.assertTrue(result.data_audit["is_synthetic"])
        self.assertEqual(result.data_audit["price_type"], "adjusted_close")
        self.assertEqual(result.data_audit["currency"], "USD")
        self.assertEqual(result.data_audit["validation_warnings"], ())
        self.assertEqual(result.data_audit["validation_errors"], ())
        self.assertEqual(result.backtest_audit["rebalance_frequency"], "monthly")
        self.assertIn("next-trading-day", result.backtest_audit["timing_convention"])
        self.assertIn("first benchmark return", result.backtest_audit["benchmark_return_convention"])

    def test_run_backtest_rejects_benchmark_nans_after_validation(self) -> None:
        price_data = validated_demo()
        prices = price_data.prices.copy()
        prices.loc[prices.index[-1], "SPY"] = float("nan")
        tampered = PriceData(
            prices,
            DataMetadata("unit_test", False, "adjusted_close", "USD"),
            ValidationResult(validated=True),
        )
        with self.assertRaises(DataValidationError):
            run_backtest(tampered)

    def test_missing_benchmark_returns_are_not_silently_zeroed(self) -> None:
        price_data = validated_demo()
        prices = price_data.prices.copy()
        prices.loc[prices.index[12], "SPY"] = float("nan")
        tampered = PriceData(
            prices,
            DataMetadata("unit_test", False, "adjusted_close", "USD"),
            ValidationResult(validated=True),
        )
        with self.assertRaises(DataValidationError):
            run_backtest(tampered)

    def test_run_backtest_rejects_benchmark_date_gaps_after_validation(self) -> None:
        price_data = validated_demo()
        prices = price_data.prices.drop(price_data.prices.index[10:25])
        tampered = PriceData(
            prices,
            DataMetadata("unit_test", False, "adjusted_close", "USD"),
            ValidationResult(validated=True),
        )
        with self.assertRaises(DataValidationError):
            run_backtest(tampered)

    def test_unsafe_dataframe_helper_is_blocked_by_default(self) -> None:
        with self.assertRaises(RuntimeError):
            run_backtest_unsafe_from_dataframe(make_demo_prices(periods=700).prices)

    def test_unsafe_dataframe_helper_requires_explicit_allow_unsafe(self) -> None:
        result = run_backtest_unsafe_from_dataframe(make_demo_prices(periods=700).prices, allow_unsafe=True)
        self.assertEqual(result.data_audit["validation_status"], "unsafe_bypassed")

    def test_target_weight_constraints_are_enforced(self) -> None:
        result = run_backtest(validated_demo())
        self.assertLessEqual(float(result.trades["target_weight"].max()), 0.2000001)
        self.assertLessEqual(float(result.weights.sum(axis=1).max()), 1.0000001)
        self.assertGreaterEqual(float(result.weights.min().min()), -1e-12)

    def test_skipped_trade_reason_counts_are_exposed(self) -> None:
        config = StrategyConfig(cost=CostConfig(min_trade_value=1_000_000_000.0))
        result = run_backtest(validated_demo(), config)
        self.assertIn("below_minimum_trade_size", result.skipped_trade_reason_counts)
        self.assertEqual(
            result.skipped_trade_reason_counts["below_minimum_trade_size"],
            result.backtest_audit["number_of_minimum_trade_size_skips"],
        )

    def test_benchmark_and_strategy_returns_are_aligned(self) -> None:
        result = run_backtest(validated_demo())
        self.assertTrue(result.returns.index.equals(result.benchmark_returns.index))

    def test_transaction_cost_calculation(self) -> None:
        config = CostConfig(min_commission=1.0, commission_pct=0.001, slippage_bps=10.0)
        self.assertEqual(calculate_trade_cost(10_000.0, config), (10.0, 10.0, 20.0))
        self.assertEqual(calculate_trade_cost(100.0, config), (1.0, 0.1, 1.1))


if __name__ == "__main__":
    unittest.main()
