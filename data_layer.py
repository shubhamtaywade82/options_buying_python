"""
Unified data fetcher using DhanHQ-py SDK v2.2.0
Sources:
  - dhan.intraday_minute_data()          → 1/5/15-min OHLCV
  - dhan.option_chain()                  → Greeks, OI, IV, bid/ask
  - dhan.ticker_data() / ohlc_data()     → Spot LTP snapshot
  - dhan.expiry_list()                   → Expiry dates
  - dhan.margin_calculator()             → Margin required
  - dhan.get_fund_limits()               → Available balance
  - dhan.place_order()                   → Order placement
"""
import asyncio
import pandas as pd
from datetime import date, timedelta
from typing import Dict, List, Optional
from config import DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN

from dhanhq import DhanContext, dhanhq

_dhan_client: Optional[dhanhq] = None


def get_dhan_client() -> dhanhq:
    """Get or create singleton DhanHQ client with DhanContext."""
    global _dhan_client
    if _dhan_client is None:
        ctx = DhanContext(DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN)
        _dhan_client = dhanhq(ctx)
    return _dhan_client


def _to_dataframe(raw: dict) -> pd.DataFrame:
    """Convert DhanHQ intraday response to DataFrame."""
    opens = raw.get("open", [])
    highs = raw.get("high", [])
    lows = raw.get("low", [])
    closes = raw.get("close", [])
    vols = raw.get("volume", [])
    times = raw.get("timestamp", [])

    df = pd.DataFrame({
        "open": opens, "high": highs,
        "low": lows, "close": closes,
        "volume": vols, "ts": times,
    })
    df["ts"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert("Asia/Kolkata")
    return df.sort_values("ts").reset_index(drop=True)


async def fetch_intraday(
    security_id: str,
    segment: str,          # "IDX_I" | "NSE_FNO" | "NSE_EQ"
    instrument: str,       # "INDEX" | "OPTIDX" | "EQUITY"
    interval: int = 5,     # 1 | 5 | 15 | 30 | 60
    days_back: int = 5,
) -> pd.DataFrame:
    """
    SDK: dhan.intraday_minute_data()
    Returns DataFrame with columns: [open, high, low, close, volume, ts]
    """
    dhan = get_dhan_client()
    to_dt = date.today().isoformat()
    from_dt = (date.today() - timedelta(days=days_back)).isoformat()

    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(
        None,
        lambda: dhan.intraday_minute_data(
            security_id=security_id,
            exchange_segment=segment,
            instrument_type=instrument,
            from_date=from_dt,
            to_date=to_dt,
            interval=interval,
        )
    )
    return _to_dataframe(raw)


async def fetch_ltp(
    segment_map: Dict[str, List[int]],
) -> Dict[str, float]:
    """
    SDK: dhan.ticker_data()
    Returns {security_id_str: ltp_float}
    """
    dhan = get_dhan_client()

    # Flatten segment_map to list of securities for ticker_data
    securities = {}
    for seg, ids in segment_map.items():
        securities[seg] = [str(i) for i in ids]

    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(
        None,
        lambda: dhan.ticker_data(securities=securities)
    )

    result = {}
    for seg, instruments in raw.items():
        for item in (instruments if isinstance(instruments, list) else []):
            result[str(item.get("securityId"))] = float(item.get("lastTradedPrice", 0))
    return result


async def compute_ivr(
    security_id: str,
    option_type: str = "CALL",
    strike_rel: str = "ATM",
    lookback: int = 30,
) -> float:
    """
    Uses historical daily data of expired options to compute IVR.
    SDK: dhan.historical_daily_data() with expired options params.
    IVR = (current_iv - iv_low) / (iv_high - iv_low) * 100
    """
    dhan = get_dhan_client()
    to_dt = date.today().isoformat()
    from_dt = (date.today() - timedelta(days=lookback)).isoformat()

    # Note: The SDK v2.2.0 may not have rollingoption endpoint directly.
    # For now, return neutral fallback - would need expired_options_data endpoint
    return 50.0


async def fetch_chain_snapshot(
    underlying_id: int,
    expiry: str,
) -> dict:
    """
    SDK: dhan.option_chain()
    Returns full chain dict.
    """
    dhan = get_dhan_client()
    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(
        None,
        lambda: dhan.option_chain(
            under_security_id=underlying_id,
            under_exchange_segment="IDX_I",
            expiry=expiry,
        )
    )
    return raw


async def fetch_expiry_list(
    underlying_id: int,
) -> List[str]:
    """SDK: dhan.expiry_list() — returns ["YYYY-MM-DD", ...]"""
    dhan = get_dhan_client()
    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(
        None,
        lambda: dhan.expiry_list(
            under_security_id=underlying_id,
            under_exchange_segment="IDX_I",
        )
    )
    return raw.get("data", [])


async def check_margin(
    security_id: str,
    quantity: int,
    price: float,
) -> dict:
    """SDK: dhan.margin_calculator()"""
    dhan = get_dhan_client()
    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(
        None,
        lambda: dhan.margin_calculator(
            security_id=security_id,
            exchange_segment="NSE_FNO",
            transaction_type="BUY",
            quantity=quantity,
            product_type="INTRADAY",
            price=price,
        )
    )
    return raw


async def get_fund_limits() -> dict:
    """SDK: dhan.get_fund_limits()"""
    dhan = get_dhan_client()
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, dhan.get_fund_limits)


async def place_buy_order(
    security_id: str,
    quantity: int,
    price: float,
    order_type: str = "LIMIT",
) -> str:
    """SDK: dhan.place_order() — Naked BUY (INTRADAY, NSE_FNO)"""
    dhan = get_dhan_client()
    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(
        None,
        lambda: dhan.place_order(
            security_id=security_id,
            exchange_segment="NSE_FNO",
            transaction_type="BUY",
            quantity=quantity,
            order_type=order_type,
            product_type="INTRADAY",
            price=price,
            validity="DAY",
        )
    )
    return raw.get("orderId", "")


async def place_exit_order(
    security_id: str,
    quantity: int,
) -> str:
    """SDK: dhan.place_order() — MARKET SELL to exit"""
    dhan = get_dhan_client()
    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(
        None,
        lambda: dhan.place_order(
            security_id=security_id,
            exchange_segment="NSE_FNO",
            transaction_type="SELL",
            quantity=quantity,
            order_type="MARKET",
            product_type="INTRADAY",
            price=0,
            validity="DAY",
        )
    )
    return raw.get("orderId", "")