"""
Filters option chain strikes against Greeks/IV/OI/spread thresholds.
Option chain from POST /v2/optionchain already includes these fields.
"""
from typing import List
from dataclasses import dataclass
from config import MIN_DELTA, MAX_DELTA, MIN_OI, MIN_IVR, MAX_BID_ASK_SPREAD_PCT


@dataclass
class StrikeCandidate:
    security_id: str
    strike: float
    option_type: str      # "CE" | "PE"
    ltp: float
    delta: float
    gamma: float
    theta: float
    vega: float
    iv: float
    oi: int
    bid: float
    ask: float

    @property
    def spread_pct(self) -> float:
        mid = (self.bid + self.ask) / 2
        return (self.ask - self.bid) / mid if mid > 0 else 999.0

    @property
    def spread_ok(self) -> bool:
        return self.spread_pct <= MAX_BID_ASK_SPREAD_PCT


def parse_chain_to_candidates(
    chain_data: dict,
    option_type: str,          # "CE" or "PE"
) -> List["StrikeCandidate"]:
    """Parse raw optionchain API response into StrikeCandidate list."""
    candidates = []
    strikes = chain_data.get("data", {})
    for strike_price, data in strikes.items():
        leg = data.get(option_type.lower(), {})
        if not leg:
            continue
        candidates.append(StrikeCandidate(
            security_id=str(leg.get("security_id", "")),
            strike=float(strike_price),
            option_type=option_type,
            ltp=float(leg.get("last_price", 0)),
            delta=float(leg.get("delta", 0)),
            gamma=float(leg.get("gamma", 0)),
            theta=float(leg.get("theta", 0)),
            vega=float(leg.get("vega", 0)),
            iv=float(leg.get("implied_volatility", 0)),
            oi=int(leg.get("open_interest", 0)),
            bid=float(leg.get("best_bid_price", 0)),
            ask=float(leg.get("best_ask_price", 0)),
        ))
    return candidates


def filter_strikes(
    candidates: List["StrikeCandidate"],
    ivr: float,
    direction: str,    # "BUY_CE" | "BUY_PE"
) -> List["StrikeCandidate"]:
    """Apply all pre-trade gates. Returns filtered, sorted list."""

    if ivr < MIN_IVR:
        print(f"[Gate] IVR {ivr:.1f} below minimum {MIN_IVR}. No trade.")
        return []

    filtered = [
        c for c in candidates
        if (
            MIN_DELTA <= abs(c.delta) <= MAX_DELTA
            and c.oi >= MIN_OI
            and c.ltp > 0
            and c.spread_ok
            and (c.option_type == "CE" if direction == "BUY_CE" else c.option_type == "PE")
        )
    ]

    # Sort by delta closest to 0.35 (sweet spot for directional naked buys)
    filtered.sort(key=lambda x: abs(abs(x.delta) - 0.35))
    return filtered