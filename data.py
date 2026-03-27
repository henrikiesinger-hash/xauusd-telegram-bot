import requests
from config import TWELVE_DATA_KEY, SYMBOL


def get_candles(interval, limit=200):
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

        return {
            "open": [float(x["open"]) for x in values],
            "high": [float(x["high"]) for x in values],
            "low": [float(x["low"]) for x in values],
            "close": [float(x["close"]) for x in values],
        }

    except Exception as e:
        print("❌ Data error:", e)
        return None