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
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    result.equity_curve.to_csv(path / "equity_curve.csv")
    result.weights.to_csv(path / "weights.csv")
    result.trades.to_csv(path / "trades.csv", index=False)
    result.order_report.to_csv(path / "dry_run_orders.csv", index=False)
    pd.Series(result.metrics).to_csv(path / "metrics.csv", header=["value"])
