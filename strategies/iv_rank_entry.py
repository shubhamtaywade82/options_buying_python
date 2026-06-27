"""
Strategy 2: IV Rank Mean Reversion
Uses: compute_ivr(), fetch_intraday(), fetch_chain_snapshot()
"""
import pandas as pd
from typing import Tuple
from dataclasses import dataclass
import aiohttp
from data_layer import compute_ivr, fetch_intraday, fetch_chain_snapshot

NIFTY_IDX_ID = "13"
NIFTY_UNDER_INT = 13


@dataclass
class IVRankSignal:
    direction: str
    ivr: float
    atm_iv: float
    gap_pct: float
    best_strike: float
    best_vega: float


def compute_gap(df_5m: pd.DataFrame) -> float:
    """Gap = (today's first candle open - yesterday's last close) / yesterday's last close * 100"""
    if len(df_5m) < 2:
        return 0.0
    today = df_5m["ts"].iloc[-1].date()
    today_bars = df_5m[df_5m["ts"].dt.date == today]
    prev_bars = df_5m[df_5m["ts"].dt.date < today]

    if today_bars.empty or prev_bars.empty:
        return 0.0

    today_open = today_bars["open"].iloc[0]
    prev_close = prev_bars["close"].iloc[-1]
    return (today_open - prev_close) / prev_close * 100


def get_atm_iv(chain_data: dict, spot: float) -> tuple[float, float]:
    """Returns (atm_iv, atm_vega) for strike closest to spot."""
    best_strike = None
    best_iv = 0.0
    best_vega = 0.0
    min_dist = float("inf")

    for strike_str, data in chain_data.get("data", {}).items():
        try:
            strike = float(strike_str)
            dist = abs(strike - spot)
            if dist < min_dist:
                iv = float(data.get("ce", {}).get("implied_volatility", 0))
                vega = float(data.get("ce", {}).get("vega", 0))
                if iv > 0:
                    min_dist = dist
                    best_strike = strike
                    best_iv = iv
                    best_vega = vega
        except (ValueError, TypeError):
            continue

    return best_iv, best_vega


async def scan_iv_rank_entry(
    session: aiohttp.ClientSession,
    expiry: str,
    open_iv_snap: float,
    spot: float,
) -> "IVRankSignal | None":
    """Only valid for first 90 minutes (9:15-10:45). Call at 9:30, 10:00, 10:30."""
    from datetime import datetime
    now = datetime.now()
    if not (9 * 60 + 25 <= now.hour * 60 + now.minute <= 10 * 60 + 45):
        return None

    # IVR gate
    ivr = await compute_ivr(
        NIFTY_IDX_ID, option_type="CALL", strike_rel="ATM",
        lookback=30, session=session
    )
    if not (40 <= ivr <= 80):
        print(f"[IVR] IVR={ivr} outside 40-80. Skip.")
        return None

    # Gap direction
    df_5m = await fetch_intraday(
        NIFTY_IDX_ID, "IDX_I", "INDEX", interval=5, days_back=2, session=session
    )
    gap_pct = compute_gap(df_5m)
    if abs(gap_pct) < 0.3:
        print(f"[IVR] Gap {gap_pct:.2f}% insufficient. Skip.")
        return None

    direction = "BUY_CE" if gap_pct > 0 else "BUY_PE"

    # First 15-min candle confirmation
    today = df_5m["ts"].iloc[-1].date()
    today_bars = df_5m[df_5m["ts"].dt.date == today].head(3)
    if len(today_bars) >= 3:
        candle_dir = today_bars["close"].iloc[-1] - today_bars["open"].iloc[0]
        if (gap_pct > 0 and candle_dir < 0) or (gap_pct < 0 and candle_dir > 0):
            print("[IVR] Candle direction conflicts with gap. Skip.")
            return None

    # IV falling check
    chain = await fetch_chain_snapshot(NIFTY_UNDER_INT, expiry, session)
    atm_iv, atm_vega = get_atm_iv(chain, spot)

    if atm_iv >= open_iv_snap:
        print(f"[IVR] IV not falling: current={atm_iv:.1f} vs open={open_iv_snap:.1f}. Skip.")
        return None

    return IVRankSignal(
        direction=direction,
        ivr=ivr,
        atm_iv=atm_iv,
        gap_pct=gap_pct,
        best_strike=round(spot / 50) * 50,
        best_vega=atm_vega,
    )