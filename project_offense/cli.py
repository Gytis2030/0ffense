from __future__ import annotations

import argparse
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from project_offense.backtest.engine import run_backtest
from project_offense.config import CostConfig, defensive_momentum_v1
from project_offense.data.provider import LocalCSVDataProvider, SyntheticDemoDataProvider
from project_offense.data.sources import download_yfinance
from project_offense.data.universe import load_universe
from project_offense.data.validation import DataMetadata, DataValidationConfig, PriceData, validate_price_data
from project_offense.reports.orders import write_reports
from project_offense.research.scorecard import build_scorecard


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Project Offense backtest.")
    parser.add_argument("--prices-csv", "--price-csv", dest="prices_csv")
    parser.add_argument("--metadata", help="Optional YAML metadata for --prices-csv/--price-csv.")
    parser.add_argument("--symbols", nargs="+", default=["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "JPM", "XLV"])
    parser.add_argument("--benchmark")
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--strategy", default="defensive_momentum_v1", choices=["defensive_momentum_v1"])
    parser.add_argument("--output-dir", default="reports_output")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--allow-synthetic", action="store_true", help="Required when --demo is used.")
    parser.add_argument("--universe-config", help="YAML universe config. Example: config/stock_universe.yaml")
    parser.add_argument("--price-type", default="adjusted_close", choices=["adjusted_close", "total_return", "raw_close"])
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--timezone")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.demo and not args.allow_synthetic:
        raise SystemExit("--demo uses synthetic data; pass --allow-synthetic to run it explicitly.")
    universe = load_universe(args.universe_config) if args.universe_config else None
    benchmark = args.benchmark or _benchmark_from_universe(universe) or "SPY"
    active_tickers = list(universe.tradable_tickers) if universe else args.symbols
    active_tickers = [ticker for ticker in active_tickers if ticker != benchmark]
    symbols = active_tickers + [benchmark]
    if args.prices_csv:
        metadata = _load_metadata(args.metadata)
        provider = LocalCSVDataProvider(
            args.prices_csv,
            source_name=str(metadata.get("source_name", "local_csv")),
            is_synthetic=_parse_is_synthetic(metadata.get("is_synthetic", False)),
            price_type=str(metadata.get("price_type", args.price_type)),
            currency=str(metadata.get("currency", args.currency)),
            timezone=_parse_timezone(metadata.get("timezone", args.timezone)),
        )
        price_data = provider.load(symbols)
    elif args.demo:
        provider = SyntheticDemoDataProvider(benchmark=benchmark, start=args.start, currency=args.currency)
        price_data = provider.load(active_tickers)
    else:
        prices = download_yfinance(symbols, start=args.start)
        price_data = PriceData(
            prices=prices,
            metadata=DataMetadata(
                source_name="yfinance",
                is_synthetic=False,
                price_type="adjusted_close",
                currency=args.currency,
                timezone=args.timezone,
            ),
        )
    price_data = validate_price_data(price_data, DataValidationConfig(allow_synthetic=args.allow_synthetic))
    result = run_backtest(
        price_data,
        defensive_momentum_v1(
            top_n=args.top_n,
            benchmark_symbol=benchmark,
            cost=CostConfig(),
            active_universe=active_tickers if universe else None,
        ),
    )
    output_dir = Path(args.output_dir)
    write_reports(result, str(output_dir))
    print("Performance metrics")
    for key, value in result.metrics.items():
        print(f"{key}: {value:.4f}")
    _print_audit_summary(result.data_audit)
    _print_backtest_audit_summary(result.backtest_audit)
    _print_scorecard_summary(build_scorecard(result))
    print(f"Reports written to: {output_dir.resolve()}")


def _print_audit_summary(audit: dict[str, object]) -> None:
    print("Data audit")
    print(
        "source={source} price_type={price_type} currency={currency} benchmark={benchmark} rows={rows} tickers={tickers}".format(
            source=audit.get("source_name"),
            price_type=audit.get("price_type"),
            currency=audit.get("currency"),
            benchmark=audit.get("benchmark_ticker"),
            rows=audit.get("row_count"),
            tickers=audit.get("ticker_count"),
        )
    )
    if audit.get("is_synthetic"):
        print("WARNING: synthetic data was used; results are for demos/smoke tests only.")
    warnings = tuple(audit.get("validation_warnings") or ())
    if warnings:
        print("Validation warnings")
        for warning in warnings:
            print(f"- {warning}")


def _print_backtest_audit_summary(audit: dict[str, object]) -> None:
    print("Backtest audit")
    print(
        "rebalances={rebalances} trades={trades} skipped={skipped} skip_reasons={reasons} cash_resized_orders={cash_resized} leverage_attempted={leverage} cash_negative={cash_negative}".format(
            rebalances=audit.get("number_of_rebalances"),
            trades=audit.get("number_of_trades"),
            skipped=audit.get("number_of_skipped_trades"),
            reasons=audit.get("skipped_trade_reason_counts"),
            cash_resized=audit.get("number_of_cash_resized_orders"),
            leverage=audit.get("leverage_was_attempted"),
            cash_negative=audit.get("cash_went_negative"),
        )
    )


def _print_scorecard_summary(scorecard) -> None:
    print("Objective scorecard")
    print(
        "overall={overall} return={return_status} risk={risk} drawdown={drawdown} behavioral={behavioral} cost_practicality={cost} evidence_quality={evidence}".format(
            overall=scorecard.overall_status,
            return_status=scorecard.return_objective,
            risk=scorecard.risk_objective,
            drawdown=scorecard.drawdown_objective,
            behavioral=scorecard.behavioral_objective,
            cost=scorecard.cost_practicality_objective,
            evidence=scorecard.evidence_quality_objective,
        )
    )


def _benchmark_from_universe(universe) -> str | None:
    if universe and universe.benchmark_tickers:
        return universe.benchmark_tickers[0]
    return None


def _load_metadata(path: str | None) -> dict[str, object]:
    if not path:
        return {}
    with Path(path).open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise SystemExit("--metadata must point to a YAML mapping.")
    return raw


def _parse_is_synthetic(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    raise SystemExit("metadata is_synthetic must be a boolean true/false or string 'true'/'false'.")


def _parse_timezone(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise SystemExit("metadata timezone must be a valid IANA timezone string, such as Europe/London.")
    timezone = value.strip()
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise SystemExit(f"metadata timezone is not a valid IANA timezone: {timezone}.") from exc
    return timezone


if __name__ == "__main__":
    main()
