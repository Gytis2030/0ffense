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

## Real ETF CSV Research Workflow

Project Offense supports local real-data research through validated CSV input. Real-data runs must go through `PriceData` validation. Synthetic/demo data remains blocked unless `--allow-synthetic` is explicitly supplied.

Project Offense validates declared metadata and price structure. It cannot independently prove that a user-provided CSV is genuine market data. You are responsible for sourcing real adjusted-close or total-return price data from a trusted provider and for keeping provenance records outside the backtest output.

Recommended local directory structure:

```text
data/
  real/
    etf_prices.csv
    metadata.yaml
```

Do not commit large market data files by default. `data/real/metadata.example.yaml` is included as a template.

To download the starter ETF universe from Yahoo Finance into `data/real/etf_prices.csv`:

```bash
pip install -e ".[data]"
python3 scripts/download_etf_prices.py
```

The downloader reads `config/etf_universe.yaml`, maps LSE tickers to Yahoo symbols such as `CSPX -> CSPX.L`, downloads daily adjusted close prices from `2015-01-01` through today, and writes project ticker columns such as `CSPX`, `IWDA`, and `EIMI`. The generated `data/real/etf_prices.csv` and `data/real/etf_prices_partial.csv` files are ignored by git by default.

Optional arguments:

```bash
python3 scripts/download_etf_prices.py \
  --universe-config config/etf_universe.yaml \
  --output data/real/etf_prices.csv \
  --start-date 2015-01-01 \
  --end-date YYYY-MM-DD
```

Yahoo Finance can occasionally time out on individual tickers. The downloader requests tickers one by one, retries each ticker three times by default, and uses a longer Yahoo timeout. If any ticker still fails, the script writes successfully downloaded tickers to `data/real/etf_prices_partial.csv` and fails unless `--allow-partial` is supplied.

Partial download example:

```bash
python3 scripts/download_etf_prices.py \
  --allow-partial \
  --output data/real/etf_prices.csv
```

Useful downloader flags:

- `--start-date`: first download date, default `2015-01-01`
- `--end-date`: final download date, default today
- `--output`: full-data CSV path, default `data/real/etf_prices.csv`
- `--partial-output`: partial-data CSV path, default `data/real/etf_prices_partial.csv`
- `--retries`: attempts per ticker, default `3`
- `--timeout`: Yahoo request timeout in seconds, default `60`
- `--allow-partial`: keep successful tickers and warn instead of failing when some tickers fail

`data/real/etf_prices.csv` should be wide daily price data with one date column and one column per ticker:

```csv
date,IWDA,EIMI,IUIT,IUHC,AGGU,IGLN,CSPX
2024-01-02,78.10,31.42,26.80,8.91,5.12,36.20,512.44
2024-01-03,77.94,31.20,26.72,8.89,5.13,36.18,510.10
```

`data/real/metadata.yaml` should describe the CSV:

```yaml
source_name: local_real_etf_csv
is_synthetic: false
price_type: adjusted_close
currency: USD
timezone: Europe/London
```

Supported `price_type` metadata values are `adjusted_close`, `total_return`, and `raw_close`. The default production validation profile currently requires `adjusted_close`.

`is_synthetic` is parsed strictly. Use YAML booleans `true` / `false` or strings `"true"` / `"false"` only. Ambiguous values such as `"yes"`, `"no"`, `"0"`, or `"1"` are rejected.

`timezone` is validated as an IANA timezone string, for example `Europe/London` or `America/New_York`. Timezone is metadata-only for the current daily-close workflow; it is recorded in audit outputs but does not shift daily bars.

The default ETF universe in `config/etf_universe.yaml` is a small UCITS-focused starter universe. It uses `CSPX` as the benchmark entry and keeps the tradable set intentionally limited while the workflow is being validated.

Run the first real ETF research backtest:

```bash
python3 -m project_offense.cli \
  --price-csv data/real/etf_prices.csv \
  --metadata data/real/metadata.yaml \
  --universe-config config/etf_universe.yaml \
  --strategy defensive_momentum_v1 \
  --benchmark CSPX \
  --output-dir reports_output_real_etf
```

The benchmark can be selected with `--benchmark`. If omitted, the CLI uses the first `role: benchmark` ticker from the universe config, or `SPY` when no universe benchmark is available. The benchmark ticker must exist in the price CSV. A benchmark ticker may also be listed in the universe config with `role: benchmark`; it is used for comparison and excluded from tradable assets.

Expected real-data report files include `audit_report.md`, `research_report.md`, `objective_scorecard.md`, `objective_scorecard.csv`, `monthly_returns.csv`, `weekly_returns.csv`, `rolling_metrics.csv`, `reconciliation_report.csv`, `skipped_trades.csv`, `cash_curve.csv`, and `positions.csv`.

## Strategy Research

The default strategy configuration is `defensive_momentum_v1`. It exposes the following research parameters without optimizing them for maximum historical performance:

- `lookback_12m`
- `skip_recent_month`
- `lookback_6m`
- `volatility_lookback`
- `trend_ma_window`
- `top_n`
- `max_position_weight`
- `rebalance_frequency`
- `regime_filter_enabled`
- `allow_fractional_shares`
- `risk_free_rate`

Run a research backtest with the same CLI command used for a normal backtest:

```bash
project-offense --demo --allow-synthetic --strategy defensive_momentum_v1 --universe-config config/stock_universe.yaml --output-dir reports_output
```

Research outputs are written automatically. Use `research_report.md` for the high-level objective comparison versus the benchmark, and `strategy_score_summary.csv` for the metric table. The default research reports assume `risk_free_rate = 0.0` unless the strategy config is changed.

## Project Offense Objective Scorecard

The objective scorecard is a formal PASS / FAIL / INCONCLUSIVE gate for deciding whether a backtest supports the Project Offense objective. It is not a parameter optimizer and should not be used to tune the strategy to a single historical sample.

Default objectives require:

- strategy CAGR to exceed benchmark CAGR after costs
- strategy volatility to be below benchmark volatility
- strategy max drawdown to be less severe than benchmark max drawdown
- worst weekly return to be less severe than benchmark
- negative week frequency to be no worse than benchmark
- turnover, full-period cost drag, and annualized cost drag to remain acceptable
- average executed trade size to remain practical for a small account
- enough backtest years, rebalances, and trades to evaluate the result

Scorecard statuses:

- `PASS`: evidence is sufficient and all required return, risk, drawdown, behavioral, and cost/practicality objectives pass.
- `FAIL`: evidence is sufficient, but one or more critical Project Offense objectives fail.
- `INCONCLUSIVE`: the backtest period is too short, there are too few rebalances or trades, required metrics are unavailable, benchmark data is insufficient, or validation warnings must be reviewed.

Synthetic/demo data always blocks a Project Offense `PASS` by forcing evidence quality to `INCONCLUSIVE`. This is research infrastructure, not live trading software, and no order placement is implemented.

The default threshold profile is defined by `ObjectiveConfig` in `project_offense.research.scorecard`.

Default numeric thresholds:

- `minimum_excess_cagr`: `0.0`
- `maximum_relative_volatility`: `1.0`
- `maximum_relative_drawdown`: `1.0`
- `maximum_worst_week`: `1.0`
- `maximum_negative_week_frequency`: `1.0`
- `maximum_turnover`: `50.0`
- `maximum_cost_drag`: `0.10`
- `maximum_annualized_cost_drag`: `0.02`
- `minimum_average_trade_size`: `50.0`
- `minimum_backtest_years`: `3.0`
- `minimum_number_of_rebalances`: `24`
- `minimum_number_of_trades`: `20`

Evidence quality gates a `PASS`: synthetic/demo data, material validation warnings, short samples, too few rebalances, too few trades, unavailable benchmark evidence, or non-finite required metrics make the scorecard `INCONCLUSIVE` unless a critical objective already clearly fails. In that case the overall status is `FAIL`, because a strategy can be rejected even when evidence is not sufficient for approval.

Reports write `objective_scorecard.csv` for row-level objective results and `objective_scorecard.md` for the human-readable status summary. `research_report.md` also includes a compact scorecard section and failed/inconclusive objective reasons.

Metric conventions:

- CAGR is calculated from the first and last valid net equity values and annualized using elapsed calendar days divided by 365.25.
- Daily volatility, Sharpe, Sortino, beta, tracking error, information ratio, hit rate, weekly returns, monthly returns, and rolling metrics exclude the artificial first-day `0.0` return inserted by the backtest engine.
- Sharpe and Sortino use the configured annual `risk_free_rate`; Sortino measures downside deviation against the per-period minimum acceptable return over the full daily return sample.
- Calmar is CAGR divided by absolute max drawdown. It is reported as `0.0` when drawdown is zero because the ratio is undefined.
- Turnover is `sum(abs(executed trade value)) / average equity`; skipped trades are excluded.
- Cost drag is full-period `sum(actual deducted costs) / initial equity`; `annualized_cost_drag` is that full-period drag divided by elapsed years.
- Weekly returns use `W-FRI` resampling and monthly returns use calendar month-end resampling.
- Weekly and monthly returns are net of trading costs because they are derived from the net equity curve.

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
- Extreme daily returns are rejected.
- Stale prices are calibrated with separate warning and error thresholds. By default, unchanged-price streaks of at least 5 rows but fewer than 15 rows produce validation warnings, while streaks of 15 rows or more are fatal. Warnings include ticker, streak length, start date, and end date.

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
- `objective_scorecard.csv`
- `objective_scorecard.md`
- `positions.csv`
- `reconciliation_report.csv`
- `research_report.md`
- `rolling_metrics.csv`
- `skipped_trades.csv`
- `strategy_score_summary.csv`
- `trades.csv`
- `weekly_returns.csv`
- `monthly_returns.csv`
- `weights.csv`

`audit_report.md` records data source metadata, validation status, validation warnings/errors, benchmark ticker, data date range, row count, and ticker count. Validation warnings do not necessarily block a backtest, but they must be reviewed before trusting results. Synthetic data is clearly marked in both the CLI output and audit report.

The audit report also records the backtest timing convention, transaction cost assumptions, number of rebalances, number of trades, skipped trade counts, missing-price skips, minimum-trade-size skips, cash-constrained order resizing, leverage attempts, and whether cash ever went negative. Cash-constrained resizing is normal accounting behavior; it is reported separately from leverage attempts.

`reconciliation_report.csv` proves daily accounting with `reported_equity = cash + positions_market_value`. Rows include cash, positions market value, reported equity, recalculated equity, difference, and reconciliation status.

`research_report.md` compares the strategy against the benchmark on net return, volatility, max drawdown, worst week, negative week frequency, turnover, and cost drag. It also includes a metric definitions section with the CAGR, risk-free rate, Sortino, Calmar, turnover, cost drag, and resampling conventions. `rolling_metrics.csv` contains rolling 3-month, 6-month, and 12-month returns, volatility, drawdown, and beta to benchmark.

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
- Stale-price validation reports short unchanged ETF price streaks as warnings and long unchanged streaks as fatal errors. Validation warnings flow into CLI output, `BacktestResult.data_audit`, `audit_report.md`, and the scorecard evidence-quality gate.
- Cash earns zero interest.
- Transaction costs include minimum commission, percentage commission, and bid-ask slippage.
- Trades below the configured minimum trade size are skipped and logged.
- Trades with missing or unusable execution prices are skipped and logged.
- Live order placement is not implemented.
