from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from scripts.download_etf_prices import download_etf_prices, yahoo_symbol_for_asset
from project_offense.data.universe import UniverseAsset


class DownloadEtfPricesTests(unittest.TestCase):
    def test_lse_ticker_maps_to_yahoo_suffix(self) -> None:
        asset = UniverseAsset("CSPX", "LSE", "USD", "ucits_equity_etf", "benchmark", 100.0)
        self.assertEqual(yahoo_symbol_for_asset(asset), "CSPX.L")

    def test_download_writes_project_ticker_columns_with_mocked_data(self) -> None:
        dates = pd.bdate_range("2024-01-02", periods=4)
        calls: list[str] = []

        def fake_downloader(symbol: str, **_: object) -> pd.DataFrame:
            calls.append(symbol)
            offset = float(len(calls))
            return pd.DataFrame({"Adj Close": [100.0 + offset, 101.0 + offset, 102.0 + offset, 103.0 + offset]}, index=dates)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            universe_path = tmp_path / "etf_universe.yaml"
            output_path = tmp_path / "etf_prices.csv"
            universe_path.write_text(
                "\n".join(
                    [
                        "assets:",
                        "  - ticker: CSPX",
                        "    exchange: LSE",
                        "    currency: USD",
                        "    asset_class: ucits_equity_etf",
                        "    role: benchmark",
                        "    minimum_trade_size: 100.0",
                        "  - ticker: IWDA",
                        "    exchange: LSE",
                        "    currency: USD",
                        "    asset_class: ucits_equity_etf",
                        "    role: global_developed_equity",
                        "    minimum_trade_size: 100.0",
                    ]
                ),
                encoding="utf-8",
            )

            prices = download_etf_prices(
                universe_config=universe_path,
                output=output_path,
                start="2024-01-01",
                end="2024-01-10",
                downloader=fake_downloader,
            )
            written = pd.read_csv(output_path)

        self.assertEqual(calls, ["CSPX.L", "IWDA.L"])
        self.assertEqual(list(prices.columns), ["CSPX", "IWDA"])
        self.assertEqual(list(written.columns), ["date", "CSPX", "IWDA"])
        self.assertEqual(prices.attrs["output_path"], str(output_path))
        self.assertEqual(prices.attrs["failed_tickers"], ())

    def test_failed_download_has_clear_ticker_error(self) -> None:
        def fake_downloader(symbol: str, **_: object) -> pd.DataFrame:
            raise RuntimeError(f"missing {symbol}")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            universe_path = tmp_path / "etf_universe.yaml"
            universe_path.write_text(
                "\n".join(
                    [
                        "assets:",
                        "  - ticker: CSPX",
                        "    exchange: LSE",
                        "    currency: USD",
                        "    asset_class: ucits_equity_etf",
                        "    role: benchmark",
                        "    minimum_trade_size: 100.0",
                        "  - ticker: IWDA",
                        "    exchange: LSE",
                        "    currency: USD",
                        "    asset_class: ucits_equity_etf",
                        "    role: global_developed_equity",
                        "    minimum_trade_size: 100.0",
                    ]
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "CSPX.*CSPX.L"):
                download_etf_prices(universe_config=universe_path, output=tmp_path / "prices.csv", downloader=fake_downloader, retries=1)

    def test_retries_each_ticker_before_success(self) -> None:
        dates = pd.bdate_range("2024-01-02", periods=2)
        calls: dict[str, int] = {}

        def fake_downloader(symbol: str, **kwargs: object) -> pd.DataFrame:
            self.assertEqual(kwargs["timeout"], 90)
            calls[symbol] = calls.get(symbol, 0) + 1
            if symbol == "CSPX.L" and calls[symbol] < 3:
                raise TimeoutError("timed out")
            return pd.DataFrame({"Adj Close": [100.0, 101.0]}, index=dates)

        with tempfile.TemporaryDirectory() as tmp, patch("scripts.download_etf_prices.time.sleep", return_value=None):
            tmp_path = Path(tmp)
            universe_path = tmp_path / "etf_universe.yaml"
            universe_path.write_text(_two_asset_universe(), encoding="utf-8")
            prices = download_etf_prices(
                universe_config=universe_path,
                output=tmp_path / "prices.csv",
                downloader=fake_downloader,
                retries=3,
                timeout=90,
            )

        self.assertEqual(calls["CSPX.L"], 3)
        self.assertEqual(calls["IWDA.L"], 1)
        self.assertEqual(list(prices.columns), ["CSPX", "IWDA"])

    def test_partial_download_is_saved_when_allowed(self) -> None:
        dates = pd.bdate_range("2024-01-02", periods=3)

        def fake_downloader(symbol: str, **_: object) -> pd.DataFrame:
            if symbol == "IWDA.L":
                raise TimeoutError("timed out")
            return pd.DataFrame({"Adj Close": [100.0, 101.0, 102.0]}, index=dates)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            universe_path = tmp_path / "etf_universe.yaml"
            output_path = tmp_path / "etf_prices.csv"
            partial_path = tmp_path / "etf_prices_partial.csv"
            universe_path.write_text(_two_asset_universe(), encoding="utf-8")
            prices = download_etf_prices(
                universe_config=universe_path,
                output=output_path,
                partial_output=partial_path,
                downloader=fake_downloader,
                retries=1,
                allow_partial=True,
            )
            partial = pd.read_csv(partial_path)

        self.assertFalse(output_path.exists())
        self.assertEqual(list(prices.columns), ["CSPX"])
        self.assertEqual(list(partial.columns), ["date", "CSPX"])
        self.assertEqual(prices.attrs["output_path"], str(partial_path))
        self.assertEqual(prices.attrs["failed_tickers"], ("IWDA",))

    def test_partial_download_fails_without_allow_partial_but_writes_partial(self) -> None:
        dates = pd.bdate_range("2024-01-02", periods=3)

        def fake_downloader(symbol: str, **_: object) -> pd.DataFrame:
            if symbol == "IWDA.L":
                raise TimeoutError("timed out")
            return pd.DataFrame({"Adj Close": [100.0, 101.0, 102.0]}, index=dates)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            universe_path = tmp_path / "etf_universe.yaml"
            partial_path = tmp_path / "etf_prices_partial.csv"
            universe_path.write_text(_two_asset_universe(), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "IWDA.*etf_prices_partial.csv"):
                download_etf_prices(
                    universe_config=universe_path,
                    output=tmp_path / "etf_prices.csv",
                    partial_output=partial_path,
                    downloader=fake_downloader,
                    retries=1,
                    allow_partial=False,
                )
            partial = pd.read_csv(partial_path)

        self.assertEqual(list(partial.columns), ["date", "CSPX"])


def _two_asset_universe() -> str:
    return "\n".join(
        [
            "assets:",
            "  - ticker: CSPX",
            "    exchange: LSE",
            "    currency: USD",
            "    asset_class: ucits_equity_etf",
            "    role: benchmark",
            "    minimum_trade_size: 100.0",
            "  - ticker: IWDA",
            "    exchange: LSE",
            "    currency: USD",
            "    asset_class: ucits_equity_etf",
            "    role: global_developed_equity",
            "    minimum_trade_size: 100.0",
        ]
    )


if __name__ == "__main__":
    unittest.main()
