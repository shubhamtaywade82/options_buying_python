"""
Strategy 4: Opening Range Breakout
Valid only in 9:30-11:30 window.
Data: fetch_intraday(interval=5)
"""
import pandas as pd
from dataclasses import dataclass
from datetime import datetime
import aiohttp
from data_layer import fetch_intraday

NIFTY_IDX_ID = "13"


@dataclass
class ORBSignal:
    direction: str
    orb_high: float
    orb_low: float
    breakout_price: float
    volume_ratio: float
    body_pct: float


def compute_orb(df: pd.DataFrame) -> tuple[float, float, float]:
    """Define ORB from first 3 five-min bars (9:15-9:30). Returns (orb_high, orb_low, orb_avg_volume)."""
    today = df["ts"].iloc[-1].date()
    today_df = df[df["ts"].dt.date == today].head(3)

    if len(today_df) < 3:
        return 0.0, 0.0, 0.0

    return (
        today_df["high"].max(),
        today_df["low"].min(),
        today_df["volume"].mean(),
    )


def candle_body_pct(row: pd.Series) -> float:
    """Body size as fraction of total candle range."""
    rng = row["high"] - row["low"]
    if rng == 0:
        return 0.0
    return abs(row["close"] - row["open"]) / rng


async def scan_orb(
    session: aiohttp.ClientSession,
    vix: float,
    already_traded_today: bool = False,
) -> "ORBSignal | None":
    """Call every 5 min on bar close between 9:30 and 11:30. One trade per day."""
    now = datetime.now()
    if already_traded_today:
        return None
    if not (9 * 60 + 30 <= now.hour * 60 + now.minute <= 11 * 60 + 30):
        return None
    if vix > 18:
        print(f"[ORB] VIX={vix} > 18. Skip.")
        return None

    df = await fetch_intraday(
        NIFTY_IDX_ID, "IDX_I", "INDEX", interval=5, days_back=1, session=session
    )
    today = df["ts"].iloc[-1].date()
    df_today = df[df["ts"].dt.date == today].copy().reset_index(drop=True)

    if len(df_today) < 5:
        return None

    orb_h, orb_l, orb_avg_vol = compute_orb(df_today)
    if orb_h == 0 or orb_l == 0:
        return None

    post_orb = df_today.iloc[3:]

    if len(post_orb) < 2:
        return None

    bar1 = post_orb.iloc[-2]
    bar2 = post_orb.iloc[-3] if len(post_orb) >= 3 else bar1

    vol_r = bar1["volume"] / orb_avg_vol if orb_avg_vol > 0 else 1.0
    body_pct = candle_body_pct(bar1)

    # Upside breakout
    if (bar1["close"] > orb_h * 1.002 and
            bar2["close"] > orb_h * 1.001 and
            vol_r >= 2.0 and
            body_pct >= 0.60):
        print(f"[ORB] BUY CE breakout: close={bar1['close']:.0f} "
              f"> ORB_H={orb_h:.0f} vol_r={vol_r:.1f}")
        return ORBSignal(
            direction="BUY_CE",
            orb_high=orb_h,
            orb_low=orb_l,
            breakout_price=bar1["close"],
            volume_ratio=vol_r,
            body_pct=body_pct,
        )

    # Downside breakout
    if (bar1["close"] < orb_l * 0.998 and
            bar2["close"] < orb_l * 0.999 and
            vol_r >= 2.0 and
            body_pct >= 0.60):
        print(f"[ORB] BUY PE breakout: close={bar1['close']:.0f} "
              f"< ORB_L={orb_l:.0f} vol_r={vol_r:.1f}")
        return ORBSignal(
            direction="BUY_PE",
            orb_high=orb_h,
            orb_low=orb_l,
            breakout_price=bar1["close"],
            volume_ratio=vol_r,
            body_pct=body_pct,
        )

    return None