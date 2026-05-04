# Project Offense Code Review v0

## Executive summary

The repository is a useful scaffold, but it should not yet be trusted for financial conclusions, capital allocation, or broker integration. The largest risks are not small implementation details; they are structural research-validity gaps around universe construction, missing data, execution timing, benchmark comparability, and transaction cost realism.

The current backtester makes a visible attempt to avoid look-ahead bias by using `asof_date = prices.index[i - 1]` for monthly rebalance decisions in `project_offense/backtest/engine.py`. That is directionally correct. However, the system still has material ways to produce misleading results: it assumes the supplied asset universe is valid for the full backtest, converts missing returns to zero, uses synthetic data with smooth survivor-like assets, compares against an uncosted fully invested benchmark, and generates dry-run orders from final target weights rather than executable deltas.

The right next step is hardening the research substrate before adding features: define the investable universe through time, build explicit data-quality rules, make rebalance/execution timing configurable and testable, improve benchmark accounting, and expand tests around pathologic market-data cases.

## Critical issues

1. Survivorship bias is completely uncontrolled.

   The system takes a static list of symbols from CLI arguments or CSV columns and treats them as continuously investable (`project_offense/cli.py`, lines 15 and 31; `project_offense/backtest/engine.py`, lines 44-45). There is no point-in-time index membership, no listing date, no delisting date, no corporate-action lifecycle, and no delisting return handling. Any backtest over today’s winners will overstate performance.

2. Missing prices are converted into zero returns.

   `asset_returns = assets.pct_change().fillna(0.0)` and `benchmark_returns = benchmark.pct_change().fillna(0.0)` in `project_offense/backtest/engine.py`, lines 46-47, turn missing data into flat returns. That can silently treat suspended, stale, delisted, not-yet-listed, or bad data as cash-like holdings. It also hides benchmark data gaps.

3. Stale prices and delistings are not modeled.

   There is no detection of repeated unchanged prices, halted names, missing bars after entry, terminal missing prices, merger cash-outs, bankruptcy losses, or forced liquidation. Current holdings can remain in `current_weights` indefinitely even if subsequent prices become invalid.

4. Benchmark comparison is not economically comparable.

   Strategy returns are net of modeled transaction costs, but benchmark returns are simple `pct_change()` with zero transaction cost, no benchmark allocation regime, no cash drag, no dividend/source validation beyond `auto_adjust=True` when using yfinance, and no explicit buy-and-hold equity curve (`project_offense/backtest/engine.py`, lines 46-47 and 102). This may be acceptable for a rough baseline, but not for a strict after-cost comparison.

5. The order report is not a real rebalance order report.

   `build_order_report()` receives final weights only and outputs `BUY` rows for positive target holdings (`project_offense/reports/orders.py`, lines 8-24). It does not compare current vs target holdings, cannot produce sells, ignores current positions/cash, ignores minimum trade size, ignores order value after costs, rounds only with floor division, and does not identify whether orders are stale relative to the last rebalance date.

6. Backtest execution timing is under-specified and probably optimistic.

   The engine applies the day’s return using old weights, then rebalances on the same date using yesterday’s signal data (`project_offense/backtest/engine.py`, lines 57-79). This is internally consistent if interpreted as trading at the close of the rebalance date using prior close data, but it does not model open/close prices, execution delay, market-on-close availability, or next-day execution. Daily close-only data cannot validate same-day close execution from prior close signals without an explicit convention.

## Important issues

1. The monthly rebalance rule is simplistic.

   `monthly_rebalance_dates()` selects the first available date in the input index for each month (`project_offense/backtest/calendar.py`, lines 6-9). If the price index is not a clean exchange calendar, a missing first trading day shifts the rebalance to the first available data row without warning. There is no exchange calendar, holiday calendar, timezone handling, or "rebalance at month end vs month start" policy.

2. Signal availability is not enforced per asset.

   `ranking_scores()` masks only with current-day `prices.notna()` (`project_offense/signals/ranking.py`, line 21). It does not require a continuous lookback window, sufficient trading days, non-stale prices, or valid volume/liquidity. Some NaN handling comes indirectly from rolling windows and `dropna()` in portfolio construction, but it is not a formal data contract.

3. Momentum definitions are approximate.

   Twelve-month excluding most recent month uses 252 and 21 trading-day constants (`project_offense/features/indicators.py`, lines 5 and 33). Six-month momentum uses 126 days (`line 34`). This is acceptable as a first approximation, but the README and metrics should disclose that these are trading-day approximations, not calendar-month endpoints.

4. The 200-day trend filter is cross-sectionally mixed with ranks.

   `trend_200` is added as a binary 0/1 component (`project_offense/signals/ranking.py`, lines 14-19). This is not wrong, but it means trend is not a hard filter; an asset below its 200-day average can still rank highly. If the intended design is a trend filter, this implementation is weaker than the requirement implies.

5. Inverse-volatility weights may fail concentration expectations.

   The default `top_n=5` and `max_weight=0.20` imply a fully invested portfolio can only reach 100% if exactly five names are selected and all cap at 20%. If fewer valid names exist, exposure may be materially below the regime target. That may be desirable, but it is not reported.

6. Transaction cost modeling is weak.

   The model uses a flat minimum commission, percentage commission, and fixed bps slippage (`project_offense/backtest/costs.py`, lines 22-28). It does not model spread by asset, liquidity/ADV, order size impact, borrow constraints, SEC/TAF fees, exchange fees, odd lots, fractional shares, taxes, market impact, or different buy/sell costs.

7. Cost and position accounting are weight-based, not share/cash based.

   Trades are calculated from `delta_weight * equity` (`project_offense/backtest/costs.py`, line 34). The system never tracks shares, cash, lot sizes, residual cash, or price-specific fills. Weight changes after returns and costs are approximations.

8. Trade skipping can leave the portfolio away from target.

   Minimum trade size filtering skips small deltas (`project_offense/backtest/costs.py`, lines 35-36), and the engine only applies executable deltas (`project_offense/backtest/engine.py`, lines 73-75). That is reasonable, but the resulting drift is not reported, and skipped trades are not included in diagnostics.

9. Regime filter drawdown is a recent rolling drawdown, not total benchmark drawdown.

   `regime_exposure()` uses `rolling_max_drawdown(hist, 126).iloc[-1]` (`project_offense/backtest/engine.py`, line 35). The requirement says "if benchmark drawdown exceeds 10%" without specifying rolling or peak-to-date. This implementation uses a six-month rolling peak, which should be made explicit or changed.

10. Synthetic demo assumptions are unrealistic.

   `make_demo_prices()` creates all assets from correlated lognormal returns with positive drifts, no missing data, no jumps, no volatility clustering, no delistings, no splits, no stale prints, no borrow/liquidity constraints, and no regime changes (`project_offense/data/sources.py`, lines 26-43). It is useful for smoke tests only and should not be interpreted as strategy evidence.

11. yfinance data source is convenient but not institutional-grade.

   `download_yfinance()` uses adjusted close-style data through `auto_adjust=True` (`project_offense/data/sources.py`, line 18). It does not validate corporate actions, symbol changes, survivorship, delisted tickers, or data revisions. This is fine for demos, not for research-grade results.

12. Generated reports are committed.

   `reports_output/*.csv` is tracked in git. That makes the repository mix source code with generated artifacts and can cause stale report files to be mistaken for validated outputs.

## Nice-to-have issues

1. Add a formal configuration file format instead of only CLI flags and dataclasses.

2. Add logging for rebalance decisions, selected names, skipped names, regime exposure, and skipped trades.

3. Add type checking and linting once the core design stabilizes.

4. Add report metadata with run date, git commit, input data hash, symbols, benchmark, and cost assumptions.

5. Add chart generation only after metrics and accounting are trustworthy.

6. Add support for benchmark alternatives such as total-return index data, SPY ETF, equal-weight S&P 500, and cash benchmark.

## Recommended implementation order

1. Define the data contract.

   Require point-in-time symbol eligibility, listing/delisting dates, adjusted close semantics, missing-data policy, stale-price policy, benchmark source, and calendar assumptions.

2. Harden data validation before the backtest starts.

   Reject duplicate dates, unsorted dates, all-NaN assets, missing benchmark rows, non-business-day anomalies if not expected, insufficient lookbacks, and suspicious stale prices.

3. Fix missing-price and delisting behavior.

   Do not turn missing prices into zero returns globally. Add explicit rules for not-yet-listed assets, temporarily missing bars, stale holdings, forced exits, and terminal delisting returns.

4. Make execution timing explicit.

   Choose and document one convention: signal at prior close, trade at next open; signal at prior close, trade at current close; or signal at month-end close, trade next trading day. Then encode it in tests.

5. Upgrade benchmark accounting.

   Produce a benchmark equity curve with the same date range, explicit dividend adjustment assumption, optional transaction costs for benchmark implementation, and cash/regime comparability where relevant.

6. Replace final-holding dry-run orders with rebalance-order generation.

   Generate orders from current holdings to target holdings, include sells, skipped trades, estimated costs, cash impact, and timestamp/as-of date.

7. Improve transaction cost realism.

   Add per-asset spread assumptions, liquidity/ADV caps, market impact, and separate buy/sell fee components.

8. Expand tests around failure modes.

   Use deterministic miniature price panels that deliberately include missing bars, stale prices, delistings, benchmark gaps, and non-trading-day rows.

9. Only then consider IBKR paper integration.

   Keep broker code disabled until order generation, accounting, and data validation are reliable.

## Tests that should be added

1. Rebalance timing test proving that a large price move on the rebalance date cannot affect that date's target weights.

2. Test that missing asset prices after entry do not become zero returns silently.

3. Test that a not-yet-listed asset cannot be selected before it has a full lookback history.

4. Test stale-price detection using repeated unchanged prices over a configurable window.

5. Test delisting behavior, including terminal loss or forced liquidation.

6. Test benchmark missing-data rejection.

7. Test duplicate-date and unsorted-index handling.

8. Test that first-trading-day monthly rebalancing behaves correctly when the first session of the month is absent from the input data.

9. Test that same-day execution and next-day execution produce different, expected returns in a toy dataset.

10. Test that the regime filter uses the intended drawdown definition.

11. Test that benchmark metrics align on exactly the same dates as strategy returns.

12. Test that dry-run orders include sells when target weight is below current weight.

13. Test that dry-run orders respect minimum trade size and estimated transaction costs.

14. Test that `IBKRPaperBroker.place_orders()` always raises and cannot submit orders.

15. Test that generated reports are reproducible and include run metadata.

16. Test that committed sample reports are not required for package operation.

## Parts of the code that look safe

1. The broker stub is intentionally non-executing.

   `IBKRPaperBroker.place_orders()` raises unconditionally (`project_offense/broker/ibkr_paper.py`, lines 15-16), and preview orders set `transmit = False` (`lines 9-13`). This is safe as a placeholder.

2. Rebalance decisions use prior-row signal data.

   `asof_date = prices.index[i - 1]` is used before target weights are calculated (`project_offense/backtest/engine.py`, lines 63-71). This reduces the most obvious same-row look-ahead risk.

3. Rolling indicators use backward-looking pandas windows.

   Momentum, SMA, volatility, and rolling drawdown are built with shifts or rolling windows (`project_offense/features/indicators.py`, lines 12-28). The formulas are not forward-looking by themselves.

4. Minimum trade-size skipping is at least enforced in the cost path.

   `trade_costs()` skips deltas below `min_trade_value` (`project_offense/backtest/costs.py`, lines 31-38). The behavior needs more diagnostics, but the basic condition exists.

5. Tests exist and run with standard-library `unittest`.

   The current tests are narrow, but they cover an initial no-future-date assertion, rebalance date selection, minimum trade size, and cost calculation (`project_offense/tests/test_backtest.py`).

## Parts of the code that should not be trusted yet

1. Any reported CAGR, Sharpe, Sortino, beta, tracking error, or information ratio from the current engine should be treated as illustrative only.

2. Any performance comparison against `SPY` should be treated as preliminary because benchmark accounting and data-quality controls are insufficient.

3. Any result from the synthetic demo should be treated as a smoke test, not strategy evidence.

4. Any result using a hand-picked current ticker list should be assumed survivorship-biased unless proven otherwise.

5. Any result across assets with missing prices, stale prices, ticker changes, or delistings should be considered invalid until explicit handling is implemented.

6. The dry-run order report should not be used for actual trading decisions because it reports final positive holdings, not executable rebalance orders.

7. The transaction cost model should not be trusted for small-cap, illiquid, high-turnover, stressed-market, or large-notional scenarios.

8. The IBKR module should remain disconnected from any real or paper account until order generation and accounting are redesigned and tested.
