"""
Strategy 3: Intraday EMA Pullback
Computes EMA9, EMA21, RSI14 on 5-min Nifty index candles.
Data: fetch_intraday(interval=5)
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass
import aiohttp
from data_layer import fetch_intraday, fetch_ltp

NIFTY_IDX_ID = "13"


@dataclass
class EMAPullbackSignal:
    direction: str
    spot: float
    ema9: float
    ema21: float
    rsi14: float
    slope_pct: float
    volume_ratio: float


# Indicator calculations
def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_g = gain.ewm(com=period - 1, adjust=False).mean()
    avg_l = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_g / avg_l.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def ema_slope_pct(ema_series: pd.Series, lookback: int = 3) -> float:
    """% slope of EMA over last N bars."""
    if len(ema_series) < lookback + 1:
        return 0.0
    start = ema_series.iloc[-(lookback + 1)]
    end = ema_series.iloc[-1]
    return (end - start) / start * 100 if start > 0 else 0.0


def is_pullback_to_ema(
    df: pd.DataFrame,
    ema_col: str,
    direction: str,
    tolerance: float = 0.001,
) -> bool:
    """Last closed candle touched EMA within tolerance AND previous candle was above/below EMA."""
    if len(df) < 3:
        return False
    curr_close = df["close"].iloc[-2]
    curr_ema = df[ema_col].iloc[-2]
    prev_close = df["close"].iloc[-3]
    prev_ema = df[ema_col].iloc[-3]

    touch = abs(curr_close - curr_ema) / curr_ema <= tolerance

    if direction == "up":
        return touch and prev_close > prev_ema and curr_close >= curr_ema * 0.999
    else:
        return touch and prev_close < prev_ema and curr_close <= curr_ema * 1.001


def higher_low_check(df: pd.DataFrame, direction: str) -> bool:
    """Last 3 lows are ascending (bullish) or last 3 highs are descending."""
    if len(df) < 4:
        return False
    if direction == "up":
        lows = df["low"].iloc[-4:-1].values
        return lows[-1] > lows[-2] > lows[0]
    else:
        highs = df["high"].iloc[-4:-1].values
        return highs[-1] < highs[-2] < highs[0]


async def scan_ema_pullback(
    session: aiohttp.ClientSession,
    re_entry_count: int = 0,
) -> "EMAPullbackSignal | None":
    """Call every 5 min on new bar close. Valid between 10:30 AM and 2:00 PM IST."""
    from datetime import datetime
    now = datetime.now()
    if not (10 * 60 + 30 <= now.hour * 60 + now.minute <= 14 * 60):
        return None
    if re_entry_count >= 2:
        print("[EMA-PB] Max re-entries (2) reached. Skip.")
        return None

    df = await fetch_intraday(
        NIFTY_IDX_ID, "IDX_I", "INDEX", interval=5, days_back=2, session=session
    )
    today = df["ts"].iloc[-1].date()
    df = df[df["ts"].dt.date == today].copy().reset_index(drop=True)

    if len(df) < 25:
        return None

    df["ema9"] = ema(df["close"], 9)
    df["ema21"] = ema(df["close"], 21)
    df["rsi"] = rsi(df["close"], 14)
    df["vol_avg"] = df["volume"].rolling(20).mean()

    e9 = df["ema9"].iloc[-1]
    e21 = df["ema21"].iloc[-1]
    rsi14 = df["rsi"].iloc[-2]
    slope = ema_slope_pct(df["ema21"], lookback=4)
    vol_r = (df["volume"].iloc[-2] / df["vol_avg"].iloc[-2]
             if df["vol_avg"].iloc[-2] > 0 else 1.0)

    bullish_trend = (e9 > e21) and (slope > 0.03)
    bearish_trend = (e9 < e21) and (slope < -0.03)

    if not (bullish_trend or bearish_trend):
        return None

    direction = "up" if bullish_trend else "down"

    rsi_ok = (40 <= rsi14 <= 52) if direction == "up" else (48 <= rsi14 <= 60)
    vol_ok = vol_r < 0.85
    touch_ok = is_pullback_to_ema(df, "ema9", direction)
    hl_ok = higher_low_check(df, direction)

    if not (rsi_ok and vol_ok and touch_ok and hl_ok):
        return None

    spot = df["close"].iloc[-1]
    print(f"[EMA-PB] Signal: {'BUY_CE' if direction=='up' else 'BUY_PE'} "
          f"spot={spot:.0f} EMA9={e9:.0f} RSI={rsi14:.1f} slope={slope:.3f}%")

    return EMAPullbackSignal(
        direction="BUY_CE" if direction == "up" else "BUY_PE",
        spot=spot,
        ema9=e9,
        ema21=e21,
        rsi14=rsi14,
        slope_pct=slope,
        volume_ratio=vol_r,
    )