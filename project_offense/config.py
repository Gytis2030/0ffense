from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class CostConfig:
    min_commission: float = 1.0
    commission_pct: float = 0.0005
    slippage_bps: float = 5.0
    min_trade_value: float = 50.0


@dataclass(frozen=True)
class StrategyConfig:
    name: str = "defensive_momentum_v1"
    lookback_12m: int = 252
    skip_recent_month: int = 21
    lookback_6m: int = 126
    volatility_lookback: int = 126
    trend_ma_window: int = 200
    top_n: int = 5
    max_position_weight: float = 0.20
    rebalance_frequency: str = "monthly"
    regime_filter_enabled: bool = True
    benchmark_symbol: str = "SPY"
    starting_cash: float = 100_000.0
    risk_free_rate: float = 0.0
    cost: CostConfig = CostConfig()
    active_universe: Sequence[str] | None = None
    allow_fractional_shares: bool = True


def defensive_momentum_v1(**overrides: object) -> StrategyConfig:
    """Default Project Offense defensive momentum configuration."""
    return StrategyConfig(**overrides)
