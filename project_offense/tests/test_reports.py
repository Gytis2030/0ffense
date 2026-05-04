from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from project_offense.backtest.engine import run_backtest
from project_offense.data.sources import make_demo_prices
from project_offense.data.validation import DataValidationConfig, PriceData, validate_price_data
from project_offense.reports.orders import write_reports


def result_with_warning():
    price_data = validate_price_data(make_demo_prices(periods=700), DataValidationConfig(allow_synthetic=True))
    validation = replace(price_data.validation_result, warnings=("review this synthetic smoke test",))
    warned = PriceData(price_data.prices, price_data.metadata, validation)
    return run_backtest(warned)


class ReportTests(unittest.TestCase):
    def test_write_reports_persists_data_audit(self) -> None:
        result = result_with_warning()
        with tempfile.TemporaryDirectory() as tmp:
            write_reports(result, tmp)
            audit_path = Path(tmp) / "audit_report.md"
            content = audit_path.read_text(encoding="utf-8")

        self.assertIn("source_name: synthetic_demo", content)
        self.assertIn("price_type: adjusted_close", content)
        self.assertIn("currency: USD", content)
        self.assertIn("benchmark_ticker: SPY", content)
        self.assertIn("data_start_date:", content)
        self.assertIn("data_end_date:", content)
        self.assertIn("row_count: 700", content)
        self.assertIn("ticker_count:", content)

    def test_validation_warnings_appear_in_written_report(self) -> None:
        result = result_with_warning()
        with tempfile.TemporaryDirectory() as tmp:
            write_reports(result, tmp)
            content = (Path(tmp) / "audit_report.md").read_text(encoding="utf-8")

        self.assertIn("review this synthetic smoke test", content)

    def test_report_marks_synthetic_data_clearly(self) -> None:
        result = result_with_warning()
        with tempfile.TemporaryDirectory() as tmp:
            write_reports(result, tmp)
            content = (Path(tmp) / "audit_report.md").read_text(encoding="utf-8")

        self.assertIn("is_synthetic: True", content)

    def test_no_report_is_generated_without_audit_metadata(self) -> None:
        result = result_with_warning()
        result.data_audit = {}
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                write_reports(result, tmp)


if __name__ == "__main__":
    unittest.main()
