from __future__ import annotations

from pathlib import Path

import pandas as pd

from project_offense.research.reports import write_research_reports


def build_order_report(weights: pd.Series, latest_prices: pd.Series, portfolio_value: float) -> pd.DataFrame:
    rows = []
    for symbol, weight in weights[weights > 0].sort_values(ascending=False).items():
        price = float(latest_prices.get(symbol, 0.0))
        notional = float(weight) * portfolio_value
        rows.append(
            {
                "symbol": symbol,
                "side": "BUY",
                "target_weight": float(weight),
                "latest_price": price,
                "notional": notional,
                "estimated_quantity": int(notional // price) if price > 0 else 0,
                "live_order": False,
            }
        )
    return pd.DataFrame(rows)


def write_reports(result, output_dir: str) -> None:
    if not getattr(result, "data_audit", None):
        raise ValueError("BacktestResult is missing required data_audit metadata.")
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    result.equity_curve.to_csv(path / "equity_curve.csv")
    result.weights.to_csv(path / "weights.csv")
    result.trades.to_csv(path / "trades.csv", index=False)
    result.skipped_trades.to_csv(path / "skipped_trades.csv", index=False)
    result.cash_curve.to_csv(path / "cash_curve.csv")
    result.positions.to_csv(path / "positions.csv")
    result.reconciliation.to_csv(path / "reconciliation_report.csv", index=False)
    result.order_report.to_csv(path / "dry_run_orders.csv", index=False)
    pd.Series(result.metrics).to_csv(path / "metrics.csv", header=["value"])
    (path / "audit_report.md").write_text(
        format_audit_report(result.data_audit, getattr(result, "backtest_audit", {})),
        encoding="utf-8",
    )
    write_research_reports(result, str(path))


def format_audit_report(audit: dict[str, object], backtest_audit: dict[str, object] | None = None) -> str:
    backtest_audit = backtest_audit or {}
    warnings = _format_list(audit.get("validation_warnings"))
    errors = _format_list(audit.get("validation_errors"))
    skipped_reason_counts = _format_mapping(backtest_audit.get("skipped_trade_reason_counts"))
    return "\n".join(
        [
            "# Audit Report",
            "",
            "## Data",
            "",
            f"- source_name: {audit.get('source_name')}",
            f"- is_synthetic: {audit.get('is_synthetic')}",
            f"- price_type: {audit.get('price_type')}",
            f"- currency: {audit.get('currency')}",
            f"- timezone: {audit.get('timezone')}",
            f"- benchmark_ticker: {audit.get('benchmark_ticker')}",
            f"- data_start_date: {audit.get('data_start_date')}",
            f"- data_end_date: {audit.get('data_end_date')}",
            f"- row_count: {audit.get('row_count')}",
            f"- ticker_count: {audit.get('ticker_count')}",
            "",
            "## Validation",
            "",
            f"- validation_status: {audit.get('validation_status')}",
            "- validation_warnings:",
            warnings,
            "- validation_errors:",
            errors,
            "",
            "## Backtest",
            "",
            f"- rebalance_frequency: {backtest_audit.get('rebalance_frequency')}",
            f"- timing_convention: {backtest_audit.get('timing_convention')}",
            f"- benchmark_ticker: {backtest_audit.get('benchmark_ticker')}",
            f"- min_commission: {backtest_audit.get('min_commission')}",
            f"- commission_pct: {backtest_audit.get('commission_pct')}",
            f"- slippage_bps: {backtest_audit.get('slippage_bps')}",
            f"- minimum_trade_size: {backtest_audit.get('minimum_trade_size')}",
            f"- allow_fractional_shares: {backtest_audit.get('allow_fractional_shares')}",
            f"- risk_free_rate: {backtest_audit.get('risk_free_rate')}",
            f"- benchmark_return_convention: {backtest_audit.get('benchmark_return_convention')}",
            f"- number_of_rebalances: {backtest_audit.get('number_of_rebalances')}",
            f"- number_of_trades: {backtest_audit.get('number_of_trades')}",
            f"- number_of_skipped_trades: {backtest_audit.get('number_of_skipped_trades')}",
            f"- number_of_missing_price_skips: {backtest_audit.get('number_of_missing_price_skips')}",
            f"- number_of_minimum_trade_size_skips: {backtest_audit.get('number_of_minimum_trade_size_skips')}",
            "- skipped_trade_reason_counts:",
            skipped_reason_counts,
            f"- leverage_was_attempted: {backtest_audit.get('leverage_was_attempted')}",
            f"- cash_constraint_triggered: {backtest_audit.get('cash_constraint_triggered')}",
            f"- orders_resized_due_to_cash: {backtest_audit.get('orders_resized_due_to_cash')}",
            f"- number_of_cash_resized_orders: {backtest_audit.get('number_of_cash_resized_orders')}",
            f"- total_cash_shortfall_before_resizing: {backtest_audit.get('total_cash_shortfall_before_resizing')}",
            f"- cash_went_negative: {backtest_audit.get('cash_went_negative')}",
            "",
        ]
    )


def _format_list(value: object) -> str:
    items = tuple(value or ())
    if not items:
        return "  - none"
    return "\n".join(f"  - {item}" for item in items)


def _format_mapping(value: object) -> str:
    mapping = dict(value or {})
    if not mapping:
        return "  - none"
    return "\n".join(f"  - {key}: {mapping[key]}" for key in sorted(mapping))
