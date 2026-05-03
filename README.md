# Project Offense

Project Offense is a daily-price, long-only trading research package. It builds low-turnover monthly portfolios, applies market-regime exposure controls, deducts commissions and slippage, and compares results against an S&P 500 benchmark.

This is a research and paper-trading scaffold only. It does not place live orders.

## Setup

```bash
cd "/Users/gytissalcius/Documents/project-offense"
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Optional Yahoo Finance data support:

```bash
pip install -e ".[data]"
```

## Run A Backtest

Offline deterministic demo:

```bash
project-offense --demo --output-dir reports_output
```

With a CSV of daily close prices:

```bash
project-offense --prices-csv prices.csv --benchmark SPY --output-dir reports_output
```

The CSV should have a date index in the first column and one ticker per column, including the benchmark symbol.

## Reports

The CLI writes `equity_curve.csv`, `weights.csv`, `trades.csv`, `dry_run_orders.csv`, and `metrics.csv`.

## Tests

```bash
python3 -m unittest discover -s project_offense/tests
```

## Assumptions

- Signals are computed from adjusted daily close prices.
- A rebalance decision made on date `T` uses data only through `T-1`.
- Trades are modeled at the rebalance close after that day's portfolio return is applied.
- Cash earns zero interest.
- Transaction costs include minimum commission, percentage commission, and bid-ask slippage.
- Live order placement is not implemented.
