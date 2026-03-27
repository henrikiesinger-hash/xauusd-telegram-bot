import requests
import logging
logging.basicConfig(level=logging.INFO)

from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

from config import TELEGRAM_TOKEN, CHAT_ID
from data import get_candles
from strategy import generate_signal
from filters import weekend_filter, session_filter, cooldown_filter, update_signal_time

app = Flask(__name__)


@app.route("/")
def home():
    return "Gold Sniper Bot Running"


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
# LIVE BOT (wird im Test NICHT benutzt)
# ==============================

def run_bot():

    logging.info("Bot check running...")

    if not weekend_filter():
        logging.info("Weekend - no trading")
        return

    if not session_filter():
        logging.info("Session closed")
        return

    if not cooldown_filter():
        logging.info("Cooldown active")
        return

    data = get_candles("5min")

    if data is None:
        logging.info("No market data")
        return

    try:
        signal = generate_signal(data)
    except Exception as e:
        logging.error(f"❌ Strategy error: {e}")
        return

    if signal is None:
        logging.info("No valid signal")
        return

    message = f"""
🔥 XAUUSD SMART MONEY SIGNAL

Direction: {signal["direction"]}
Entry: {signal["entry"]}
Stop Loss: {signal["sl"]}
Take Profit: {signal["tp"]}

Score: {signal.get("score", "N/A")}/10
"""

    send_telegram(message)
    update_signal_time()


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
            logging.error(f"❌ Strategy crash at {i}: {e}")
            continue

        if signal:
            signals_found += 1
            logging.info(f"✅ SIGNAL #{signals_found} at index {i}")
            logging.info(signal)

    logging.info(f"🔥 BACKTEST DONE — Signals found: {signals_found}")


# ==============================
# START SERVER
# ==============================

if __name__ == "__main__":
    test_bot()  # 🔥 TEST MODE AKTIV
    app.run(host="0.0.0.0", port=8080)