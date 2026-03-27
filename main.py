import requests
import logging
logging.basicConfig(level=logging.INFO)

from flask import Flask

from config import TELEGRAM_TOKEN, CHAT_ID
from data import get_candles
from strategy import generate_signal

app = Flask(__name__)


@app.route("/")
def home():
    return "Gold Sniper Bot Running (TEST MODE)"


@app.route("/health")
def health():
    return {"status": "running"}


# ==============================
# TELEGRAM
# ==============================

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": message
    }

    try:
        response = requests.post(url, data=payload, timeout=10)
        logging.info(f"Telegram status: {response.status_code}")
    except Exception as e:
        logging.error(f"Telegram error: {e}")


# ==============================
# 🔥 TEST MODE (BACKTEST)
# ==============================

def test_bot():

    logging.info("🔥 START BACKTEST MODE")

    data = get_candles("5min")

    if data is None:
        logging.info("❌ No data")
        return

    closes = data["close"]
    highs = data["high"]
    lows = data["low"]
    opens = data["open"]

    logging.info(f"📊 Candles loaded: {len(closes)}")

    signals_found = 0

    for i in range(50, len(closes)):

        slice_data = {
            "close": closes[:i],
            "high": highs[:i],
            "low": lows[:i],
            "open": opens[:i],
        }

        try:
            signal = generate_signal(slice_data)
        except Exception as e:
            logging.error(f"❌ Strategy crash at index {i}: {e}")
            continue

        if signal:
            signals_found += 1

            logging.info(f"✅ SIGNAL #{signals_found} at index {i}")
            logging.info(f"""
Direction: {signal['direction']}
Entry: {signal['entry']}
SL: {signal['sl']}
TP: {signal['tp']}
Score: {signal.get('score')}
""")

    logging.info(f"🔥 BACKTEST DONE — Signals found: {signals_found}")


# ==============================
# START SERVER + TEST
# ==============================

test_bot()  # 🔥 WIRD BEIM START AUTOMATISCH AUSGEFÜHRT

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)