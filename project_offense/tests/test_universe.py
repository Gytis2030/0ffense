from __future__ import annotations

import unittest

import pandas as pd

from project_offense.backtest.engine import run_backtest
from project_offense.config import StrategyConfig
from project_offense.data.sources import make_demo_prices
from project_offense.data.universe import UniverseValidationError, load_universe, validate_universe
from project_offense.data.validation import DataMetadata, DataValidationConfig, PriceData, validate_price_data


def valid_asset(ticker: str = "AAPL") -> dict[str, object]:
    return {
        "ticker": ticker,
        "exchange": "NASDAQ",
        "currency": "USD",
        "asset_class": "common_stock",
        "role": "equity",
        "minimum_trade_size": 50.0,
    }


class UniverseValidationTests(unittest.TestCase):
    def test_duplicate_tickers_are_rejected(self) -> None:
        raw = {"assets": [valid_asset("AAPL"), valid_asset("AAPL")]}
        with self.assertRaises(UniverseValidationError):
            validate_universe(raw)

    def test_missing_required_fields_are_rejected(self) -> None:
        asset = valid_asset("MSFT")
        del asset["exchange"]
        with self.assertRaises(UniverseValidationError):
            validate_universe({"assets": [asset]})

    def test_unsupported_currencies_are_rejected(self) -> None:
        asset = valid_asset("NVDA")
        asset["currency"] = "EUR"
        with self.assertRaises(UniverseValidationError):
            validate_universe({"assets": [asset]})

    def test_invalid_tickers_are_rejected(self) -> None:
        with self.assertRaises(UniverseValidationError):
            validate_universe({"assets": [valid_asset("bad ticker")]})

    def test_empty_universe_configs_are_rejected(self) -> None:
        with self.assertRaises(UniverseValidationError):
            validate_universe({"assets": []})

    def test_config_file_loads(self) -> None:
        universe = load_universe("config/stock_universe.yaml")
        self.assertIn("AAPL", universe.tradable_tickers)
        self.assertNotIn("SPY", universe.tradable_tickers)

    def test_strategy_only_trades_active_universe(self) -> None:
        prices = validate_price_data(
            make_demo_prices(symbols=["AAPL", "MSFT", "NVDA"], benchmark="SPY", periods=700),
            DataValidationConfig(allow_synthetic=True),
        )
        config = StrategyConfig(active_universe=("AAPL",), benchmark_symbol="SPY")
        result = run_backtest(prices, config)
        traded = set(result.trades["symbol"]) if not result.trades.empty else set()
        self.assertLessEqual(traded, {"AAPL"})
        self.assertEqual(list(result.weights.columns), ["AAPL"])

    def test_missing_active_universe_price_column_is_rejected(self) -> None:
        dates = pd.bdate_range("2020-01-01", periods=260)
        raw = pd.DataFrame({"SPY": 100.0, "AAPL": 100.0}, index=dates)
        prices = validate_price_data(
            PriceData(raw, DataMetadata("unit_test", False, "adjusted_close", "USD")),
            DataValidationConfig(stale_price_days=0),
        )
        with self.assertRaises(ValueError):
            run_backtest(prices, StrategyConfig(active_universe=("MSFT",), benchmark_symbol="SPY"))


if __name__ == "__main__":
    unittest.main()
