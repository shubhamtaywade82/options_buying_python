"""
Handles position lifecycle, SL/TP monitoring.
Order placement functions moved to data_layer.py (using DhanHQ-py SDK).
"""
import asyncio
from typing import List, Dict
from dataclasses import dataclass, field
from datetime import datetime
from config import STOP_LOSS_PCT, TARGET_PCT

from data_layer import check_margin, get_fund_limits, place_buy_order, place_exit_order


@dataclass
class OptionLeg:
    security_id: str
    option_type: str
    strike: float
    entry_price: float
    lots: int
    lot_size: int
    order_id: str = ""
    status: str = "OPEN"   # OPEN | SL_HIT | TP_HIT | TIME_EXIT
    entry_time: datetime = field(default_factory=datetime.now)

    @property
    def quantity(self) -> int:
        return self.lots * self.lot_size

    @property
    def sl_price(self) -> float:
        return round(self.entry_price * (1 - STOP_LOSS_PCT), 1)

    @property
    def tp_price(self) -> float:
        return round(self.entry_price * (1 + TARGET_PCT), 1)

    @property
    def max_loss(self) -> float:
        return self.entry_price * STOP_LOSS_PCT * self.quantity


async def monitor_positions(
    legs: List["OptionLeg"],
    ticks: Dict[str, float],     # security_id -> current LTP (from WS feed)
) -> None:
    """
    Called on every tick update.
    Fires SL/TP exits when thresholds are breached.
    """
    now = datetime.now()

    for leg in legs:
        if leg.status != "OPEN":
            continue

        ltp = ticks.get(leg.security_id)
        if ltp is None:
            continue

        # Theta time stop: 2 PM on expiry day
        if now.hour >= 14 and now.minute >= 0:
            print(f"[Monitor] Time stop triggered for {leg.security_id}")
            await place_exit_order(leg.security_id, leg.quantity)
            leg.status = "TIME_EXIT"
            continue

        # Hard Stop Loss
        if ltp <= leg.sl_price:
            print(f"[Monitor] SL HIT {leg.security_id} ltp={ltp} sl={leg.sl_price}")
            await place_exit_order(leg.security_id, leg.quantity)
            leg.status = "SL_HIT"
            continue

        # Target Profit
        if ltp >= leg.tp_price:
            print(f"[Monitor] TP HIT {leg.security_id} ltp={ltp} tp={leg.tp_price}")
            await place_exit_order(leg.security_id, leg.quantity)
            leg.status = "TP_HIT"
            continue