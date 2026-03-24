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
    return {"status":"running"}


def send_telegram(message):

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": message
    }

    try:
        response = requests.post(url, data=payload, timeout=10)
        print("Telegram response:", response.status_code)
        print("Telegram text:", response.text)
    except Exception as e:
        print("Telegram error:", e)


def run_bot():

    logging.info("Bot check running...")

    if not weekend_filter():
        print("Weekend")
        return

    if not session_filter():
        print("Session closed")
        return

    if not cooldown_filter():
        print("Cooldown active")
        return

    data = get_candles("5min")

    if data is None:
        return

    signal = generate_signal(data)

    if signal is None:
        print("No signal")
        return

    message = f"""
🔥 XAUUSD SNIPER SIGNAL

Direction: {signal["direction"]}

Entry: {signal["entry"]}

Stop Loss: {signal["sl"]}

Take Profit: {signal["tp"]}

Signal Score: {signal["score"]}/10
RR: 1:2
"""

    send_telegram(message)

    update_signal_time()


scheduler = BackgroundScheduler()
scheduler.add_job(run_bot,"interval",minutes=5)
scheduler.start()


if __name__ == "__main__":
    run_bot()  # ← HIER eingefügt
    app.run(host="0.0.0.0", port=8080)
