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
MIN_AVG_DOLLAR_VOL = 5_000_000   # $5M/day avg

# Today's move
MIN_GAIN_PCT = 2.0    # must be up at least 2% today
MAX_GAIN_PCT = 12.0   # not already blown out today

# Volume surge
MIN_VOLUME_RATIO = 1.5   # today's volume / 20-day avg volume

# Prior momentum (exclude if already ran hard before today)
MAX_5D_PRIOR_GAIN = 15.0

# Stop / target
ATR_STOP_MULT = 1.0   # stop = price - 1.0 × ATR(14)
RR_TARGET = 2.0       # target = price + 2.0 × risk
