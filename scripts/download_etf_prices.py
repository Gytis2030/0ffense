from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys
import time
from typing import Callable

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_offense.data.universe import UniverseAsset, load_universe


DEFAULT_UNIVERSE_CONFIG = "config/etf_universe.yaml"
DEFAULT_OUTPUT = "data/real/etf_prices.csv"
DEFAULT_PARTIAL_OUTPUT = "data/real/etf_prices_partial.csv"
DEFAULT_START = "2015-01-01"
DEFAULT_RETRIES = 3
DEFAULT_TIMEOUT = 60


def yahoo_symbol_for_asset(asset: UniverseAsset) -> str:
    """Map a Project Offense ticker to a Yahoo Finance ticker."""
    if "." in asset.ticker:
        return asset.ticker
    if asset.exchange.upper() == "LSE":
        return f"{asset.ticker}.L"
    return asset.ticker


def download_etf_prices(
    *,
    universe_config: str | Path = DEFAULT_UNIVERSE_CONFIG,
    output: str | Path = DEFAULT_OUTPUT,
    partial_output: str | Path = DEFAULT_PARTIAL_OUTPUT,
    start: str = DEFAULT_START,
    end: str | None = None,
    retries: int = DEFAULT_RETRIES,
    timeout: int = DEFAULT_TIMEOUT,
    allow_partial: bool = False,
    downloader: Callable[..., pd.DataFrame] | None = None,
) -> pd.DataFrame:
    universe = load_universe(universe_config)
    assets = list(universe.assets)
    if not assets:
        raise RuntimeError(f"No assets found in universe config: {universe_config}")

    downloader = downloader or _yfinance_download
    end = end or date.today().isoformat()
    series_by_ticker: dict[str, pd.Series] = {}
    failures: list[str] = []

    for asset in assets:
        yahoo_symbol = yahoo_symbol_for_asset(asset)
        try:
            raw = _download_with_retries(
                downloader,
                yahoo_symbol,
                start=start,
                end=end,
                retries=retries,
                timeout=timeout,
            )
            adjusted_close = _extract_adjusted_close(raw, yahoo_symbol)
        except Exception as exc:  # noqa: BLE001 - CLI script should aggregate clear ticker errors.
            failures.append(f"{asset.ticker} ({yahoo_symbol}): {exc}")
            continue

        adjusted_close = adjusted_close.dropna()
        if adjusted_close.empty:
            failures.append(f"{asset.ticker} ({yahoo_symbol}): no adjusted close rows returned")
            continue
        series_by_ticker[asset.ticker] = adjusted_close.rename(asset.ticker)

    if not series_by_ticker:
        details = "; ".join(failures) if failures else "no downloader details"
        raise RuntimeError(f"Failed to download ETF prices for all tickers. Details: {details}")

    prices = pd.concat(series_by_ticker.values(), axis=1).sort_index().dropna(how="any")
    if prices.empty:
        raise RuntimeError("Downloaded ticker histories have no overlapping adjusted-close dates after dropping missing rows.")
    prices.index.name = "date"
    failed_tickers = [asset.ticker for asset in assets if asset.ticker not in series_by_ticker]
    if failed_tickers:
        partial_path = Path(partial_output)
        partial_path.parent.mkdir(parents=True, exist_ok=True)
        prices.to_csv(partial_path)
        message = _failure_message(failed_tickers, failures, partial_path)
        if not allow_partial:
            raise RuntimeError(message)
        print(f"WARNING: {message}", file=sys.stderr)
        prices.attrs["output_path"] = str(partial_path)
        prices.attrs["failed_tickers"] = tuple(failed_tickers)
        return prices

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    prices.to_csv(output_path)
    prices.attrs["output_path"] = str(output_path)
    prices.attrs["failed_tickers"] = ()
    return prices


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download ETF adjusted close prices for Project Offense.")
    parser.add_argument("--universe-config", default=DEFAULT_UNIVERSE_CONFIG)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--partial-output", default=DEFAULT_PARTIAL_OUTPUT)
    parser.add_argument("--start-date", "--start", dest="start_date", default=DEFAULT_START)
    parser.add_argument("--end-date", "--end", dest="end_date", default=date.today().isoformat())
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--allow-partial", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        prices = download_etf_prices(
            universe_config=args.universe_config,
            output=args.output,
            partial_output=args.partial_output,
            start=args.start_date,
            end=args.end_date,
            retries=args.retries,
            timeout=args.timeout,
            allow_partial=args.allow_partial,
        )
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    output_path = Path(str(prices.attrs.get("output_path", args.output)))
    print(f"Wrote {len(prices)} daily rows for {len(prices.columns)} tickers to {output_path.resolve()}")


def _yfinance_download(*args: object, **kwargs: object) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError('yfinance is required. Install it with: pip install -e ".[data]"') from exc
    return yf.download(*args, **kwargs)


def _download_with_retries(
    downloader: Callable[..., pd.DataFrame],
    yahoo_symbol: str,
    *,
    start: str,
    end: str,
    retries: int,
    timeout: int,
) -> pd.DataFrame:
    if retries < 1:
        raise RuntimeError("retries must be at least 1")
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return downloader(
                yahoo_symbol,
                start=start,
                end=end,
                progress=False,
                auto_adjust=False,
                timeout=timeout,
            )
        except Exception as exc:  # noqa: BLE001 - retry loop should preserve last downloader error.
            last_error = exc
            if attempt < retries:
                time.sleep(min(2 ** (attempt - 1), 5))
    raise RuntimeError(f"failed after {retries} attempts: {last_error}")


def _extract_adjusted_close(raw: pd.DataFrame, yahoo_symbol: str) -> pd.Series:
    if raw is None or raw.empty:
        raise RuntimeError("empty download result")
    if isinstance(raw.columns, pd.MultiIndex):
        if "Adj Close" in raw.columns.get_level_values(0):
            adjusted = raw["Adj Close"]
            if isinstance(adjusted, pd.DataFrame):
                if yahoo_symbol in adjusted.columns:
                    return adjusted[yahoo_symbol]
                if len(adjusted.columns) == 1:
                    return adjusted.iloc[:, 0]
        raise RuntimeError("download result does not contain Adj Close")
    if "Adj Close" not in raw.columns:
        raise RuntimeError("download result does not contain Adj Close")
    return raw["Adj Close"]


def _failure_message(failed_tickers: list[str], failures: list[str], partial_path: Path) -> str:
    details = "; ".join(failures) if failures else "no downloader details"
    return (
        "Failed to download ETF prices for: "
        f"{', '.join(failed_tickers)}. Successfully downloaded tickers were saved to "
        f"{partial_path}. Details: {details}"
    )


if __name__ == "__main__":
    main()
