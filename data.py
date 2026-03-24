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

    try:
        r = requests.get(BASE_URL, params=params, timeout=10)
        data = r.json()
    except Exception as e:
        print("API REQUEST ERROR:", e)
        return None

    if "values" not in data:
        print("API ERROR:", data)
        return None

    candles = list(reversed(data["values"]))

    opens = [float(c["open"]) for c in candles]
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    closes = [float(c["close"]) for c in candles]
    times = [c["datetime"] for c in candles]

    return {
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "time": times
    }