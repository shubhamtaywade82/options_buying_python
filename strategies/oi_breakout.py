"""
Strategy 1: OI Surge + Price Breakout
Data sources:
  - fetch_chain_snapshot() → OI per strike
  - fetch_intraday()       → 5-min OHLCV of underlying index
  - fetch_ltp()            → current spot
"""
import pandas as pd
from typing import Dict, Tuple
from dataclasses import dataclass
import aiohttp
from data_layer import fetch_intraday, fetch_chain_snapshot, fetch_ltp

NIFTY_IDX_ID = "13"
NIFTY_UNDER_INT = 13


@dataclass
class OIBreakoutSignal:
    direction: str
    key_strike: float
    oi_change_pct: float
    volume_ratio: float
    spot: float


def compute_oi_levels(chain_data: dict) -> Dict[float, Dict]:
    """Extract OI per strike from optionchain response."""
    levels = {}
    for strike_str, data in chain_data.get("data", {}).items():
        try:
            strike = float(strike_str)
            ce_oi = int(data.get("ce", {}).get("open_interest", 0))
            pe_oi = int(data.get("pe", {}).get("open_interest", 0))
            levels[strike] = {
                "ce_oi": ce_oi,
                "pe_oi": pe_oi,
                "total_oi": ce_oi + pe_oi,
            }
        except (ValueError, TypeError):
            continue
    return levels


def find_key_levels(oi_levels: Dict, spot: float, top_n: int = 3) -> Dict:
    """Find top-N strikes by total OI near spot (within ±5%)."""
    near = {
        s: v for s, v in oi_levels.items()
        if abs(s - spot) / spot <= 0.05
    }
    sorted_by_oi = sorted(near.items(), key=lambda x: x[1]["total_oi"], reverse=True)
    return dict(sorted_by_oi[:top_n])


def volume_ratio(df: pd.DataFrame, window: int = 20) -> float:
    """Current candle volume / rolling mean volume."""
    if len(df) < window + 1:
        return 1.0
    avg = df["volume"].iloc[-(window + 1):-1].mean()
    cur = df["volume"].iloc[-1]
    return cur / avg if avg > 0 else 1.0


def check_breakout(
    df: pd.DataFrame,
    key_strike: float,
    direction: str,
    threshold: float = 0.001,
) -> bool:
    """Candle must close beyond key_strike by threshold %."""
    if len(df) < 3:
        return False
    c1 = df["close"].iloc[-2]
    c2 = df["close"].iloc[-3]

    if direction == "up":
        return (c1 > key_strike * (1 + threshold) and
                c2 > key_strike * (1 + threshold * 0.5))
    else:
        return (c1 < key_strike * (1 - threshold) and
                c2 < key_strike * (1 - threshold * 0.5))


async def scan_oi_breakout(
    session: aiohttp.ClientSession,
    expiry: str,
    prev_oi_snap: Dict,
    vix: float,
) -> "Tuple[OIBreakoutSignal | None, Dict]":
    """Main scanner. Call every 3 minutes during market hours."""

    if not (11 <= vix <= 18):
        print(f"[OI-BO] VIX {vix} out of range [11-18]. Skip.")
        return None, prev_oi_snap

    df_5m = await fetch_intraday(
        NIFTY_IDX_ID, "IDX_I", "INDEX", interval=5, days_back=1, session=session
    )
    ltp_map = await fetch_ltp({"IDX_I": [13]}, session)
    spot = ltp_map.get("13", df_5m["close"].iloc[-1] if not df_5m.empty else 0)

    chain = await fetch_chain_snapshot(NIFTY_UNDER_INT, expiry, session)
    curr_oi = compute_oi_levels(chain)

    vol_r = volume_ratio(df_5m)
    if vol_r < 1.5:
        return None, curr_oi

    key_levels = find_key_levels(curr_oi, spot)

    for strike, oi_now in key_levels.items():
        prev = prev_oi_snap.get(strike, {})
        prev_total = prev.get("total_oi", oi_now["total_oi"])
        oi_change_pct = ((oi_now["total_oi"] - prev_total) / prev_total * 100
                         if prev_total > 0 else 0)

        if oi_change_pct <= -15 and check_breakout(df_5m, strike, "up"):
            return OIBreakoutSignal(
                direction="BUY_CE",
                key_strike=strike,
                oi_change_pct=oi_change_pct,
                volume_ratio=vol_r,
                spot=spot,
            ), curr_oi

        ce_change = ((oi_now["ce_oi"] - prev.get("ce_oi", oi_now["ce_oi"]))
                     / prev.get("ce_oi", 1) * 100) if prev.get("ce_oi") else 0
        if ce_change >= 20 and check_breakout(df_5m, strike, "down"):
            return OIBreakoutSignal(
                direction="BUY_PE",
                key_strike=strike,
                oi_change_pct=ce_change,
                volume_ratio=vol_r,
                spot=spot,
            ), curr_oi

    return None, curr_oi