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
    top_n: int = 5
    max_position_weight: float = 0.20
    benchmark_symbol: str = "SPY"
    starting_cash: float = 100_000.0
    cost: CostConfig = CostConfig()
    active_universe: Sequence[str] | None = None
    allow_fractional_shares: bool = True
