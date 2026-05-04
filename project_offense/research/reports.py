from __future__ import annotations

from pathlib import Path

import pandas as pd

from project_offense.research.metrics import (
    annualized_volatility,
    max_drawdown_from_returns,
    monthly_returns,
    research_metrics,
    research_return_pair,
    rolling_metrics,
    weekly_returns,
)


def write_research_reports(result, output_dir: str) -> None:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    metrics = research_metrics(result)
    weekly = _paired_period_returns(result, weekly_returns, "weekly")
    monthly = _paired_period_returns(result, monthly_returns, "monthly")
    strategy_returns, benchmark_returns = research_return_pair(result)
    rolling = rolling_metrics(strategy_returns, benchmark_returns)
    summary = pd.Series(metrics, name="value").to_frame()

    weekly.to_csv(path / "weekly_returns.csv")
    monthly.to_csv(path / "monthly_returns.csv")
    rolling.to_csv(path / "rolling_metrics.csv")
    summary.to_csv(path / "strategy_score_summary.csv")
    (path / "research_report.md").write_text(format_research_report(metrics, result), encoding="utf-8")


def format_research_report(metrics: dict[str, float], result) -> str:
    strategy_returns, benchmark_returns = research_return_pair(result)
    benchmark_total = float((1.0 + benchmark_returns).prod() - 1.0)
    strategy_total = float(result.equity_curve.iloc[-1] / result.equity_curve.iloc[0] - 1.0)
    benchmark_weekly = weekly_returns(benchmark_returns)
    benchmark_negative_weeks = float((benchmark_weekly < 0).mean()) if not benchmark_weekly.empty else 0.0
    benchmark_worst_week = float(benchmark_weekly.min()) if not benchmark_weekly.empty else 0.0
    risk_free_rate = float(getattr(result, "backtest_audit", {}).get("risk_free_rate", 0.0))
    return "\n".join(
        [
            "# Strategy Research Report",
            "",
            "## Objective Comparison",
            "",
            f"- net_return_strategy: {strategy_total:.6f}",
            f"- net_return_benchmark: {benchmark_total:.6f}",
            f"- volatility_strategy: {metrics['annualized_volatility']:.6f}",
            f"- volatility_benchmark: {annualized_volatility(benchmark_returns):.6f}",
            f"- max_drawdown_strategy: {metrics['max_drawdown']:.6f}",
            f"- max_drawdown_benchmark: {max_drawdown_from_returns(benchmark_returns):.6f}",
            f"- worst_week_strategy: {metrics['worst_weekly_return']:.6f}",
            f"- worst_week_benchmark: {benchmark_worst_week:.6f}",
            f"- negative_week_frequency: {metrics['percentage_negative_weeks']:.6f}",
            f"- negative_week_frequency_benchmark: {benchmark_negative_weeks:.6f}",
            f"- turnover: {metrics['turnover']:.6f}",
            "- turnover_benchmark: not_modeled",
            f"- cost_drag: {metrics['total_cost_drag']:.6f}",
            "- cost_drag_benchmark: not_modeled",
            "",
            "## Metrics",
            "",
            *[f"- {key}: {value:.6f}" for key, value in metrics.items()],
            "",
            "## Metric Definitions",
            "",
            "- CAGR is calculated from the first and last valid net equity values and annualized using elapsed calendar days / 365.25.",
            f"- Risk-free rate is {risk_free_rate:.6f} annualized; Sharpe and Sortino use this explicit value and default to 0.0 unless configured.",
            "- Sortino uses downside deviation against the per-period minimum acceptable return, based on the configured annual risk-free rate, over the full daily return sample.",
            "- Calmar is CAGR divided by absolute max drawdown; it is reported as 0.0 when drawdown is zero because the ratio is undefined.",
            "- Turnover is sum(abs(executed trade value)) / average equity; skipped trades are excluded.",
            "- Cost drag is full-period sum(actual deducted costs) / initial equity; annualized_cost_drag is this full-period drag divided by elapsed years.",
            "- Weekly returns use W-FRI resampling and monthly returns use calendar month-end resampling.",
            "- Weekly and monthly returns are net of trading costs because they are derived from the net equity curve.",
            "- Research metrics exclude the artificial first-day 0.0 return inserted by the backtest engine.",
            "",
        ]
    )


def _paired_period_returns(result, period_func, label: str) -> pd.DataFrame:
    strategy_returns, benchmark_returns = research_return_pair(result)
    strategy = period_func(strategy_returns).rename("strategy")
    benchmark = period_func(benchmark_returns).rename("benchmark")
    frame = pd.concat([strategy, benchmark], axis=1).dropna()
    frame.index.name = f"{label}_period"
    return frame
