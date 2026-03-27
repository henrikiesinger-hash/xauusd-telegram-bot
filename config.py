import os

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
TWELVE_DATA_KEY = os.environ.get("TWELVE_DATA_KEY")

SYMBOL = "XAU/USD"

# Score threshold — new scoring is direction-bound (max 11, stricter)

# Old system: 8/10 with inflated scores

# New system: 7/11 means ALL core components align in same direction

SIGNAL_SCORE_THRESHOLD = 7

COOLDOWN_MINUTES = 30