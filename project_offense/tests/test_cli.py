from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


class CLITests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
