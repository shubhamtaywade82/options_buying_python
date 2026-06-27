"""
Handles order placement, SL/TP monitoring, and position lifecycle.
Uses: POST /v2/orders, GET /v2/positions, DELETE /v2/orders/{id}
"""
import asyncio
import aiohttp
from dataclasses import dataclass, field
from datetime import datetime
from config import (
    DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN,
    MAX_CAPITAL_PER_TRADE_PCT, STOP_LOSS_PCT, TARGET_PCT, MAX_OPEN_LEGS
)

BASE_URL = "https://api.dhan.co/v2"
HEADERS = {
    "access-token": DHAN_ACCESS_TOKEN,
    "Content-Type": "application/json",
}


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


async def check_margin(
    security_id: str,
    quantity: int,
    price: float,
    session: aiohttp.ClientSession,
) -> dict:
    """POST /v2/margincalculator — pre-trade margin check."""
    payload = {
        "dhanClientId": DHAN_CLIENT_ID,
        "exchangeSegment": "NSE_FNO",
        "transactionType": "BUY",
        "quantity": quantity,
        "productType": "INTRADAY",
        "securityId": security_id,
        "price": price,
    }
    async with session.post(
        f"{BASE_URL}/margincalculator",
        json=payload, headers=HEADERS
    ) as resp:
        resp.raise_for_status()
        return await resp.json()


async def get_fund_limits(session: aiohttp.ClientSession) -> dict:
    """GET /v2/fundlimit — available balance."""
    async with session.get(f"{BASE_URL}/fundlimit", headers=HEADERS) as resp:
        resp.raise_for_status()
        return await resp.json()


async def place_buy_order(
    security_id: str,
    quantity: int,
    price: float,              # Use 0 for MARKET
    session: aiohttp.ClientSession,
    order_type: str = "LIMIT",
) -> str:
    """
    POST /v2/orders — Naked BUY (INTRADAY, NSE_FNO).
    Returns orderId on success.
    """
    payload = {
        "dhanClientId": DHAN_CLIENT_ID,
        "transactionType": "BUY",
        "exchangeSegment": "NSE_FNO",
        "productType": "INTRADAY",
        "orderType": order_type,
        "validity": "DAY",
        "securityId": security_id,
        "quantity": quantity,
        "price": price,
        "disclosedQuantity": 0,
        "afterMarketOrder": False,
    }
    async with session.post(
        f"{BASE_URL}/orders", json=payload, headers=HEADERS
    ) as resp:
        resp.raise_for_status()
        data = await resp.json()
        order_id = data.get("orderId", "")
        print(f"[Order] Placed BUY {security_id} qty={quantity} @ {price} -> {order_id}")
        return order_id


async def place_exit_order(
    security_id: str,
    quantity: int,
    session: aiohttp.ClientSession,
) -> str:
    """MARKET SELL to exit position."""
    payload = {
        "dhanClientId": DHAN_CLIENT_ID,
        "transactionType": "SELL",
        "exchangeSegment": "NSE_FNO",
        "productType": "INTRADAY",
        "orderType": "MARKET",
        "validity": "DAY",
        "securityId": security_id,
        "quantity": quantity,
        "price": 0,
    }
    async with session.post(
        f"{BASE_URL}/orders", json=payload, headers=HEADERS
    ) as resp:
        resp.raise_for_status()
        data = await resp.json()
        return data.get("orderId", "")


async def monitor_positions(
    legs: list[OptionLeg],
    ticks: dict[str, float],     # security_id -> current LTP (from WS feed)
    session: aiohttp.ClientSession,
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
            await place_exit_order(leg.security_id, leg.quantity, session)
            leg.status = "TIME_EXIT"
            continue

        # Hard Stop Loss
        if ltp <= leg.sl_price:
            print(f"[Monitor] SL HIT {leg.security_id} ltp={ltp} sl={leg.sl_price}")
            await place_exit_order(leg.security_id, leg.quantity, session)
            leg.status = "SL_HIT"
            continue

        # Target Profit
        if ltp >= leg.tp_price:
            print(f"[Monitor] TP HIT {leg.security_id} ltp={ltp} tp={leg.tp_price}")
            await place_exit_order(leg.security_id, leg.quantity, session)
            leg.status = "TP_HIT"
            continue