from __future__ import annotations

import pandas as pd


class IBKRPaperBroker:
    live_trading_enabled = False

    def preview_orders(self, order_report: pd.DataFrame) -> list[dict[str, object]]:
        orders = order_report.copy()
        orders["account_type"] = "PAPER"
        orders["transmit"] = False
        return orders.to_dict(orient="records")

    def place_orders(self, _: pd.DataFrame) -> None:
        raise RuntimeError("Live and paper order submission are disabled in this research build.")
