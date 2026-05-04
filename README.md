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

- `audit_report.md`
- `cash_curve.csv`
- `equity_curve.csv`
- `dry_run_orders.csv`
- `metrics.csv`
- `positions.csv`
- `reconciliation_report.csv`
- `skipped_trades.csv`
- `trades.csv`
- `weights.csv`

`audit_report.md` records data source metadata, validation status, validation warnings/errors, benchmark ticker, data date range, row count, and ticker count. Validation warnings do not necessarily block a backtest, but they must be reviewed before trusting results. Synthetic data is clearly marked in both the CLI output and audit report.

The audit report also records the backtest timing convention, transaction cost assumptions, number of rebalances, number of trades, skipped trade counts, missing-price skips, minimum-trade-size skips, cash-constrained order resizing, leverage attempts, and whether cash ever went negative. Cash-constrained resizing is normal accounting behavior; it is reported separately from leverage attempts.

`reconciliation_report.csv` proves daily accounting with `reported_equity = cash + positions_market_value`. Rows include cash, positions market value, reported equity, recalculated equity, difference, and reconciliation status.

## Tests

```bash
python3 -m unittest discover -s project_offense/tests
```

## Assumptions

- Signals are computed from adjusted daily close prices.
- Monthly signals are computed at the close of the last available trading day of each calendar month.
- The rebalance decision is made after that signal-date close.
- Trades execute on the next available trading day after the decision date.
- The engine tracks cash and shares explicitly; buys are capped by available cash after estimated costs.
- Fractional shares are allowed by default. Set `StrategyConfig(allow_fractional_shares=False)` to round share quantities down to whole shares.
- The first benchmark return is set to `0.0` by convention. Missing benchmark returns after the first row are fatal in validated runs.
- Date validation uses configurable maximum calendar-day gaps instead of requiring every weekday. Normal weekend gaps and short holiday-like weekday gaps are allowed; long unexplained gaps are rejected.
- Cash earns zero interest.
- Transaction costs include minimum commission, percentage commission, and bid-ask slippage.
- Trades below the configured minimum trade size are skipped and logged.
- Trades with missing or unusable execution prices are skipped and logged.
- Live order placement is not implemented.
