import requests
import logging
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

from config import TELEGRAM_TOKEN, CHAT_ID
from data import get_candles
from strategy import generate_signal
from filters import weekend_filter, session_filter, cooldown_filter, update_signal_time

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)


@app.route("/")
def home():
    return "Gold Sniper Bot Running"


@app.route("/health")
def health():
    return {"status": "running"}


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

    if not all(key in data for key in ["open", "high", "low", "close"]):
        logging.error("❌ Data format invalid (dict keys missing)")
        return

    try:
        signal = generate_signal(data)
    except Exception as e:
        logging.error(f"❌ Strategy error: {e}")
        return

    if signal is None:
        logging.info("No valid signal")
        return

    if not all(key in signal for key in ["direction", "entry", "sl", "tp"]):
        logging.error("❌ Signal missing keys")
        return

    direction = signal["direction"]
    entry = signal["entry"]
    sl = signal["sl"]
    tp = signal["tp"]

    if direction not in ["BUY", "SELL"]:
        logging.error("❌ Invalid direction")
        return

    try:
        entry = float(entry)
        sl = float(sl)
        tp = float(tp)
    except Exception:
        logging.error("❌ Entry/SL/TP invalid")
        return

    message = f"""
🔥 XAUUSD SMART MONEY SIGNAL

Direction: {direction}
Entry: {entry}
Stop Loss: {sl}
Take Profit: {tp}

Signal Score: {signal.get("score", "N/A")}/10

Setup:
{signal.get("notes", "No details")}
"""

    send_telegram(message)
    update_signal_time()


scheduler = BackgroundScheduler()
scheduler.add_job(run_bot, "interval", minutes=5, max_instances=1)
scheduler.start()

run_bot()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)