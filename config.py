import os
from dotenv import load_dotenv

# Load .env file (if exists) - searches parent directories
load_dotenv()

# DhanHQ Credentials (REQUIRED - must be set in .env or environment)
DHAN_CLIENT_ID = os.environ.get("DHAN_CLIENT_ID", "")
DHAN_ACCESS_TOKEN = os.environ.get("DHAN_ACCESS_TOKEN", "")

# PIN + TOTP for automatic token generation (OPTIONAL)
DHAN_PIN = os.environ.get("DHAN_PIN", "")
DHAN_TOTP_SECRET = os.environ.get("DHAN_TOTP_SECRET", "")

# Risk Parameters
MAX_CAPITAL_PER_TRADE_PCT = float(os.environ.get("MAX_CAPITAL_PER_TRADE_PCT", "0.02"))
STOP_LOSS_PCT = float(os.environ.get("STOP_LOSS_PCT", "0.50"))
TARGET_PCT = float(os.environ.get("TARGET_PCT", "0.90"))
MAX_OPEN_LEGS = int(os.environ.get("MAX_OPEN_LEGS", "3"))
MIN_OI = int(os.environ.get("MIN_OI", "500000"))
MIN_DELTA = float(os.environ.get("MIN_DELTA", "0.25"))
MAX_DELTA = float(os.environ.get("MAX_DELTA", "0.45"))
MIN_IVR = int(os.environ.get("MIN_IVR", "40"))
MAX_BID_ASK_SPREAD_PCT = float(os.environ.get("MAX_BID_ASK_SPREAD_PCT", "0.005"))

# Instruments
NIFTY_UNDERLYING_ID = 13
BANKNIFTY_UNDERLYING_ID = 25

# Ollama
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")

# Lot Sizes (verify from Dhan instrument master CSV)
NIFTY_LOT_SIZE = int(os.environ.get("NIFTY_LOT_SIZE", "25"))
BANKNIFTY_LOT_SIZE = int(os.environ.get("BANKNIFTY_LOT_SIZE", "15"))

# Validation
def validate_config():
    """Validate required configuration is present."""
    errors = []
    if not DHAN_CLIENT_ID:
        errors.append("DHAN_CLIENT_ID not set (add to .env or environment)")
    if not DHAN_ACCESS_TOKEN:
        errors.append("DHAN_ACCESS_TOKEN not set (add to .env or environment)")
    if errors:
        raise RuntimeError("Configuration errors:\n  - " + "\n  - ".join(errors))

# Run validation on import
validate_config()