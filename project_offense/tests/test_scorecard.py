from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

import numpy as np
import pandas as pd

from project_offense.research.reports import write_research_reports
from project_offense.research.scorecard import FAIL, INCONCLUSIVE, PASS, ObjectiveConfig, build_scorecard


def scorecard_result(
    *,
    periods: int = 252 * 4,
    strategy_scale: float = 0.002,
    benchmark_scale: float = 0.006,
    strategy_drift: float = 0.00045,
    benchmark_drift: float = 0.00015,
    rebalances: int = 48,
    trades: int = 80,
    trade_value: float = 1_000.0,
    cost: float = 0.50,
    warnings: tuple[str, ...] = (),
    is_synthetic: bool = False,
    source_name: str = "unit_test_fixture",
):
    dates = pd.bdate_range("2020-01-02", periods=periods)
    wave = np.sin(np.linspace(0.0, 18.0 * np.pi, periods))
    strategy_returns = pd.Series(strategy_drift + strategy_scale * wave, index=dates)
    benchmark_returns = pd.Series(benchmark_drift + benchmark_scale * wave, index=dates)
    strategy_returns.iloc[0] = 0.0
    benchmark_returns.iloc[0] = 0.0
    equity = 100_000.0 * (1.0 + strategy_returns).cumprod()
    trade_rows = pd.DataFrame(
        {
            "trade_value": [trade_value if i % 2 == 0 else -trade_value for i in range(trades)],
            "total_cost": [cost for _ in range(trades)],
        }
    )
    return SimpleNamespace(
        equity_curve=equity,
        returns=strategy_returns,
        benchmark_returns=benchmark_returns,
        trades=trade_rows,
        backtest_audit={"number_of_rebalances": rebalances, "number_of_trades": trades, "risk_free_rate": 0.0},
        data_audit={"validation_warnings": warnings, "is_synthetic": is_synthetic, "source_name": source_name},
    )


class ScorecardTests(unittest.TestCase):
    def test_clear_pass_case(self) -> None:
        scorecard = build_scorecard(scorecard_result())
        self.assertEqual(scorecard.overall_status, PASS)
        self.assertEqual(scorecard.return_objective, PASS)
        self.assertEqual(scorecard.risk_objective, PASS)
        self.assertEqual(scorecard.drawdown_objective, PASS)
        self.assertEqual(scorecard.behavioral_objective, PASS)
        self.assertEqual(scorecard.cost_practicality_objective, PASS)
        self.assertEqual(scorecard.evidence_quality_objective, PASS)

    def test_clear_fail_case(self) -> None:
        result = scorecard_result(strategy_scale=0.010, benchmark_scale=0.002, strategy_drift=-0.0002, benchmark_drift=0.0004)
        scorecard = build_scorecard(result)
        self.assertEqual(scorecard.overall_status, FAIL)
        self.assertEqual(scorecard.return_objective, FAIL)

    def test_inconclusive_due_to_short_backtest(self) -> None:
        scorecard = build_scorecard(scorecard_result(periods=126))
        self.assertEqual(scorecard.overall_status, INCONCLUSIVE)
        self.assertEqual(scorecard.evidence_quality_objective, INCONCLUSIVE)

    def test_inconclusive_due_to_too_few_rebalances(self) -> None:
        scorecard = build_scorecard(scorecard_result(rebalances=2))
        self.assertEqual(scorecard.overall_status, INCONCLUSIVE)
        self.assertEqual(scorecard.evidence_quality_objective, INCONCLUSIVE)

    def test_inconclusive_due_to_too_few_trades(self) -> None:
        scorecard = build_scorecard(scorecard_result(trades=2))
        self.assertEqual(scorecard.overall_status, INCONCLUSIVE)
        self.assertEqual(scorecard.evidence_quality_objective, INCONCLUSIVE)

    def test_inconclusive_due_to_validation_warnings(self) -> None:
        scorecard = build_scorecard(scorecard_result(warnings=("material data warning",)))
        self.assertEqual(scorecard.overall_status, INCONCLUSIVE)
        self.assertEqual(scorecard.evidence_quality_objective, INCONCLUSIVE)

    def test_synthetic_data_forces_inconclusive_evidence(self) -> None:
        scorecard = build_scorecard(scorecard_result(is_synthetic=True))
        self.assertEqual(scorecard.evidence_quality_objective, INCONCLUSIVE)
        self.assertEqual(scorecard.overall_status, INCONCLUSIVE)
        self.assertTrue(any(result.metric_name == "synthetic_data" for result in scorecard.objective_results))

    def test_synthetic_source_name_forces_inconclusive_evidence(self) -> None:
        scorecard = build_scorecard(scorecard_result(source_name="synthetic_demo"))
        self.assertEqual(scorecard.evidence_quality_objective, INCONCLUSIVE)
        self.assertEqual(scorecard.overall_status, INCONCLUSIVE)

    def test_overall_pass_requires_evidence_quality_pass(self) -> None:
        passing_metrics_but_synthetic = build_scorecard(scorecard_result(is_synthetic=True))
        self.assertEqual(passing_metrics_but_synthetic.return_objective, PASS)
        self.assertNotEqual(passing_metrics_but_synthetic.overall_status, PASS)

    def test_volatility_objective(self) -> None:
        scorecard = build_scorecard(scorecard_result(strategy_scale=0.010, benchmark_scale=0.002))
        self.assertEqual(scorecard.risk_objective, FAIL)

    def test_drawdown_objective(self) -> None:
        scorecard = build_scorecard(scorecard_result(strategy_scale=0.012, benchmark_scale=0.003))
        self.assertEqual(scorecard.drawdown_objective, FAIL)

    def test_worst_week_behavioral_objective(self) -> None:
        config = ObjectiveConfig(maximum_worst_week=0.25)
        scorecard = build_scorecard(scorecard_result(), config)
        self.assertEqual(scorecard.behavioral_objective, FAIL)

    def test_cost_drag_objective(self) -> None:
        scorecard = build_scorecard(scorecard_result(cost=250.0))
        self.assertEqual(scorecard.cost_practicality_objective, FAIL)

    def test_average_trade_size_objective(self) -> None:
        scorecard = build_scorecard(scorecard_result(trade_value=10.0, cost=0.01))
        self.assertEqual(scorecard.cost_practicality_objective, FAIL)

    def test_benchmark_cagr_uses_aligned_returns(self) -> None:
        result = scorecard_result()
        result.benchmark_returns.iloc[0] = 10.0
        scorecard = build_scorecard(result)
        excess = next(row for row in scorecard.objective_results if row.metric_name == "excess_cagr")
        self.assertLess(excess.benchmark_value, 1.0)

    def test_inf_metrics_are_inconclusive(self) -> None:
        result = scorecard_result()
        result.trades = pd.DataFrame({"trade_value": [1_000.0], "total_cost": [float("inf")]})
        scorecard = build_scorecard(result)
        self.assertEqual(scorecard.evidence_quality_objective, INCONCLUSIVE)
        self.assertTrue(any(result.metric_name == "required_metric:total_cost_drag" for result in scorecard.objective_results))

    def test_objective_report_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_research_reports(scorecard_result(), tmp)
            files = {path.name for path in Path(tmp).iterdir()}
            markdown = (Path(tmp) / "objective_scorecard.md").read_text(encoding="utf-8")
            csv = (Path(tmp) / "objective_scorecard.csv").read_text(encoding="utf-8")
        self.assertIn("objective_scorecard.csv", files)
        self.assertIn("objective_scorecard.md", files)
        self.assertIn("overall_status: PASS", markdown)
        self.assertIn("Default Project Offense Objective Profile", markdown)
        self.assertIn("maximum_turnover", markdown)
        self.assertIn("Turnover and average trade size are based on executed trades", markdown)
        self.assertIn("metric_name", csv)
        self.assertIn("excess_cagr", csv)

    def test_scorecard_section_in_research_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_research_reports(scorecard_result(), tmp)
            report = (Path(tmp) / "research_report.md").read_text(encoding="utf-8")
        self.assertIn("## Project Offense Scorecard", report)
        self.assertIn("overall_status: PASS", report)
        self.assertIn("return_objective: PASS", report)
        self.assertIn("### Scorecard Reasons", report)

    def test_research_report_includes_fail_or_inconclusive_reasons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_research_reports(scorecard_result(is_synthetic=True), tmp)
            report = (Path(tmp) / "research_report.md").read_text(encoding="utf-8")
        self.assertIn("synthetic_data: INCONCLUSIVE", report)
        self.assertIn("Synthetic/demo data cannot provide sufficient evidence", report)

    def test_readme_includes_default_thresholds(self) -> None:
        readme = Path("README.md").read_text(encoding="utf-8")
        self.assertIn("Default numeric thresholds", readme)
        self.assertIn("maximum_turnover", readme)
        self.assertIn("minimum_backtest_years", readme)
        self.assertIn("minimum_number_of_rebalances", readme)


if __name__ == "__main__":
    unittest.main()
