"""
Priority order: ORB -> OI Breakout -> IV Rank -> EMA Pullback
Only one active trade per strategy slot at a time.
"""
import asyncio
import aiohttp
from datetime import datetime
from data_layer import fetch_ltp

from strategies.orb import scan_orb, ORBSignal
from strategies.oi_breakout import scan_oi_breakout, OIBreakoutSignal
from strategies.iv_rank_entry import scan_iv_rank_entry, IVRankSignal
from strategies.ema_pullback import scan_ema_pullback, EMAPullbackSignal

VIX_SECURITY_ID = "26000"


class StrategyRouter:
    def __init__(self):
        self.prev_oi_snap: dict = {}
        self.open_iv_snap: float = 0.0
        self.orb_traded_today: bool = False
        self.ema_reentry_count: int = 0
        self.last_day: int = -1

    def reset_daily_state(self):
        now = datetime.now()
        if now.day != self.last_day:
            self.orb_traded_today = False
            self.ema_reentry_count = 0
            self.last_day = now.day
            print("[Router] Daily state reset.")

    async def run_cycle(
        self,
        session: aiohttp.ClientSession,
        expiry: str,
    ) -> dict | None:
        """Returns {"signal": <SignalObject>, "strategy": str, "params": {...}} or None."""
        self.reset_daily_state()

        # Fetch VIX
        ltp_map = await fetch_ltp({"IDX_I": [VIX_SECURITY_ID]}, session)
        vix = ltp_map.get(VIX_SECURITY_ID, 14.0)

        spot_map = await fetch_ltp({"IDX_I": [13]}, session)
        spot = spot_map.get("13", 0.0)

        # 1. ORB (highest priority, 9:30-11:30 only)
        orb_sig = await scan_orb(session, vix, self.orb_traded_today)
        if orb_sig:
            self.orb_traded_today = True
            return {
                "signal": orb_sig,
                "strategy": "ORB",
                "params": {"sl_pct": 0.40, "tp_pct": 1.00, "time_limit_min": 60}
            }

        # 2. OI Breakout (all day, 3-min cycle)
        oi_sig, self.prev_oi_snap = await scan_oi_breakout(
            session, expiry, self.prev_oi_snap, vix
        )
        if oi_sig:
            return {
                "signal": oi_sig,
                "strategy": "OI_BREAKOUT",
                "params": {"sl_pct": 0.40, "tp_pct": 0.80, "time_limit_min": 90}
            }

        # 3. IV Rank (9:25-10:45 only)
        ivr_sig = await scan_iv_rank_entry(
            session, expiry, self.open_iv_snap, spot
        )
        if ivr_sig:
            return {
                "signal": ivr_sig,
                "strategy": "IV_RANK",
                "params": {"sl_pct": 0.45, "tp_pct": 0.70, "time_limit_min": 90}
            }

        # 4. EMA Pullback (10:30-14:00)
        ema_sig = await scan_ema_pullback(session, self.ema_reentry_count)
        if ema_sig:
            self.ema_reentry_count += 1
            return {
                "signal": ema_sig,
                "strategy": "EMA_PULLBACK",
                "params": {"sl_pct": 0.45, "tp_pct": 0.90, "time_limit_min": 60}
            }

        return None