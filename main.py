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
        logging.info(f"Telegram response: {response.text}")
    except Exception as e:
        logging.error(f"Telegram error: {e}")


# ==============================
# BOT LOGIC
# ==============================

def run_bot():

    logging.info("Bot check running...")

    # FILTERS
    if not weekend_filter():
        logging.info("Weekend - no trading")
        return

    if not session_filter():
        logging.info("Session closed")
        return

    if not cooldown_filter():
        logging.info("Cooldown active")
        return

    # DATA
    data = get_candles("5min")

    if data is None:
        logging.info("No market data")
        return

    # SIGNAL
    signal = generate_signal(data)

    if signal is None:
        logging.info("No valid signal")
        return

    # MESSAGE
    message = f"""
🔥 XAUUSD SMART MONEY SIGNAL

Direction: {signal["direction"]}
Entry: {signal["entry"]}
Stop Loss: {signal["sl"]}
Take Profit: {signal["tp"]}

Signal Score: {signal["score"]}/10

Setup:
{signal["notes"]}
"""

    # SEND
    send_telegram(message)

    # UPDATE COOLDOWN
    update_signal_time()

# ==============================
# SCHEDULER
# ==============================

scheduler = BackgroundScheduler()
scheduler.add_job(run_bot, "interval", minutes=5, max_instances=1)
scheduler.start()


# ==============================
# START SERVER
# ==============================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)