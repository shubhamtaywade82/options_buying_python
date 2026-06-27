"""
Calls local Ollama model for directional bias + sentiment.
Returns: "BUY_CE" | "BUY_PE" | "NO_TRADE"
"""
import aiohttp
import json
from config import OLLAMA_URL, OLLAMA_MODEL


async def get_signal(
    underlying: str,
    spot_price: float,
    day_change_pct: float,
    vix: float,
    session: aiohttp.ClientSession,
) -> str:
    """
    Sends market context to Ollama; expects structured JSON back.
    IMPORTANT: This is directional classification, NOT financial advice.
    """
    prompt = f"""
You are a quantitative market microstructure classifier.
Classify the intraday directional bias based ONLY on the technical inputs.

Instrument: {underlying}
Spot: {spot_price}
Day Change: {day_change_pct:.2f}%
India VIX: {vix:.2f}

Rules:
- Output ONLY valid JSON: {{"signal": "BUY_CE"|"BUY_PE"|"NO_TRADE", "confidence": 0.0-1.0}}
- NO_TRADE if VIX > 20 or |day_change_pct| < 0.15
- BUY_CE if momentum is clearly upward
- BUY_PE if momentum is clearly downward
- Minimum confidence to trade: 0.65
"""
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
    }
    async with session.post(OLLAMA_URL, json=payload) as resp:
        raw = await resp.json()
        result = json.loads(raw.get("response", "{}"))

    signal = result.get("signal", "NO_TRADE")
    confidence = float(result.get("confidence", 0.0))

    if confidence < 0.65:
        return "NO_TRADE"
    return signal