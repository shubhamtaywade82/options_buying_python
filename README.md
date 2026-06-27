# Naked Options Buying Bot — DhanHQ v2.2.0

A fully automated intraday naked options buying bot for Nifty/BankNifty using DhanHQ API. Implements 4 distinct entry strategies with Greeks-based filtering, real-time WebSocket monitoring, and Ollama LLM for directional bias.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     STRATEGY PIPELINE                            │
├─────────────────────────────────────────────────────────────────┤
│  1. ORB (9:30–11:30)     → Opening Range Breakout               │
│  2. OI Breakout (all day) → OI Surge + Price Breakout           │
│  3. IV Rank (9:25–10:45)  → Mean Reversion after IV Spike       │
│  4. EMA Pullback (10:30–14:00) → Trend Pullback to EMA9         │
│       ↓                                                         │
│  Greeks/IV Gate  →  Margin Check  →  LIMIT Order  →  Monitor   │
│       ↓                                                         │
│  SL/TP/Time Exit (WebSocket ticks)                              │
└─────────────────────────────────────────────────────────────────┘
```

---

## Prerequisites

### System Requirements
- **Python 3.11+** (required for `dhanhq>=2.2.0` match statements)
- **Ollama** running locally with `llama3.2` model
- **DhanHQ Account** with:
  - Static IP whitelisted (mandatory for Order APIs)
  - Data API subscription active
  - F&O trading enabled

### Install Dependencies
```bash
# Python 3.11 (use uv, pyenv, or system package manager)
# Ubuntu/Debian:
sudo apt update && sudo apt install python3.11 python3.11-venv

# Create venv
python3.11 -m venv .venv
source .venv/bin/activate

# Install requirements
pip install -r requirements.txt

# Verify
python -c "import dhanhq; print(dhanhq.__version__)"  # Should show 2.2.0
```

### Ollama Setup
```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Start server
ollama serve &

# Pull model (in another terminal)
ollama pull llama3.2

# Verify
curl http://localhost:11434/api/tags
```

---

## Authentication

### Method 1: PIN + TOTP (Recommended) — Automatic or Manual

**Option A: Fully Automatic (store TOTP secret once)**
```bash
# 1. Get your TOTP secret from Dhan 2FA setup (base32 string, e.g., "JBSWY3DPEHPK3PXP")
# 2. Set environment variables:
export DHAN_CLIENT_ID="your_client_id"
export DHAN_PIN="123456"
export DHAN_TOTP_SECRET="YOUR_BASE32_TOTP_SECRET_HERE"

# 3. Run once - auto-generates TOTP and gets access token:
python auth_pin_totp.py
# Output: access_token = eyJhbGciOiJIUzI1NiIs...
# Copy and export:
export DHAN_ACCESS_TOKEN="your_token_here"
```

**Option B: Manual TOTP entry**
```bash
python auth_pin_totp.py
# Enter Client ID, PIN, and TOTP from authenticator app when prompted
```

### Required Environment Variables
```bash
# Required
export DHAN_CLIENT_ID="your_10_digit_client_id"
export DHAN_ACCESS_TOKEN="your_access_token_from_above"

# Optional (for automatic TOTP generation)
export DHAN_PIN="123456"              # 6-digit PIN
export DHAN_TOTP_SECRET="JBSWY3DPEHPK3PXP"  # base32 secret from Dhan 2FA setup
```

### Token Renewal (every 24 hours)
```bash
# Option 1: Re-run auth script (auto if DHAN_TOTP_SECRET set)
python auth_pin_totp.py

# Option 2: Direct renewal (if token not fully expired)
python -c "
from dhanhq import DhanLogin
import os
DhanLogin(os.environ['DHAN_CLIENT_ID']).renew_token(os.environ['DHAN_ACCESS_TOKEN'])
"
```

---

## Configuration

Edit `config.py` to adjust risk parameters:

```python
# Risk Management
MAX_CAPITAL_PER_TRADE_PCT = 0.02   # 2% equity per trade
STOP_LOSS_PCT             = 0.50   # 50% premium stop loss
TARGET_PCT                = 0.90   # 90% premium target
MAX_OPEN_LEGS             = 3      # Max concurrent positions

# Strike Selection Gates
MIN_OI                    = 500_000    # Minimum open interest
MIN_DELTA                 = 0.25       # Delta floor
MAX_DELTA                 = 0.45       # Delta ceiling
MIN_IVR                   = 40         # Minimum IV Rank
MAX_BID_ASK_SPREAD_PCT    = 0.005      # 0.5% max spread

# Lot Sizes (verify from Dhan instrument master)
NIFTY_LOT_SIZE       = 25
BANKNIFTY_LOT_SIZE   = 15

# Ollama
OLLAMA_MODEL = "llama3.2"
OLLAMA_URL   = "http://localhost:11434/api/generate"
```

---

## Running the Bot

### Quick Start
```bash
# 1. Activate venv
source .venv/bin/activate

# 2. Set credentials
export DHAN_CLIENT_ID="1234567890"
export DHAN_ACCESS_TOKEN="eyJhbGciOiJIUzI1NiIs..."

# 3. Ensure Ollama is running
ollama serve &

# 4. Run bot
python bot.py
```

### Expected Output
```
[Bot] Trading expiry: 2024-01-25
[Feed] Connected to DhanHQ WebSocket v2
[Bot] No trade signal. (waiting for strategy conditions)
[Bot] Signal: BUY_CE from OI_BREAKOUT
[Bot] Selected: CE 21500 delta=0.32 iv=14.5% OI=12,50,000 bid=148.2 ask=149.5
[Bot] Leg added: SL=74.7 TP=284.0 MaxLoss=₹1868
[Monitor] TP HIT 12345678 ltp=295.0 tp=284.0
[Bot] Leg added: SL=74.7 TP=284.0 MaxLoss=₹1868
```

### Dry Run / Paper Trading
The bot places real orders. For testing:
1. Use a test account with minimal capital
2. Or comment out `place_buy_order` in `bot.py` and add logging
3. Monitor logs for signal generation without execution

---

## Strategy Details

### 1. Opening Range Breakout (ORB)
- **Window:** 9:30–11:30 IST (one trade/day)
- **Logic:** First 15-min range break with 2× volume, 60%+ candle body
- **SL:** 40% | **TP:** 100% | **Time Stop:** 11:30 AM

### 2. OI Surge + Price Breakout
- **Window:** All day (3-min cycle)
- **Logic:** OI drop ≥15% at key strike + spot breakout + 1.5× volume
- **SL:** 40% | **TP:** 80% | **Time Stop:** 90 min

### 3. IV Rank Mean Reversion
- **Window:** 9:25–10:45 only
- **Logic:** IVR 40–80 + gap >0.3% + first 15-min confirmation + IV falling
- **SL:** 45% | **TP:** 70% | **Time Stop:** 11:00 AM

### 4. EMA Pullback
- **Window:** 10:30–14:00
- **Logic:** EMA9 > EMA21 (bullish) or vice versa, pullback to EMA9, RSI 40–52, low volume
- **SL:** 45% | **TP:** 90% | **Time Stop:** 60 min
- **Max Re-entries:** 2/day per direction

---

## Risk Management

| Rule | Value | Description |
|------|-------|-------------|
| Max Capital/Trade | 2% | Of available margin |
| Max Open Legs | 3 | Concurrent positions |
| Stop Loss | 50% | Of premium paid |
| Target | 90% | Of premium paid |
| Theta Stop | 14:00 | Exit all on expiry day |
| IVR Gate | >40 | Minimum IV Rank for directional |
| Delta Range | 0.25–0.45 | Strike selection window |
| Min OI | 5L | Liquidity filter |
| Max Spread | 0.5% | Bid-ask spread limit |

---

## Project Structure

```
options_buying_python/
├── auth_pin_totp.py       # PIN/TOTP authentication
├── bot.py                 # Main orchestrator (60s heartbeat)
├── config.py              # Risk parameters & constants
├── data_layer.py          # DhanHQ SDK wrapper (REST calls)
├── greeks_filter.py       # Strike selection gates
├── market_feed.py         # WebSocket v2 async wrapper
├── order_manager.py       # Position lifecycle & SL/TP
├── signal_engine.py       # Ollama LLM directional bias
├── requirements.txt       # Python dependencies
├── strategies/
│   ├── __init__.py
│   ├── oi_breakout.py     # Strategy 1: OI + Breakout
│   ├── iv_rank_entry.py   # Strategy 2: IV Rank Reversion
│   ├── ema_pullback.py    # Strategy 3: EMA Pullback
│   ├── orb.py             # Strategy 4: Opening Range Breakout
│   └── router.py          # Priority router
└── README.md
```

---

## Troubleshooting

### Common Issues

**`ModuleNotFoundError: dhanhq`**
```bash
pip install -r requirements.txt
# Ensure Python 3.11+
```

**`WebSocket connection failed`**
- Verify static IP is whitelisted in Dhan dashboard
- Check `DHAN_ACCESS_TOKEN` is valid (not expired)
- Token expires in 24h — renew if needed

**`No trade signal` (continuous)**
- Normal during low volatility / sideways markets
- Check Ollama is running: `curl localhost:11434/api/tags`
- Verify IVR > 40, VIX 11–18, volume conditions

**`Insufficient margin`**
- Reduce `MAX_CAPITAL_PER_TRADE_PCT`
- Check available balance via Dhan app

**`Option chain rate limit`**
- Built-in: max 1 req/3 sec per underlying/expiry
- Bot respects this via 60s cycle

### Logs to Watch
```
[Bot] Trading expiry: YYYY-MM-DD          # Expiry selection
[Feed] Reconnecting after: ...            # WebSocket reconnect
[Gate] IVR XX below minimum 40            # IV filter
[Monitor] SL HIT / TP HIT / TIME_EXIT     # Exit triggers
[Bot] Leg added: SL=XX TP=XX MaxLoss=₹XX # New position
```

---

## Development

### Run Syntax Checks
```bash
python -m py_compile *.py strategies/*.py
```

### Add New Strategy
1. Create `strategies/my_strategy.py` with `scan_my_strategy()` returning signal dataclass
2. Add to `strategies/__init__.py`
3. Register in `strategies/router.py` with priority

### Testing Without Live API
```python
# In bot.py, replace:
# order_id = await place_buy_order(...)
# With:
order_id = f"PAPER_{int(time.time())}"
print(f"[PAPER] Would buy {security_id} @ {price}")
```

---

## Disclaimer

**This is algorithmic trading software. Use at your own risk.**

- Past performance ≠ future results
- Naked options buying has unlimited risk (theoretical)
- Test thoroughly with paper trading before live capital
- Ensure compliance with SEBI/regulatory requirements
- No financial advice — this is a technical implementation

---

## License

MIT License — See LICENSE file