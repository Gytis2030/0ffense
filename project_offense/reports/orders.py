from __future__ import annotations

from pathlib import Path

import pandas as pd


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
    result.order_report.to_csv(path / "dry_run_orders.csv", index=False)
    pd.Series(result.metrics).to_csv(path / "metrics.csv", header=["value"])
    (path / "audit_report.md").write_text(format_audit_report(result.data_audit), encoding="utf-8")


def format_audit_report(audit: dict[str, object]) -> str:
    warnings = _format_list(audit.get("validation_warnings"))
    errors = _format_list(audit.get("validation_errors"))
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
        ]
    )


def _format_list(value: object) -> str:
    items = tuple(value or ())
    if not items:
        return "  - none"
    return "\n".join(f"  - {item}" for item in items)
