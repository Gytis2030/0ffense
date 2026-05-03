from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from project_offense.config import CostConfig


@dataclass(frozen=True)
class TradeCost:
    symbol: str
    trade_value: float
    commission: float
    slippage: float

    @property
    def total(self) -> float:
        return self.commission + self.slippage


def calculate_trade_cost(trade_value: float, config: CostConfig) -> tuple[float, float, float]:
    notional = abs(float(trade_value))
    if notional == 0:
        return 0.0, 0.0, 0.0
    commission = max(config.min_commission, notional * config.commission_pct)
    slippage = notional * (config.slippage_bps / 10_000.0)
    return commission, slippage, commission + slippage


def trade_costs(delta_weights: pd.Series, portfolio_value: float, config: CostConfig) -> list[TradeCost]:
    costs = []
    for symbol, delta_weight in delta_weights.items():
        trade_value = float(delta_weight) * portfolio_value
        if abs(trade_value) < config.min_trade_value:
            continue
        commission, slippage, _ = calculate_trade_cost(trade_value, config)
        costs.append(TradeCost(symbol, trade_value, commission, slippage))
    return costs
