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

    # 🔥 SAFETY: check DataFrame structure
    try:
        if not all(col in data.columns for col in ["high", "low", "close"]):
            logging.error("❌ Data format invalid")
            return
    except Exception as e:
        logging.error(f"❌ Data error: {e}")
        return

    # SIGNAL
    try:
        signal = generate_signal(data)
    except Exception as e:
        logging.error(f"❌ Strategy error: {e}")
        return

    if signal is None:
        logging.info("No valid signal")
        return

    # 🔥 SAFETY: check keys
    if "direction" not in signal or "entry" not in signal:
        logging.error("❌ Signal missing keys")
        return

    direction = signal["direction"]
    entry = signal["entry"]

    # 🔥 SAFETY: check values
    if direction not in ["BUY", "SELL"]:
        logging.error("❌ Invalid direction")
        return

    try:
        entry = float(entry)
    except:
        logging.error("❌ Entry invalid")
        return

    # 🔥 RISK ENGINE
    try:
        trade = build_trade(data, direction, entry)
    except Exception as e:
        logging.error(f"❌ Risk Engine crash: {e}")
        return

    if not trade["valid"]:
        logging.info(f"❌ Trade blockiert: {trade['reason']}")
        return

    # MESSAGE
    message = f"""
🔥 XAUUSD SMART MONEY SIGNAL

Direction: {direction}
Entry: {trade["entry"]}
Stop Loss: {trade["sl"]}
Take Profit: {trade["tp"]}

Risk: {trade["risk"]}$

Signal Score: {signal.get("score", "N/A")}/10

Setup:
{signal.get("notes", "No details")}
"""

    send_telegram(message)

    update_signal_time()


# ==============================
# SCHEDULER
# ==============================

scheduler = BackgroundScheduler()
scheduler.add_job(run_bot, "interval", minutes=5, max_instances=1)
scheduler.start()
run_bot()


# ==============================
# START SERVER
# ==============================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)