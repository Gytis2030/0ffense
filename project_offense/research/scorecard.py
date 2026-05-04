from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

import pandas as pd

from project_offense.research.metrics import (
    CALENDAR_DAYS_PER_YEAR,
    annualized_volatility,
    cagr_from_equity,
    max_drawdown_from_returns,
    monthly_returns,
    research_metrics,
    research_return_pair,
    weekly_returns,
)


PASS = "PASS"
FAIL = "FAIL"
INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class ObjectiveConfig:
    minimum_excess_cagr: float = 0.0
    maximum_relative_volatility: float = 1.0
    maximum_relative_drawdown: float = 1.0
    maximum_worst_week: float = 1.0
    maximum_negative_week_frequency: float = 1.0
    maximum_turnover: float = 50.0
    maximum_cost_drag: float = 0.10
    maximum_annualized_cost_drag: float = 0.02
    minimum_average_trade_size: float = 50.0
    minimum_backtest_years: float = 3.0
    minimum_number_of_rebalances: int = 24
    minimum_number_of_trades: int = 20


@dataclass(frozen=True)
class ObjectiveResult:
    category: str
    metric_name: str
    strategy_value: float | None
    benchmark_value: float | None
    threshold: float | int | str
    status: str
    severity: str
    reason: str


@dataclass(frozen=True)
class StrategyScorecard:
    overall_status: str
    return_objective: str
    risk_objective: str
    drawdown_objective: str
    behavioral_objective: str
    cost_practicality_objective: str
    evidence_quality_objective: str
    objective_results: tuple[ObjectiveResult, ...]

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "category": result.category,
                    "metric_name": result.metric_name,
                    "strategy_value": result.strategy_value,
                    "benchmark_value": result.benchmark_value,
                    "threshold": result.threshold,
                    "status": result.status,
                    "severity": result.severity,
                    "reason": result.reason,
                }
                for result in self.objective_results
            ]
        )


def default_project_offense_objectives(**overrides: object) -> ObjectiveConfig:
    """Default Project Offense objective profile."""
    return ObjectiveConfig(**overrides)


def build_scorecard(result, objective_config: ObjectiveConfig | None = None) -> StrategyScorecard:
    config = objective_config or default_project_offense_objectives()
    strategy_metrics = research_metrics(result)
    benchmark_metrics = _benchmark_metrics(result)
    years = _backtest_years(result.equity_curve)
    rebalances = int(getattr(result, "backtest_audit", {}).get("number_of_rebalances", 0) or 0)
    trades = int(getattr(result, "backtest_audit", {}).get("number_of_trades", 0) or 0)
    data_audit = getattr(result, "data_audit", {}) or {}
    warnings = tuple(data_audit.get("validation_warnings") or ())

    results = [
        _compare_excess(
            "return_objective",
            "excess_cagr",
            strategy_metrics["CAGR"],
            benchmark_metrics["CAGR"],
            config.minimum_excess_cagr,
            "critical",
        ),
        _compare_relative_max(
            "risk_objective",
            "relative_volatility",
            strategy_metrics["annualized_volatility"],
            benchmark_metrics["annualized_volatility"],
            config.maximum_relative_volatility,
            "critical",
            lower_abs=False,
        ),
        _compare_relative_max(
            "drawdown_objective",
            "relative_max_drawdown",
            strategy_metrics["max_drawdown"],
            benchmark_metrics["max_drawdown"],
            config.maximum_relative_drawdown,
            "critical",
            lower_abs=True,
        ),
        _compare_relative_max(
            "behavioral_objective",
            "relative_worst_week",
            strategy_metrics["worst_weekly_return"],
            benchmark_metrics["worst_weekly_return"],
            config.maximum_worst_week,
            "critical",
            lower_abs=True,
        ),
        _compare_relative_max(
            "behavioral_objective",
            "relative_negative_week_frequency",
            strategy_metrics["percentage_negative_weeks"],
            benchmark_metrics["percentage_negative_weeks"],
            config.maximum_negative_week_frequency,
            "critical",
            lower_abs=False,
        ),
        _compare_max(
            "cost_practicality_objective",
            "turnover",
            strategy_metrics["turnover"],
            config.maximum_turnover,
            "critical",
        ),
        _compare_max(
            "cost_practicality_objective",
            "total_cost_drag",
            strategy_metrics["total_cost_drag"],
            config.maximum_cost_drag,
            "critical",
        ),
        _compare_max(
            "cost_practicality_objective",
            "annualized_cost_drag",
            strategy_metrics["annualized_cost_drag"],
            config.maximum_annualized_cost_drag,
            "critical",
        ),
        _compare_min(
            "cost_practicality_objective",
            "average_trade_size",
            strategy_metrics["average_trade_size"],
            config.minimum_average_trade_size,
            "critical",
        ),
        _compare_min("evidence_quality_objective", "backtest_years", years, config.minimum_backtest_years, "evidence"),
        _compare_min(
            "evidence_quality_objective",
            "number_of_rebalances",
            float(rebalances),
            config.minimum_number_of_rebalances,
            "evidence",
        ),
        _compare_min(
            "evidence_quality_objective",
            "number_of_trades",
            float(trades),
            config.minimum_number_of_trades,
            "evidence",
        ),
    ]
    results.extend(_required_metric_checks(strategy_metrics, benchmark_metrics))
    if warnings:
        results.append(
            ObjectiveResult(
                "evidence_quality_objective",
                "validation_warnings",
                float(len(warnings)),
                None,
                "0 material warnings",
                INCONCLUSIVE,
                "evidence",
                "Validation warnings must be reviewed before trusting the scorecard.",
            )
        )
    if _is_synthetic_audit(data_audit):
        results.append(
            ObjectiveResult(
                "evidence_quality_objective",
                "synthetic_data",
                None,
                None,
                "non-synthetic validated data",
                INCONCLUSIVE,
                "evidence",
                "Synthetic/demo data cannot provide sufficient evidence for a Project Offense PASS.",
            )
        )

    category_statuses = {
        "return_objective": _category_status(results, "return_objective"),
        "risk_objective": _category_status(results, "risk_objective"),
        "drawdown_objective": _category_status(results, "drawdown_objective"),
        "behavioral_objective": _category_status(results, "behavioral_objective"),
        "cost_practicality_objective": _category_status(results, "cost_practicality_objective"),
        "evidence_quality_objective": _category_status(results, "evidence_quality_objective"),
    }
    overall = _overall_status(results, category_statuses)
    return StrategyScorecard(
        overall,
        category_statuses["return_objective"],
        category_statuses["risk_objective"],
        category_statuses["drawdown_objective"],
        category_statuses["behavioral_objective"],
        category_statuses["cost_practicality_objective"],
        category_statuses["evidence_quality_objective"],
        tuple(results),
    )


def format_scorecard_markdown(scorecard: StrategyScorecard) -> str:
    lines = [
        "# Project Offense Objective Scorecard",
        "",
        f"- overall_status: {scorecard.overall_status}",
        f"- return_objective: {scorecard.return_objective}",
        f"- risk_objective: {scorecard.risk_objective}",
        f"- drawdown_objective: {scorecard.drawdown_objective}",
        f"- behavioral_objective: {scorecard.behavioral_objective}",
        f"- cost_practicality_objective: {scorecard.cost_practicality_objective}",
        f"- evidence_quality_objective: {scorecard.evidence_quality_objective}",
        "",
        "## Default Project Offense Objective Profile",
        "",
        *[f"- {key}: {value}" for key, value in _objective_config_items(default_project_offense_objectives())],
        "",
        "## Cost Practicality Convention",
        "",
        "- Turnover and average trade size are based on executed trades.",
        "- Skipped trades are excluded from turnover and are shown separately in audit outputs.",
        "",
        "## Objective Results",
        "",
        "| category | metric | strategy | benchmark | threshold | status | severity | reason |",
        "| --- | --- | ---: | ---: | --- | --- | --- | --- |",
    ]
    for result in scorecard.objective_results:
        lines.append(
            "| {category} | {metric} | {strategy} | {benchmark} | {threshold} | {status} | {severity} | {reason} |".format(
                category=result.category,
                metric=result.metric_name,
                strategy=_format_value(result.strategy_value),
                benchmark=_format_value(result.benchmark_value),
                threshold=result.threshold,
                status=result.status,
                severity=result.severity,
                reason=result.reason.replace("|", "/"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _benchmark_metrics(result) -> dict[str, float]:
    _, benchmark = research_return_pair(result)
    benchmark_equity = (1.0 + benchmark).cumprod()
    weekly = weekly_returns(benchmark)
    monthly = monthly_returns(benchmark)
    return {
        "CAGR": cagr_from_equity(benchmark_equity),
        "annualized_volatility": annualized_volatility(benchmark),
        "max_drawdown": max_drawdown_from_returns(benchmark),
        "percentage_negative_weeks": float((weekly < 0).mean()) if not weekly.empty else math.nan,
        "worst_weekly_return": float(weekly.min()) if not weekly.empty else math.nan,
        "monthly_win_rate": float((monthly > 0).mean()) if not monthly.empty else math.nan,
    }


def _compare_excess(category: str, metric: str, strategy: float, benchmark: float, threshold: float, severity: str) -> ObjectiveResult:
    if _any_nan(strategy, benchmark, threshold):
        return _inconclusive(category, metric, strategy, benchmark, threshold, severity, "Required return metric is NaN.")
    excess = strategy - benchmark
    status = PASS if excess >= threshold else FAIL
    reason = f"Excess CAGR {excess:.6f} {'meets' if status == PASS else 'is below'} required minimum {threshold:.6f}."
    return ObjectiveResult(category, metric, strategy, benchmark, threshold, status, severity, reason)


def _compare_relative_max(
    category: str,
    metric: str,
    strategy: float,
    benchmark: float,
    threshold: float,
    severity: str,
    *,
    lower_abs: bool,
) -> ObjectiveResult:
    if _any_nan(strategy, benchmark, threshold):
        return _inconclusive(category, metric, strategy, benchmark, threshold, severity, "Required relative metric is NaN.")
    numerator = abs(strategy) if lower_abs else strategy
    denominator = abs(benchmark) if lower_abs else benchmark
    if denominator <= 0:
        return _inconclusive(category, metric, strategy, benchmark, threshold, severity, "Benchmark denominator is not usable.")
    ratio = numerator / denominator
    status = PASS if ratio <= threshold else FAIL
    reason = f"Relative value {ratio:.6f} {'meets' if status == PASS else 'exceeds'} maximum {threshold:.6f}."
    return ObjectiveResult(category, metric, strategy, benchmark, threshold, status, severity, reason)


def _compare_max(category: str, metric: str, strategy: float, threshold: float, severity: str) -> ObjectiveResult:
    if _any_nan(strategy, threshold):
        return _inconclusive(category, metric, strategy, None, threshold, severity, "Required maximum-threshold metric is NaN.")
    status = PASS if strategy <= threshold else FAIL
    reason = f"{metric} {strategy:.6f} {'meets' if status == PASS else 'exceeds'} maximum {threshold:.6f}."
    return ObjectiveResult(category, metric, strategy, None, threshold, status, severity, reason)


def _compare_min(category: str, metric: str, strategy: float, threshold: float | int, severity: str) -> ObjectiveResult:
    if _any_nan(strategy, threshold):
        return _inconclusive(category, metric, strategy, None, threshold, severity, "Required minimum-threshold metric is NaN.")
    status = PASS if strategy >= float(threshold) else INCONCLUSIVE if severity == "evidence" else FAIL
    reason = f"{metric} {strategy:.6f} {'meets' if status == PASS else 'is below'} minimum {float(threshold):.6f}."
    return ObjectiveResult(category, metric, strategy, None, threshold, status, severity, reason)


def _required_metric_checks(strategy_metrics: dict[str, float], benchmark_metrics: dict[str, float]) -> list[ObjectiveResult]:
    checks = []
    for name, value in {**strategy_metrics, **{f"benchmark_{key}": value for key, value in benchmark_metrics.items()}}.items():
        if _is_nan(value):
            checks.append(
                ObjectiveResult(
                    "evidence_quality_objective",
                    f"required_metric:{name}",
                    value,
                    None,
                    "finite",
                    INCONCLUSIVE,
                    "evidence",
                    "Required scorecard metric is NaN.",
                )
            )
    return checks


def _category_status(results: Iterable[ObjectiveResult], category: str) -> str:
    statuses = [result.status for result in results if result.category == category]
    if any(status == INCONCLUSIVE for status in statuses):
        return INCONCLUSIVE
    if any(status == FAIL for status in statuses):
        return FAIL
    return PASS


def _overall_status(results: Iterable[ObjectiveResult], categories: dict[str, str]) -> str:
    # Convention: evidence quality gates a PASS, but clear critical failures
    # still produce FAIL because a strategy can fail even on incomplete evidence.
    if any(result.status == FAIL and result.severity == "critical" for result in results):
        return FAIL
    if categories["evidence_quality_objective"] == INCONCLUSIVE:
        return INCONCLUSIVE
    if any(result.status == INCONCLUSIVE for result in results):
        return INCONCLUSIVE
    required_categories = (
        "return_objective",
        "risk_objective",
        "drawdown_objective",
        "behavioral_objective",
        "cost_practicality_objective",
        "evidence_quality_objective",
    )
    return PASS if all(categories[category] == PASS for category in required_categories) else FAIL


def _backtest_years(equity_curve: pd.Series) -> float:
    equity = equity_curve.dropna()
    if len(equity) < 2:
        return 0.0
    elapsed_days = (pd.Timestamp(equity.index[-1]) - pd.Timestamp(equity.index[0])).days
    return float(elapsed_days / CALENDAR_DAYS_PER_YEAR) if elapsed_days > 0 else 0.0


def _inconclusive(
    category: str,
    metric: str,
    strategy: float | None,
    benchmark: float | None,
    threshold: float | int | str,
    severity: str,
    reason: str,
) -> ObjectiveResult:
    return ObjectiveResult(category, metric, strategy, benchmark, threshold, INCONCLUSIVE, severity, reason)


def _any_nan(*values: object) -> bool:
    return any(_is_nan(value) for value in values)


def _is_nan(value: object) -> bool:
    if isinstance(value, (float, int)):
        return not math.isfinite(float(value))
    try:
        return bool(pd.isna(value))
    except TypeError:
        return False


def _format_value(value: float | None) -> str:
    if value is None:
        return ""
    if _is_nan(value):
        return "NaN"
    return f"{value:.6f}"


def _is_synthetic_audit(data_audit: dict[str, object]) -> bool:
    source_name = str(data_audit.get("source_name") or "").lower()
    return bool(data_audit.get("is_synthetic")) or "synthetic" in source_name or "demo" in source_name


def _objective_config_items(config: ObjectiveConfig) -> list[tuple[str, float | int]]:
    return [
        ("minimum_excess_cagr", config.minimum_excess_cagr),
        ("maximum_relative_volatility", config.maximum_relative_volatility),
        ("maximum_relative_drawdown", config.maximum_relative_drawdown),
        ("maximum_worst_week", config.maximum_worst_week),
        ("maximum_negative_week_frequency", config.maximum_negative_week_frequency),
        ("maximum_turnover", config.maximum_turnover),
        ("maximum_cost_drag", config.maximum_cost_drag),
        ("maximum_annualized_cost_drag", config.maximum_annualized_cost_drag),
        ("minimum_average_trade_size", config.minimum_average_trade_size),
        ("minimum_backtest_years", config.minimum_backtest_years),
        ("minimum_number_of_rebalances", config.minimum_number_of_rebalances),
        ("minimum_number_of_trades", config.minimum_number_of_trades),
    ]
