from __future__ import annotations

import argparse
from pathlib import Path

from project_offense.backtest.engine import run_backtest
from project_offense.config import CostConfig, StrategyConfig
from project_offense.data.sources import download_yfinance, make_demo_prices, read_price_csv
from project_offense.reports.orders import write_reports


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Project Offense backtest.")
    parser.add_argument("--prices-csv")
    parser.add_argument("--symbols", nargs="+", default=["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "JPM", "XLV"])
    parser.add_argument("--benchmark", default="SPY")
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--output-dir", default="reports_output")
    parser.add_argument("--demo", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.prices_csv:
        prices = read_price_csv(args.prices_csv)
    elif args.demo:
        prices = make_demo_prices(args.symbols, benchmark=args.benchmark, start=args.start)
    else:
        prices = download_yfinance(args.symbols + [args.benchmark], start=args.start)
    result = run_backtest(prices, StrategyConfig(top_n=args.top_n, benchmark_symbol=args.benchmark, cost=CostConfig()))
    output_dir = Path(args.output_dir)
    write_reports(result, str(output_dir))
    print("Performance metrics")
    for key, value in result.metrics.items():
        print(f"{key}: {value:.4f}")
    print(f"Reports written to: {output_dir.resolve()}")


if __name__ == "__main__":
    main()
