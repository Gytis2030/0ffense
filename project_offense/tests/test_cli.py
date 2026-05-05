from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from project_offense.cli import _benchmark_from_universe, _parse_is_synthetic
from project_offense.data.universe import load_universe


ETF_SYMBOLS = ["IWDA", "EIMI", "IUIT", "IUHC", "AGGU", "IGLN", "CSPX"]


def write_real_etf_fixture(directory: Path) -> tuple[Path, Path]:
    dates = pd.bdate_range("2020-01-02", periods=760)
    base = np.linspace(0.0, 10.0, len(dates))
    prices = {
        symbol: 100.0 + (index + 1) * 0.03 * np.arange(len(dates)) + np.sin(base + index) * 2.0
        for index, symbol in enumerate(ETF_SYMBOLS)
    }
    csv_path = directory / "etf_prices.csv"
    metadata_path = directory / "metadata.yaml"
    pd.DataFrame(prices, index=dates).to_csv(csv_path, index_label="date")
    metadata_path.write_text(
        "\n".join(
            [
                "source_name: unit_test_real_etf_csv",
                "is_synthetic: false",
                "price_type: adjusted_close",
                "currency: USD",
                "timezone: Europe/London",
            ]
        ),
        encoding="utf-8",
    )
    return csv_path, metadata_path

class CLITests(unittest.TestCase):
    def test_parse_is_synthetic_accepts_booleans_and_true_false_strings(self) -> None:
        self.assertTrue(_parse_is_synthetic(True))
        self.assertFalse(_parse_is_synthetic(False))
        self.assertTrue(_parse_is_synthetic("true"))
        self.assertFalse(_parse_is_synthetic("false"))
        self.assertTrue(_parse_is_synthetic("TRUE"))
        self.assertFalse(_parse_is_synthetic("FALSE"))

    def test_parse_is_synthetic_rejects_ambiguous_values(self) -> None:
        for value in ("yes", "no", "0", "1", "", "synthetic", 0, 1, None):
            with self.subTest(value=value):
                with self.assertRaises(SystemExit):
                    _parse_is_synthetic(value)

    def test_benchmark_config_uses_universe_benchmark(self) -> None:
        universe = load_universe("config/etf_universe.yaml")
        self.assertEqual(_benchmark_from_universe(universe), "CSPX")

    def test_demo_requires_allow_synthetic(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "project_offense.cli",
                "--demo",
                "--universe-config",
                "config/stock_universe.yaml",
                "--output-dir",
                "reports_output_test_blocked",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--allow-synthetic", result.stderr + result.stdout)

    def test_demo_works_with_allow_synthetic(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "project_offense.cli",
                "--demo",
                "--allow-synthetic",
                "--universe-config",
                "config/stock_universe.yaml",
                "--output-dir",
                "reports_output_test_allowed",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Performance metrics", result.stdout)
        self.assertIn("Data audit", result.stdout)
        self.assertIn("Backtest audit", result.stdout)
        self.assertIn("skip_reasons=", result.stdout)
        self.assertIn("cash_resized_orders=", result.stdout)
        self.assertIn("source=synthetic_demo", result.stdout)
        self.assertIn("WARNING: synthetic data was used", result.stdout)
        self.assertTrue(Path("reports_output_test_allowed/audit_report.md").exists())

    def test_real_data_csv_workflow_outputs_reports_and_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_path, metadata_path = write_real_etf_fixture(tmp_path)
            output_dir = tmp_path / "reports"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "project_offense.cli",
                    "--price-csv",
                    str(csv_path),
                    "--metadata",
                    str(metadata_path),
                    "--universe-config",
                    "config/etf_universe.yaml",
                    "--strategy",
                    "defensive_momentum_v1",
                    "--benchmark",
                    "CSPX",
                    "--output-dir",
                    str(output_dir),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            files = {path.name for path in output_dir.iterdir()}
            audit = (output_dir / "audit_report.md").read_text(encoding="utf-8")

        self.assertIn("Objective scorecard", result.stdout)
        self.assertIn("audit_report.md", files)
        self.assertIn("research_report.md", files)
        self.assertIn("objective_scorecard.md", files)
        self.assertIn("objective_scorecard.csv", files)
        self.assertIn("monthly_returns.csv", files)
        self.assertIn("weekly_returns.csv", files)
        self.assertIn("rolling_metrics.csv", files)
        self.assertIn("reconciliation_report.csv", files)
        self.assertIn("skipped_trades.csv", files)
        self.assertIn("cash_curve.csv", files)
        self.assertIn("positions.csv", files)
        self.assertIn("source_name: unit_test_real_etf_csv", audit)
        self.assertIn("is_synthetic: False", audit)
        self.assertIn("price_type: adjusted_close", audit)
        self.assertIn("currency: USD", audit)
        self.assertIn("benchmark_ticker: CSPX", audit)

    def test_cli_benchmark_override_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_path, metadata_path = write_real_etf_fixture(tmp_path)
            output_dir = tmp_path / "reports"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "project_offense.cli",
                    "--price-csv",
                    str(csv_path),
                    "--metadata",
                    str(metadata_path),
                    "--universe-config",
                    "config/etf_universe.yaml",
                    "--benchmark",
                    "IWDA",
                    "--output-dir",
                    str(output_dir),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            audit = (output_dir / "audit_report.md").read_text(encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("benchmark=IWDA", result.stdout)
        self.assertIn("benchmark_ticker: IWDA", audit)

    def test_synthetic_still_refused_without_allow_synthetic(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "project_offense.cli",
                "--demo",
                "--universe-config",
                "config/etf_universe.yaml",
                "--output-dir",
                "reports_output_test_synthetic_blocked",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--allow-synthetic", result.stderr + result.stdout)

    def test_real_csv_metadata_marked_synthetic_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_path, metadata_path = write_real_etf_fixture(tmp_path)
            metadata_path.write_text(
                "\n".join(
                    [
                        "source_name: mislabeled_synthetic_csv",
                        "is_synthetic: true",
                        "price_type: adjusted_close",
                        "currency: USD",
                    ]
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "project_offense.cli",
                    "--price-csv",
                    str(csv_path),
                    "--metadata",
                    str(metadata_path),
                    "--universe-config",
                    "config/etf_universe.yaml",
                    "--output-dir",
                    str(tmp_path / "reports"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Synthetic data is not allowed", result.stderr + result.stdout)

    def test_invalid_metadata_timezone_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_path, metadata_path = write_real_etf_fixture(tmp_path)
            metadata_path.write_text(
                "\n".join(
                    [
                        "source_name: unit_test_real_etf_csv",
                        "is_synthetic: false",
                        "price_type: adjusted_close",
                        "currency: USD",
                        "timezone: Not/AZone",
                    ]
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "project_offense.cli",
                    "--price-csv",
                    str(csv_path),
                    "--metadata",
                    str(metadata_path),
                    "--universe-config",
                    "config/etf_universe.yaml",
                    "--output-dir",
                    str(tmp_path / "reports"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("metadata timezone is not a valid IANA timezone", result.stderr + result.stdout)

    def test_real_csv_report_outputs_are_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_path, metadata_path = write_real_etf_fixture(tmp_path)
            outputs = []
            for name in ("reports_a", "reports_b"):
                output_dir = tmp_path / name
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "project_offense.cli",
                        "--price-csv",
                        str(csv_path),
                        "--metadata",
                        str(metadata_path),
                        "--universe-config",
                        "config/etf_universe.yaml",
                        "--benchmark",
                        "CSPX",
                        "--output-dir",
                        str(output_dir),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                outputs.append(output_dir)

            key_files = ("audit_report.md", "research_report.md", "objective_scorecard.csv", "reconciliation_report.csv")
            for filename in key_files:
                self.assertEqual(
                    (outputs[0] / filename).read_text(encoding="utf-8"),
                    (outputs[1] / filename).read_text(encoding="utf-8"),
                    filename,
                )


if __name__ == "__main__":
    unittest.main()
