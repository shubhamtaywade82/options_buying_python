import asyncio
import aiohttp
import pandas as pd
from datetime import date, timedelta
from config import DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN

BASE   = "https://api.dhan.co/v2"
HDR    = {"access-token": DHAN_ACCESS_TOKEN,
          "client-id":    DHAN_CLIENT_ID,
          "Content-Type": "application/json"}


async def fetch_intraday(
    security_id: str,
    segment:     str,
    instrument:  str,
    interval:    int   = 5,
    days_back:   int   = 5,
    session:     aiohttp.ClientSession = None,
) -> pd.DataFrame:
    """
    POST /v2/charts/intraday
    Returns DataFrame with columns: [open, high, low, close, volume, ts]
    """
    to_dt   = date.today().isoformat()
    from_dt = (date.today() - timedelta(days=days_back)).isoformat()
    payload = {
        "securityId":      security_id,
        "exchangeSegment": segment,
        "instrument":      instrument,
        "interval":        str(interval),
        "fromDate":        from_dt,
        "toDate":          to_dt,
    }
    async with session.post(f"{BASE}/charts/intraday",
                            json=payload, headers=HDR) as r:
        r.raise_for_status()
        raw = await r.json()

    opens  = raw.get("open",      [])
    highs  = raw.get("high",      [])
    lows   = raw.get("low",       [])
    closes = raw.get("close",     [])
    vols   = raw.get("volume",    [])
    times  = raw.get("timestamp", [])

    df = pd.DataFrame({
        "open":   opens,  "high": highs,
        "low":    lows,   "close": closes,
        "volume": vols,   "ts": times,
    })
    df["ts"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert("Asia/Kolkata")
    return df.sort_values("ts").reset_index(drop=True)


async def fetch_ltp(
    segment_map: dict,
    session:     aiohttp.ClientSession,
) -> dict[str, float]:
    """
    POST /v2/marketfeed/ltp  — rate limit 1 req/sec, max 1000 instruments
    Returns {security_id_str: ltp_float}
    """
    async with session.post(f"{BASE}/marketfeed/ltp",
                            json=segment_map, headers=HDR) as r:
        r.raise_for_status()
        raw = await r.json()
    result = {}
    for seg, instruments in raw.items():
        for item in (instruments if isinstance(instruments, list) else []):
            result[str(item.get("securityId"))] = float(item.get("lastTradedPrice", 0))
    return result


async def compute_ivr(
    security_id:  str,
    option_type:  str = "CALL",
    strike_rel:   str = "ATM",
    lookback:     int = 30,
    session:      aiohttp.ClientSession = None,
) -> float:
    """
    Uses POST /v2/charts/rollingoption to compute IVR.
    IVR = (current_iv - iv_low) / (iv_high - iv_low) * 100
    """
    to_dt   = date.today().isoformat()
    from_dt = (date.today() - timedelta(days=lookback)).isoformat()
    payload = {
        "exchangeSegment": "NSE_FNO",
        "interval":        "5",
        "securityId":      security_id,
        "instrument":      "OPTIDX",
        "expiryFlag":      "WEEK",
        "expiryCode":      1,
        "strike":          strike_rel,
        "drvOptionType":   option_type,
        "requiredData":    ["iv", "close", "spot"],
        "fromDate":        from_dt,
        "toDate":          to_dt,
    }
    async with session.post(f"{BASE}/charts/rollingoption",
                            json=payload, headers=HDR) as r:
        r.raise_for_status()
        raw = await r.json()

    key  = "ce" if option_type == "CALL" else "pe"
    ivs  = raw.get("data", {}).get(key, {}).get("iv", [])
    ivs  = [v for v in ivs if v and v > 0]
    if len(ivs) < 5:
        return 50.0

    iv_now  = ivs[-1]
    iv_high = max(ivs)
    iv_low  = min(ivs)
    if iv_high == iv_low:
        return 50.0
    return round((iv_now - iv_low) / (iv_high - iv_low) * 100, 1)


async def fetch_chain_snapshot(
    underlying_id: int,
    expiry:        str,
    session:       aiohttp.ClientSession,
) -> dict:
    """
    POST /v2/optionchain  — 1 req per 3 sec per underlying/expiry
    """
    payload = {
        "UnderlyingScrip": underlying_id,
        "UnderlyingSeg":   "IDX_I",
        "Expiry":          expiry,
    }
    async with session.post(f"{BASE}/optionchain",
                            json=payload, headers=HDR) as r:
        r.raise_for_status()
        return await r.json()


async def fetch_expiry_list(
    underlying_id: int,
    session:       aiohttp.ClientSession,
) -> list[str]:
    """POST /v2/optionchain/expirylist"""
    payload = {
        "UnderlyingScrip": underlying_id,
        "UnderlyingSeg":   "IDX_I",
    }
    async with session.post(f"{BASE}/optionchain/expirylist",
                            json=payload, headers=HDR) as r:
        r.raise_for_status()
        data = await r.json()
        return data.get("data", [])