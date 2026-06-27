"""
Main event loop. Wires feed, signal, filter, and order manager.
"""
import asyncio
import aiohttp
from datetime import datetime, date

from config import MAX_OPEN_LEGS, NIFTY_UNDERLYING_ID, MAX_CAPITAL_PER_TRADE_PCT
from data_layer import fetch_chain_snapshot as fetch_option_chain, fetch_expiry_list
from market_feed import start_feed
from greeks_filter import parse_chain_to_candidates, filter_strikes
from signal_engine import get_signal
from order_manager import (
    OptionLeg, check_margin, get_fund_limits,
    place_buy_order, monitor_positions,
)

# Shared state
live_ticks: "dict[str, float]" = {}
open_legs: "list[OptionLeg]" = []
NIFTY_LOT_SIZE = 25    # update from instrument master CSV if changed


# Tick callback (called by WS binary parser)
def on_tick(packet: dict) -> None:
    sec_id = str(packet.get("security_id"))
    ltp = packet.get("ltp")
    if sec_id and ltp:
        live_ticks[sec_id] = ltp


# Market hours guard
def is_market_open() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:        # Saturday/Sunday
        return False
    market_open = now.replace(hour=9, minute=15, second=0)
    market_close = now.replace(hour=15, minute=20, second=0)
    return market_open <= now <= market_close


# Capital sizing
async def compute_lots(
    ltp: float, lot_size: int, session: aiohttp.ClientSession
) -> int:
    funds = await get_fund_limits(session)
    equity = float(funds.get("availabelBalance", 0))
    capital_per_trade = equity * MAX_CAPITAL_PER_TRADE_PCT
    lots = max(1, int(capital_per_trade / (ltp * lot_size)))
    return lots


# Main strategy loop
async def strategy_loop() -> None:
    async with aiohttp.ClientSession() as session:

        # 1. Fetch nearest weekly expiry
        expiries = await fetch_expiry_list(NIFTY_UNDERLYING_ID, session)
        if not expiries:
            print("[Bot] No expiries found. Exiting.")
            return
        nearest_expiry = expiries[0]
        print(f"[Bot] Trading expiry: {nearest_expiry}")

        # 2. Start WebSocket feed (subscriptions updated dynamically)
        feed_task = asyncio.create_task(
            start_feed(instrument_list=[], on_tick=on_tick, request_code=17)
        )

        # 3. Strategy heartbeat — runs every 60 seconds
        while is_market_open():

            # Monitor existing positions first
            if open_legs:
                await monitor_positions(open_legs, live_ticks, session)
                active = [l for l in open_legs if l.status == "OPEN"]
                open_legs[:] = active

            # Skip new entries if max legs reached
            if len(open_legs) >= MAX_OPEN_LEGS:
                await asyncio.sleep(60)
                continue

            # 4. Fetch spot (use index LTP from live_ticks or REST)
            spot_ltp = live_ticks.get(str(NIFTY_UNDERLYING_ID), 0.0)
            if spot_ltp == 0:
                await asyncio.sleep(10)
                continue

            # 5. Get Ollama signal
            signal = await get_signal(
                underlying="NIFTY",
                spot_price=spot_ltp,
                day_change_pct=0.0,   # calculate from prev close
                vix=14.5,             # fetch from VIX security ID
                session=session,
            )
            if signal == "NO_TRADE":
                print("[Bot] No trade signal.")
                await asyncio.sleep(60)
                continue

            # 6. Fetch option chain + filter strikes
            chain_data = await fetch_option_chain(
                NIFTY_UNDERLYING_ID, nearest_expiry, session
            )
            candidates = parse_chain_to_candidates(chain_data, signal[-2:])  # "CE"|"PE"
            best = filter_strikes(candidates, ivr=55.0, direction=signal)

            if not best:
                print(f"[Bot] No qualifying strikes for {signal}")
                await asyncio.sleep(60)
                continue

            strike = best[0]
            print(f"[Bot] Selected: {strike.option_type} {strike.strike} "
                  f"delta={strike.delta:.2f} iv={strike.iv:.1f}% "
                  f"OI={strike.oi:,} bid={strike.bid} ask={strike.ask}")

            # 7. Capital + margin check
            lots = await compute_lots(strike.ltp, NIFTY_LOT_SIZE, session)
            qty = lots * NIFTY_LOT_SIZE

            margin_data = await check_margin(
                strike.security_id, qty, strike.ask, session
            )
            total_margin = float(margin_data.get("totalMargin", 0))
            avail_bal = float(margin_data.get("availableBalance", 0))

            if total_margin > avail_bal:
                print(f"[Bot] Insufficient margin: need {total_margin}, have {avail_bal}")
                await asyncio.sleep(60)
                continue

            # 8. Place order (LIMIT at ask price for controlled fill)
            order_id = await place_buy_order(
                strike.security_id, qty, strike.ask, session, order_type="LIMIT"
            )

            # 9. Track leg
            leg = OptionLeg(
                security_id=strike.security_id,
                option_type=strike.option_type,
                strike=strike.strike,
                entry_price=strike.ask,
                lots=lots,
                lot_size=NIFTY_LOT_SIZE,
                order_id=order_id,
            )
            open_legs.append(leg)
            print(f"[Bot] Leg added: SL={leg.sl_price} TP={leg.tp_price} "
                  f"MaxLoss=₹{leg.max_loss:.0f}")

            await asyncio.sleep(60)

        # Market closed — exit all
        print("[Bot] Market closed. Exiting all legs.")
        async with aiohttp.ClientSession() as s:
            for leg in open_legs:
                if leg.status == "OPEN":
                    from order_manager import place_exit_order
                    await place_exit_order(leg.security_id, leg.quantity, s)

        feed_task.cancel()


if __name__ == "__main__":
    asyncio.run(strategy_loop())