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
project-offense --demo --allow-synthetic --output-dir reports_output
```

With the stock universe config:

```bash
project-offense --demo --allow-synthetic --universe-config config/stock_universe.yaml --output-dir reports_output
```

With the ETF universe config:

```bash
project-offense --demo --allow-synthetic --universe-config config/etf_universe.yaml --output-dir reports_output
```

With a CSV of daily close prices:

```bash
project-offense --prices-csv prices.csv --benchmark SPY --universe-config config/stock_universe.yaml --output-dir reports_output
```

The CSV should have a date index in the first column and one ticker per column, including the benchmark symbol and all tradable tickers in the selected universe. Extra ticker columns are ignored when `--universe-config` is supplied.

## Data Input Format

Local CSV data is loaded through `LocalCSVDataProvider`. The expected format is wide daily price data:

```csv
date,AAPL,MSFT,SPY
2024-01-02,184.73,370.87,472.65
2024-01-03,183.35,370.60,468.79
```

Requirements:

- The first column must be parseable dates.
- Dates must be unique and strictly increasing.
- The data must contain every business day in the requested range.
- Columns must be ticker symbols.
- Values must be adjusted close prices by default.
- Values must be positive and cannot contain NaNs.
- Stale prices and extreme daily returns are rejected.

Data metadata is tracked with:

- `source_name`
- `is_synthetic`
- `price_type`: `adjusted_close`, `total_return`, or `raw_close`
- `currency`
- `timezone`, when available

Production validation requires `price_type=adjusted_close` and `currency=USD` by default. Synthetic demo data is blocked unless `--allow-synthetic` is passed explicitly.

All production backtests must use validated `PriceData`. The main `run_backtest()` entry point rejects raw `pandas.DataFrame` inputs and unvalidated `PriceData`. Validation attaches a result object with fatal `errors`, non-fatal `warnings`, and the synthetic-data allowance used for the run. A raw DataFrame escape hatch exists only as `run_backtest_unsafe_from_dataframe(..., allow_unsafe=True)` for tests and debugging.

Legacy convenience helpers such as `read_price_csv()` and `make_demo_prices()` return unvalidated `PriceData`; callers must pass that object through `validate_price_data()` before running a production backtest.

CSV metadata can be supplied through CLI flags:

```bash
project-offense \
  --prices-csv prices.csv \
  --price-type adjusted_close \
  --currency USD \
  --timezone America/New_York \
  --universe-config config/stock_universe.yaml
```

## Universe Configs

Universe configs live in `config/`:

- `config/stock_universe.yaml`
- `config/etf_universe.yaml`

Each asset entry must include:

- `ticker`
- `exchange`
- `currency`
- `asset_class`
- `role`
- `minimum_trade_size`

Only `USD` assets are currently supported. Entries with `role: benchmark` are metadata and are not traded. When a universe config is supplied, the strategy is restricted to non-benchmark tickers from that active universe.

## Reports

The CLI writes:

- `equity_curve.csv`
- `weights.csv`
- `trades.csv`
- `dry_run_orders.csv`
- `metrics.csv`
- `audit_report.md`

`audit_report.md` records data source metadata, validation status, validation warnings/errors, benchmark ticker, data date range, row count, and ticker count. Validation warnings do not necessarily block a backtest, but they must be reviewed before trusting results. Synthetic data is clearly marked in both the CLI output and audit report.

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
