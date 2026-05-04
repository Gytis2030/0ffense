from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

import numpy as np
import pandas as pd

from project_offense.backtest.engine import run_backtest
from project_offense.config import defensive_momentum_v1
from project_offense.data.sources import make_demo_prices
from project_offense.data.validation import DataValidationConfig, validate_price_data
from project_offense.reports.orders import write_reports
from project_offense.research.metrics import (
    annualized_volatility,
    beta_to_benchmark,
    cagr,
    cagr_from_equity,
    exclude_first_artificial_return,
    information_ratio,
    max_drawdown_from_returns,
    monthly_returns,
    research_metrics,
    research_return_pair,
    rolling_metrics,
    sharpe_ratio,
    sortino_ratio,
    tracking_error,
    weekly_returns,
)


def sample_returns() -> pd.Series:
    return pd.Series([0.01, -0.02, 0.03, 0.00, 0.01], index=pd.bdate_range("2024-01-01", periods=5))


def sample_result():
    price_data = validate_price_data(make_demo_prices(periods=700), DataValidationConfig(allow_synthetic=True))
    return run_backtest(price_data, defensive_momentum_v1())


class ResearchMetricTests(unittest.TestCase):
    def test_cagr_calculation(self) -> None:
        returns = pd.Series([0.01] * 252, index=pd.bdate_range("2024-01-01", periods=252))
        self.assertAlmostEqual(cagr(returns), (1.01**252) - 1.0)

    def test_cagr_from_equity_partial_year(self) -> None:
        equity = pd.Series([100.0, 110.0], index=pd.to_datetime(["2024-01-01", "2024-07-01"]))
        years = (equity.index[-1] - equity.index[0]).days / 365.25
        self.assertAlmostEqual(cagr_from_equity(equity), (1.10 ** (1.0 / years)) - 1.0)

    def test_cagr_from_equity_multi_year(self) -> None:
        equity = pd.Series([100.0, 121.0], index=pd.to_datetime(["2022-01-01", "2024-01-01"]))
        years = (equity.index[-1] - equity.index[0]).days / 365.25
        self.assertAlmostEqual(cagr_from_equity(equity), (1.21 ** (1.0 / years)) - 1.0)

    def test_volatility_calculation(self) -> None:
        returns = sample_returns()
        self.assertAlmostEqual(annualized_volatility(returns), float(returns.std() * np.sqrt(252)))

    def test_sharpe_and_sortino_calculation(self) -> None:
        returns = sample_returns()
        self.assertAlmostEqual(sharpe_ratio(returns), float(returns.mean() / returns.std() * np.sqrt(252)))
        downside = np.minimum(returns, 0.0)
        downside_deviation = float(np.sqrt(np.mean(np.square(downside))) * np.sqrt(252))
        expected_sortino = float(returns.mean() * 252 / downside_deviation) if downside_deviation != 0 else 0.0
        self.assertAlmostEqual(sortino_ratio(returns), expected_sortino)

    def test_sharpe_uses_explicit_risk_free_rate(self) -> None:
        returns = sample_returns()
        rf = 0.05
        excess = returns - rf / 252
        expected = float(excess.mean() / excess.std() * np.sqrt(252))
        self.assertAlmostEqual(sharpe_ratio(returns, risk_free_rate=rf), expected)

    def test_max_drawdown_calculation(self) -> None:
        returns = pd.Series([0.1, -0.2, 0.05], index=pd.bdate_range("2024-01-01", periods=3))
        self.assertAlmostEqual(max_drawdown_from_returns(returns), -0.2)

    def test_beta_calculation(self) -> None:
        benchmark = pd.Series([0.01, 0.02, -0.01, 0.00], index=pd.bdate_range("2024-01-01", periods=4))
        strategy = benchmark * 2.0
        self.assertAlmostEqual(beta_to_benchmark(strategy, benchmark), 2.0)

    def test_tracking_error_and_information_ratio(self) -> None:
        benchmark = pd.Series([0.01, 0.01, 0.00, 0.02], index=pd.bdate_range("2024-01-01", periods=4))
        strategy = pd.Series([0.02, 0.01, -0.01, 0.03], index=benchmark.index)
        active = strategy - benchmark
        expected_te = float(active.std() * np.sqrt(252))
        self.assertAlmostEqual(tracking_error(strategy, benchmark), expected_te)
        self.assertAlmostEqual(information_ratio(strategy, benchmark), float(active.mean() * 252 / expected_te))

    def test_weekly_and_monthly_returns(self) -> None:
        returns = pd.Series([0.01] * 22, index=pd.bdate_range("2024-01-01", periods=22))
        self.assertFalse(weekly_returns(returns).empty)
        self.assertFalse(monthly_returns(returns).empty)

    def test_rolling_metrics(self) -> None:
        dates = pd.bdate_range("2023-01-02", periods=300)
        strategy = pd.Series([0.001] * 300, index=dates)
        benchmark = pd.Series([0.0005] * 300, index=dates)
        rolling = rolling_metrics(strategy, benchmark)
        self.assertIn("return_3m", rolling.columns)
        self.assertIn("beta_to_benchmark", rolling.columns)
        self.assertFalse(rolling["return_3m"].dropna().empty)

    def test_rolling_beta_zero_benchmark_variance_is_nan(self) -> None:
        dates = pd.bdate_range("2023-01-02", periods=160)
        strategy = pd.Series(np.linspace(-0.001, 0.001, 160), index=dates)
        benchmark = pd.Series(0.0, index=dates)
        rolling = rolling_metrics(strategy, benchmark)
        self.assertTrue(rolling["beta_to_benchmark"].dropna().empty)

    def test_turnover_and_cost_drag_metrics(self) -> None:
        metrics = research_metrics(sample_result())
        self.assertIn("turnover", metrics)
        self.assertIn("total_cost_drag", metrics)
        self.assertIn("annualized_cost_drag", metrics)
        self.assertIn("average_trade_size", metrics)
        self.assertGreaterEqual(metrics["turnover"], 0.0)
        self.assertGreaterEqual(metrics["total_cost_drag"], 0.0)

    def test_turnover_and_cost_drag_definitions(self) -> None:
        dates = pd.bdate_range("2024-01-01", periods=4)
        result = SimpleNamespace(
            equity_curve=pd.Series([100.0, 101.0, 102.0, 103.0], index=dates),
            returns=pd.Series([0.0, 0.01, 0.0099, 0.0098], index=dates),
            benchmark_returns=pd.Series([0.0, 0.005, 0.005, 0.005], index=dates),
            trades=pd.DataFrame({"trade_value": [20.0, -5.0], "total_cost": [1.0, 0.5]}),
            backtest_audit={"risk_free_rate": 0.0},
        )
        metrics = research_metrics(result)
        self.assertAlmostEqual(metrics["turnover"], 25.0 / result.equity_curve.mean())
        self.assertAlmostEqual(metrics["total_cost_drag"], 1.5 / 100.0)

    def test_research_metrics_exclude_first_artificial_return(self) -> None:
        dates = pd.bdate_range("2024-01-01", periods=5)
        result = SimpleNamespace(
            equity_curve=pd.Series([100.0, 101.0, 102.0, 103.0, 104.0], index=dates),
            returns=pd.Series([0.0, 0.01, 0.02, -0.01, 0.00], index=dates),
            benchmark_returns=pd.Series([0.0, 0.00, 0.01, -0.02, 0.01], index=dates),
            trades=pd.DataFrame(columns=["trade_value", "total_cost"]),
            backtest_audit={"risk_free_rate": 0.0},
        )
        strategy, benchmark = research_return_pair(result)
        self.assertEqual(strategy.index[0], dates[1])
        self.assertEqual(benchmark.index[0], dates[1])
        metrics = research_metrics(result)
        self.assertAlmostEqual(metrics["annualized_volatility"], annualized_volatility(result.returns.iloc[1:]))
        self.assertAlmostEqual(metrics["hit_rate_vs_benchmark"], float((result.returns.iloc[1:] > result.benchmark_returns.iloc[1:]).mean()))

    def test_weekly_monthly_returns_are_from_clean_net_returns(self) -> None:
        dates = pd.bdate_range("2024-01-01", periods=8)
        returns = pd.Series([0.0, 0.01, -0.02, 0.03, 0.0, 0.01, 0.01, -0.01], index=dates)
        clean = exclude_first_artificial_return(returns)
        self.assertEqual(weekly_returns(clean).index.freqstr, "W-FRI")
        self.assertFalse(monthly_returns(clean).empty)

    def test_research_report_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_reports(sample_result(), tmp)
            files = {path.name for path in Path(tmp).iterdir()}
            report = (Path(tmp) / "research_report.md").read_text(encoding="utf-8")
        self.assertIn("monthly_returns.csv", files)
        self.assertIn("weekly_returns.csv", files)
        self.assertIn("rolling_metrics.csv", files)
        self.assertIn("strategy_score_summary.csv", files)
        self.assertIn("objective_scorecard.csv", files)
        self.assertIn("objective_scorecard.md", files)
        self.assertIn("research_report.md", files)
        self.assertIn("net_return_benchmark", report)
        self.assertIn("volatility_benchmark", report)
        self.assertIn("max_drawdown_benchmark", report)
        self.assertIn("worst_week_benchmark", report)
        self.assertIn("negative_week_frequency_benchmark", report)
        self.assertIn("turnover_benchmark", report)
        self.assertIn("cost_drag_benchmark", report)
        self.assertIn("## Metric Definitions", report)
        self.assertIn("CAGR is calculated from the first and last valid net equity values", report)
        self.assertIn("Risk-free rate", report)
        self.assertIn("Sortino uses downside deviation", report)
        self.assertIn("Calmar is CAGR divided by absolute max drawdown", report)
        self.assertIn("Turnover is sum(abs(executed trade value)) / average equity", report)
        self.assertIn("Cost drag is full-period", report)
        self.assertIn("Weekly returns use W-FRI", report)
        self.assertIn("## Project Offense Scorecard", report)

    def test_default_defensive_momentum_config(self) -> None:
        config = defensive_momentum_v1()
        self.assertEqual(config.name, "defensive_momentum_v1")
        self.assertEqual(config.lookback_12m, 252)
        self.assertEqual(config.top_n, 5)


if __name__ == "__main__":
    unittest.main()
