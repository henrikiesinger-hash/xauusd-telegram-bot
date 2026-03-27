import requests
from config import TWELVE_DATA_KEY, SYMBOL


def get_candles(interval):
    try:
        url = f"https://api.twelvedata.com/time_series?symbol=XAU/USD&interval={interval}&apikey={TWELVE_DATA_KEY}&outputsize=200"

        response = requests.get(url)
        data = response.json()

        if "values" not in data:
            return None

        values = data["values"]

        closes = [float(c["close"]) for c in values][::-1]
        highs = [float(c["high"]) for c in values][::-1]
        lows = [float(c["low"]) for c in values][::-1]
        opens = [float(c["open"]) for c in values][::-1]

        return {
            "close": closes,
            "high": highs,
            "low": lows,
            "open": opens
        }

    except Exception as e:
        print("❌ Data error:", e)
        return None