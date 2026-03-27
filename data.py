import requests
import time
from config import TWELVE_DATA_KEY, SYMBOL

# Cache für verschiedene Timeframes
CACHE = {}
CACHE_TIME = {}

# Cache gültig für X Sekunden
CACHE_TTL = 60


def get_candles(interval, limit=200):
    global CACHE, CACHE_TIME

    current_time = time.time()

    # 🔁 CACHE CHECK
    if interval in CACHE:
        if current_time - CACHE_TIME[interval] < CACHE_TTL:
            return CACHE[interval]

    url = "https://api.twelvedata.com/time_series"

    params = {
        "symbol": SYMBOL,
        "interval": interval,
        "outputsize": limit,
        "apikey": TWELVE_DATA_KEY
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()

        if "values" not in data:
            print("❌ API error:", data)
            return None

        values = list(reversed(data["values"]))

        candles = {
            "open": [float(x["open"]) for x in values],
            "high": [float(x["high"]) for x in values],
            "low": [float(x["low"]) for x in values],
            "close": [float(x["close"]) for x in values],
        }

        # 🔥 CACHE SAVE
        CACHE[interval] = candles
        CACHE_TIME[interval] = current_time

        return candles

    except Exception as e:
        print("❌ Data error:", e)
        return None