from __future__ import annotations

import unittest

import pandas as pd

from project_offense.backtest.calendar import monthly_rebalance_dates
from project_offense.backtest.costs import calculate_trade_cost
from project_offense.backtest.engine import run_backtest
from project_offense.config import CostConfig, StrategyConfig
from project_offense.data.sources import make_demo_prices


class BacktestTests(unittest.TestCase):
    def test_no_future_data_leakage(self) -> None:
        result = run_backtest(make_demo_prices(periods=700))
        self.assertFalse(result.trades.empty)
        self.assertTrue((pd.to_datetime(result.trades["signal_asof_date"]) < pd.to_datetime(result.trades["date"])).all())

    def test_monthly_rebalancing_dates_are_first_trading_days(self) -> None:
        dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-02-01", "2024-02-05", "2024-03-04"])
        expected = list(pd.to_datetime(["2024-01-02", "2024-02-01", "2024-03-04"]))
        self.assertEqual(list(monthly_rebalance_dates(pd.DatetimeIndex(dates))), expected)

    def test_no_trades_below_minimum_trade_size(self) -> None:
        config = StrategyConfig(cost=CostConfig(min_trade_value=1_000_000_000.0))
        result = run_backtest(make_demo_prices(periods=700), config)
        self.assertTrue(result.trades.empty)
        self.assertEqual(float(result.weights.abs().sum().sum()), 0.0)

    def test_transaction_cost_calculation(self) -> None:
        config = CostConfig(min_commission=1.0, commission_pct=0.001, slippage_bps=10.0)
        self.assertEqual(calculate_trade_cost(10_000.0, config), (10.0, 10.0, 20.0))
        self.assertEqual(calculate_trade_cost(100.0, config), (1.0, 0.1, 1.1))


if __name__ == "__main__":
    unittest.main()
