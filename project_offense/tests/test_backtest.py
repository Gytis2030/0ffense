from __future__ import annotations

import unittest

import pandas as pd

from project_offense.backtest.calendar import monthly_rebalance_dates
from project_offense.backtest.costs import calculate_trade_cost
from project_offense.backtest.engine import run_backtest, run_backtest_unsafe_from_dataframe
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

    def test_monthly_rebalancing_dates_are_first_trading_days(self) -> None:
        dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-02-01", "2024-02-05", "2024-03-04"])
        expected = list(pd.to_datetime(["2024-01-02", "2024-02-01", "2024-03-04"]))
        self.assertEqual(list(monthly_rebalance_dates(pd.DatetimeIndex(dates))), expected)

    def test_no_trades_below_minimum_trade_size(self) -> None:
        config = StrategyConfig(cost=CostConfig(min_trade_value=1_000_000_000.0))
        result = run_backtest(validated_demo(), config)
        self.assertTrue(result.trades.empty)
        self.assertEqual(float(result.weights.abs().sum().sum()), 0.0)

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

    def test_run_backtest_rejects_benchmark_date_gaps_after_validation(self) -> None:
        price_data = validated_demo()
        prices = price_data.prices.drop(price_data.prices.index[10])
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

    def test_transaction_cost_calculation(self) -> None:
        config = CostConfig(min_commission=1.0, commission_pct=0.001, slippage_bps=10.0)
        self.assertEqual(calculate_trade_cost(10_000.0, config), (10.0, 10.0, 20.0))
        self.assertEqual(calculate_trade_cost(100.0, config), (1.0, 0.1, 1.1))


if __name__ == "__main__":
    unittest.main()
