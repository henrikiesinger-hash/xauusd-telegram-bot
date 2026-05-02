import logging
import requests
import time
from config import TWELVE_DATA_KEY, SYMBOL

log = logging.getLogger("data")

# Cache für verschiedene Timeframes
CACHE = {}
CACHE_TIME = {}

# Cache gültig für X Sekunden
CACHE_TTL = 60


def get_candles(interval, limit=200):
    global CACHE, CACHE_TIME

    current_time = time.time()

    # 🔁 CACHE CHECK
    if (interval, limit) in CACHE:
        if current_time - CACHE_TIME[(interval, limit)] < CACHE_TTL:
            return CACHE[(interval, limit)]

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

        opens = [float(x["open"]) for x in values]
        highs = [float(x["high"]) for x in values]
        lows = [float(x["low"]) for x in values]
        closes = [float(x["close"]) for x in values]

        # Garbage-Candle-Validation (Memory #18, Trade #21 Fix)
        mask = [
            o > 0 and l > 0 and c > 0 and h >= max(o, c) and l <= min(o, c)
            for o, h, l, c in zip(opens, highs, lows, closes)
        ]
        rejected = sum(1 for m in mask if not m)
        if rejected > 0:
            log.warning(
                f"[CANDLE_REJECTED] symbol={SYMBOL} interval={interval} "
                f"rejected_count={rejected} total={len(opens)}"
            )
            opens = [o for o, m in zip(opens, mask) if m]
            highs = [h for h, m in zip(highs, mask) if m]
            lows = [l for l, m in zip(lows, mask) if m]
            closes = [c for c, m in zip(closes, mask) if m]

        candles = {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
        }

        # 🔥 CACHE SAVE
        CACHE[(interval, limit)] = candles
        CACHE_TIME[(interval, limit)] = current_time

        return candles

    except Exception as e:
        print("❌ Data error:", e)
        return None