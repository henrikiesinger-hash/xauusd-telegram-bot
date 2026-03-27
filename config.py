import os

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
TWELVE_DATA_KEY = os.environ.get("TWELVE_DATA_KEY")

SYMBOL = "XAU/USD"

# 🔥 NEUE SETTINGS
SIGNAL_SCORE_THRESHOLD = 6   # vorher zu hoch → jetzt optimal

COOLDOWN_MINUTES = 30