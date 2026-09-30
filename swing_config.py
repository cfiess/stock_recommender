import os

# Email
EMAIL_FROM = os.getenv("GMAIL_USER", "")
EMAIL_TO = "cfiess@gmail.com"
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")

# Picks
NUM_PICKS = 3

# Price / liquidity
MIN_PRICE = 10.0
MAX_PRICE = 200.0
MIN_AVG_DOLLAR_VOL = 5_000_000

# Today's move
MIN_GAIN_PCT = 2.0
MAX_GAIN_PCT = 12.0

# Volume surge
MIN_VOLUME_RATIO = 1.5

# Prior momentum
MAX_5D_PRIOR_GAIN = 15.0

# Stop / target (ATR-based)
ATR_STOP_MULT = 1.0
RR_TARGET = 2.0

# Hard exclusion
EARNINGS_HARD_EXCLUDE_DAYS = 12

# Warning flags (don't exclude — annotate)
FLAG_ATR_EXTENSION = 2.5        # flag if (price - ma20) / atr14 > this
FLAG_NEAR_52W_HIGH_PCT = 2.0    # flag if within 2% of 52-week high
FLAG_STRUCTURAL_RR_MIN = 1.5    # flag if structural R:R < this

# Sector → ETF
SECTOR_ETF: dict[str, str] = {
    "Technology": "XLK",
    "Health Care": "XLV",
    "Financials": "XLF",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Industrials": "XLI",
    "Energy": "XLE",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Communication Services": "XLC",
}

# Outcome tracking
PICKS_LOG = "picks_log.csv"
