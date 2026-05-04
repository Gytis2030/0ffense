from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

import pandas as pd

from project_offense.data.provider import LocalCSVDataProvider, SyntheticDemoDataProvider
from project_offense.data.validation import (
    DataMetadata,
    DataValidationConfig,
    DataValidationError,
    PriceData,
    validate_price_data,
)


def metadata(**overrides: object) -> DataMetadata:
    values = {
        "source_name": "unit_test",
        "is_synthetic": False,
        "price_type": "adjusted_close",
        "currency": "USD",
        "timezone": "America/New_York",
    }
    values.update(overrides)
    return DataMetadata(**values)


def valid_prices(periods: int = 8) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-02", periods=periods)
    return pd.DataFrame({"AAPL": range(100, 100 + periods), "SPY": range(200, 200 + periods)}, index=dates)


class DataProviderTests(unittest.TestCase):
    def test_local_csv_provider_loads_metadata_and_prices(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prices.csv"
            valid_prices().to_csv(path)
            price_data = LocalCSVDataProvider(
                path,
                source_name="research_csv",
                price_type="adjusted_close",
                currency="USD",
                timezone="America/New_York",
            ).load(["AAPL", "SPY"])

        self.assertFalse(price_data.metadata.is_synthetic)
        self.assertEqual(price_data.metadata.source_name, "research_csv")
        self.assertEqual(price_data.metadata.price_type, "adjusted_close")
        self.assertEqual(price_data.metadata.currency, "USD")
        self.assertEqual(price_data.metadata.timezone, "America/New_York")
        self.assertEqual(list(price_data.prices.columns), ["AAPL", "SPY"])

    def test_synthetic_provider_is_marked_synthetic(self) -> None:
        price_data = SyntheticDemoDataProvider(periods=20).load(["AAPL"])
        self.assertTrue(price_data.metadata.is_synthetic)
        self.assertEqual(price_data.metadata.source_name, "synthetic_demo")

    def test_synthetic_data_is_blocked_by_default(self) -> None:
        price_data = SyntheticDemoDataProvider(periods=20).load(["AAPL"])
        with self.assertRaises(DataValidationError):
            validate_price_data(price_data)

    def test_synthetic_data_can_be_explicitly_allowed(self) -> None:
        price_data = SyntheticDemoDataProvider(periods=20).load(["AAPL"])
        validated = validate_price_data(price_data, DataValidationConfig(allow_synthetic=True))
        self.assertEqual(list(validated.prices.columns), ["AAPL", "SPY"])
        self.assertTrue(validated.validation_result.validated)
        self.assertTrue(validated.validation_result.allow_synthetic)

    def test_empty_data_is_rejected(self) -> None:
        price_data = PriceData(pd.DataFrame(), metadata())
        with self.assertRaises(DataValidationError):
            validate_price_data(price_data)

    def test_short_holiday_like_weekday_gap_is_allowed(self) -> None:
        prices = valid_prices().drop(pd.Timestamp("2024-01-04"))
        validated = validate_price_data(PriceData(prices, metadata()))
        self.assertTrue(validated.validation_result.validated)

    def test_normal_weekend_gaps_are_allowed(self) -> None:
        validated = validate_price_data(PriceData(valid_prices(), metadata()))
        self.assertTrue(validated.validation_result.validated)

    def test_long_date_gap_is_rejected(self) -> None:
        dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-15", "2024-01-16"])
        prices = pd.DataFrame({"AAPL": [100, 101, 102, 103], "SPY": [200, 201, 202, 203]}, index=dates)
        with self.assertRaises(DataValidationError):
            validate_price_data(PriceData(prices, metadata()), DataValidationConfig(max_gap_days=7))

    def test_duplicate_dates_are_rejected(self) -> None:
        prices = valid_prices()
        duplicate = pd.concat([prices.iloc[:2], prices.iloc[[1]], prices.iloc[2:]])
        with self.assertRaises(DataValidationError):
            validate_price_data(PriceData(duplicate, metadata()))

    def test_non_monotonic_dates_are_rejected(self) -> None:
        prices = valid_prices().iloc[[0, 2, 1, 3, 4, 5, 6, 7]]
        with self.assertRaises(DataValidationError):
            validate_price_data(PriceData(prices, metadata()))

    def test_missing_adjusted_close_is_rejected(self) -> None:
        with self.assertRaises(DataValidationError):
            validate_price_data(PriceData(valid_prices(), metadata(price_type="raw_close")))

    def test_nans_are_rejected(self) -> None:
        prices = valid_prices()
        prices.loc[prices.index[3], "AAPL"] = float("nan")
        with self.assertRaises(DataValidationError):
            validate_price_data(PriceData(prices, metadata()))

    def test_stale_prices_are_rejected(self) -> None:
        prices = valid_prices()
        prices.loc[prices.index[1:5], "AAPL"] = 100.0
        config = DataValidationConfig(stale_price_days=3)
        with self.assertRaises(DataValidationError):
            validate_price_data(PriceData(prices, metadata()), config)

    def test_extreme_daily_returns_are_rejected(self) -> None:
        prices = valid_prices()
        prices.loc[prices.index[2], "AAPL"] = 500.0
        with self.assertRaises(DataValidationError):
            validate_price_data(PriceData(prices, metadata()))

    def test_unsupported_currency_is_rejected(self) -> None:
        with self.assertRaises(DataValidationError):
            validate_price_data(PriceData(valid_prices(), metadata(currency="EUR")))


if __name__ == "__main__":
    unittest.main()
