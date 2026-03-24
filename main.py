import requests
import logging
logging.basicConfig(level=logging.INFO)

from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

from config import TELEGRAM_TOKEN, CHAT_ID


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
# BOT TEST
# ==============================

def run_bot():

    logging.info("TEST BOT RUNNING...")

    message = f"""
🔥 TEST SIGNAL

Bot funktioniert korrekt ✅

Time: TEST RUN
"""

    send_telegram(message)


# ==============================
# SCHEDULER
# ==============================

scheduler = BackgroundScheduler()
scheduler.add_job(run_bot, "interval", minutes=5)
scheduler.start()

# 🔥 WICHTIG: SOFORT AUSFÜHREN (TEST)
run_bot()


# ==============================
# START SERVER
# ==============================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)