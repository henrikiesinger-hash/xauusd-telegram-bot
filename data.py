import requests
from config import TWELVE_DATA_KEY, SYMBOL

BASE_URL = "https://api.twelvedata.com/time_series"


def get_candles(interval="5min", limit=200):

    params = {
        "symbol": SYMBOL,
        "interval": interval,
        "apikey": TWELVE_DATA_KEY,
        "outputsize": limit
    }

    r = requests.get(BASE_URL, params=params, timeout=10)
    data = r.json()

    if "values" not in data:
        print("API ERROR:", data)
        return None

    candles = list(reversed(data["values"]))

    closes = [float(c["close"]) for c in candles]
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]

    return {
        "close": closes,
        "high": highs,
        "low": lows
    }
