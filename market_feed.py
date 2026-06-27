"""
Real-time WebSocket feed using DhanHQ Live Market Feed (WebSocket v2)
"""
import asyncio
import struct
import json
import websockets
from typing import Callable, List, Dict
from config import DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN


WS_URL = (
    f"wss://api-feed.dhan.co"
    f"?version=2&token={DHAN_ACCESS_TOKEN}"
    f"&clientId={DHAN_CLIENT_ID}&authType=2"
)

PACKET_SIZES = {2: 17, 4: 51, 8: 163, 5: 12, 6: 17, 50: 11}

MSG_TICKER = 2
MSG_QUOTE = 4
MSG_FULL = 8
MSG_OI = 5
MSG_PREVCLOSE = 6
MSG_DISCONNECT = 50


def parse_ticker(buf: bytes) -> dict:
    """Response code 2 — LTP + LTT (17 bytes total)"""
    sec_id = struct.unpack_from("<I", buf, 3)[0]
    ltp = struct.unpack_from("<f", buf, 8)[0]
    ltt = struct.unpack_from("<I", buf, 12)[0]
    return {"type": "ticker", "security_id": sec_id, "ltp": ltp, "ltt": ltt}


QUOTE_FMT = "<I f H I f I I I f f f f"


def parse_quote(buf: bytes) -> dict:
    """Response code 4 — Full quote without depth (51 bytes)"""
    vals = struct.unpack_from(QUOTE_FMT, buf, 3)
    return {
        "type": "quote",
        "security_id": vals[0],
        "ltp": vals[1], "ltq": vals[2], "ltt": vals[3],
        "atp": vals[4], "volume": vals[5], "sell_qty": vals[6],
        "buy_qty": vals[7], "open": vals[8], "close": vals[9],
        "high": vals[10], "low": vals[11],
    }


def dispatch_binary(buf: bytes, callback: Callable) -> None:
    """Parse concatenated binary packets from a single WS message."""
    offset = 0
    while offset < len(buf):
        if offset + 3 > len(buf):
            break
        msg_len = struct.unpack_from("<H", buf, offset + 1)[0]
        msg_code = buf[offset]
        size = PACKET_SIZES.get(msg_code, msg_len)
        if size == 0 or offset + size > len(buf):
            break
        packet = buf[offset: offset + size]
        if msg_code == MSG_TICKER:
            callback(parse_ticker(packet))
        elif msg_code == MSG_QUOTE:
            callback(parse_quote(packet))
        elif msg_code == MSG_DISCONNECT:
            err_code = struct.unpack_from("<H", buf, offset + 8)[0]
            raise ConnectionError(f"DhanHQ WS disconnect: {err_code}")
        offset += size


async def start_feed(
    instrument_list: List[Dict],
    on_tick: Callable,
    request_code: int = 17,
) -> None:
    """
    Subscribe instruments and stream ticks.
    Max 100 instruments per JSON message, 5000 per connection.
    request_code: 15=Ticker, 17=Quote, 21=Full
    """
    subscribe_msg = {
        "RequestCode": request_code,
        "InstrumentCount": len(instrument_list),
        "InstrumentList": instrument_list,
    }

    async for ws in websockets.connect(WS_URL, ping_interval=10):
        try:
            await ws.send(json.dumps(subscribe_msg))
            async for message in ws:
                if isinstance(message, bytes):
                    dispatch_binary(message, on_tick)
        except websockets.ConnectionClosedError as e:
            print(f"[Feed] Reconnecting after: {e}")
            await asyncio.sleep(2)
            continue
        except ConnectionError as e:
            print(f"[Feed] Hard disconnect: {e}")
            break