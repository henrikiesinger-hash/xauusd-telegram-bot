import requests
import os
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

# ==============================
# ENV VARIABLES
# ==============================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
TWELVE_DATA_KEY = os.environ.get("TWELVE_DATA_KEY")

# ==============================
# FLASK APP
# ==============================

app = Flask(__name__)

@app.route("/")
def home():
    return "XAUUSD Sniper Bot Running"

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
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print("Telegram Error:", e)

# ==============================
# MARKET DATA
# ==============================

def get_gold_price():

    url = "https://api.twelvedata.com/price"

    params = {
        "symbol": "XAU/USD",
        "apikey": TWELVE_DATA_KEY
    }

    r = requests.get(url, params=params, timeout=10)
    data = r.json()

    if "price" not in data:
        print("API Error:", data)
        return None

    return float(data["price"])

# ==============================
# SIGNAL ENGINE
# ==============================

def check_signal(price):

    score = 7

    if price % 2 > 1:
        signal = "BUY"
    else:
        signal = "SELL"

    return signal, score

# ==============================
# SEND TRADE
# ==============================

def run_bot():

    print("Running bot check...")

    price = get_gold_price()

    if price is None:
        return

    signal, score = check_signal(price)

    sl = round(price - 2, 2)
    tp = round(price + 5, 2)

    message = f"""
🔥 XAUUSD SNIPER SIGNAL

Signal: {signal}

Entry: {price}
Stop Loss: {sl}
Take Profit: {tp}

Score: {score}/10
RR: 1:2
"""

    send_telegram(message)

# ==============================
# SCHEDULER
# ==============================

scheduler = BackgroundScheduler()
scheduler.add_job(run_bot, "interval", minutes=5)
scheduler.start()

print("Scheduler started")

# ==============================
# START SERVER
# ==============================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
