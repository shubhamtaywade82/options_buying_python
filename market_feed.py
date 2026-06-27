"""
Real-time WebSocket feed using DhanHQ-py SDK MarketFeed v2.2.0
"""
import asyncio
from typing import Callable, List, Dict, Any
from config import DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN

from dhanhq import DhanContext, MarketFeed


class MarketFeedWrapper:
    """Async wrapper around DhanHQ MarketFeed for non-blocking operation."""

    def __init__(
        self,
        instrument_list: List[Dict],
        on_tick: Callable[[Dict], None],
        request_code: int = 17,  # 15=Ticker, 17=Quote, 21=Full
    ):
        self.instrument_list = instrument_list
        self.on_tick = on_tick
        self.request_code = request_code
        self._feed: MarketFeed = None
        self._running = False
        self._context = DhanContext(DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN)

    def _convert_instruments(self) -> List[tuple]:
        """Convert our instrument dict format to MarketFeed tuple format."""
        segment_map = {
            "NSE": MarketFeed.NSE,
            "NSE_FNO": MarketFeed.NSE_FNO,
            "BSE": MarketFeed.BSE,
            "BSE_FNO": MarketFeed.BSE_FNO,
            "IDX_I": MarketFeed.IDX,
        }
        type_map = {
            15: MarketFeed.Ticker,
            17: MarketFeed.Quote,
            21: MarketFeed.Full,
        }
        sub_type = type_map.get(self.request_code, MarketFeed.Quote)

        instruments = []
        for inst in self.instrument_list:
            seg = segment_map.get(inst.get("ExchangeSegment", "NSE_FNO"), MarketFeed.NSE_FNO)
            sec_id = str(inst.get("SecurityId", ""))
            instruments.append((seg, sec_id, sub_type))
        return instruments

    def _on_message(self, data: Dict):
        """Callback for incoming market data."""
        if data:
            self.on_tick(data)

    async def start(self):
        """Start the feed in a background thread."""
        self._running = True
        instruments = self._convert_instruments()

        def run_feed():
            self._feed = MarketFeed(
                dhan_context=self._context,
                instruments=instruments,
                version="v2",
                on_message=self._on_message,
            )
            self._feed.run_forever()

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, run_feed)

    async def stop(self):
        """Stop the feed."""
        self._running = False
        if self._feed:
            self._feed.close_connection()

    def subscribe(self, instruments: List[Dict]):
        """Subscribe to additional instruments."""
        if self._feed:
            converted = []
            for inst in instruments:
                seg_map = {
                    "NSE": MarketFeed.NSE,
                    "NSE_FNO": MarketFeed.NSE_FNO,
                    "IDX_I": MarketFeed.IDX,
                }
                seg = seg_map.get(inst.get("ExchangeSegment", "NSE_FNO"), MarketFeed.NSE_FNO)
                converted.append((seg, str(inst.get("SecurityId", "")), MarketFeed.Quote))
            self._feed.subscribe_symbols(converted)

    def unsubscribe(self, instruments: List[Dict]):
        """Unsubscribe from instruments."""
        if self._feed:
            converted = []
            for inst in instruments:
                seg_map = {
                    "NSE": MarketFeed.NSE,
                    "NSE_FNO": MarketFeed.NSE_FNO,
                    "IDX_I": MarketFeed.IDX,
                }
                seg = seg_map.get(inst.get("ExchangeSegment", "NSE_FNO"), MarketFeed.NSE_FNO)
                converted.append((seg, str(inst.get("SecurityId", "")), 16))  # unsubscribe code
            self._feed.unsubscribe_symbols(converted)


async def start_feed(
    instrument_list: List[Dict],
    on_tick: Callable,
    request_code: int = 17,
) -> None:
    """
    Start the market feed with auto-reconnect.
    """
    wrapper = MarketFeedWrapper(instrument_list, on_tick, request_code)

    while True:
        try:
            await wrapper.start()
        except Exception as e:
            print(f"[Feed] Error: {e}. Reconnecting in 2s...")
            await asyncio.sleep(2)
            continue