import requests
import time
import os
from datetime import datetime

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("6669831090")

def send_message(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text
    }
    requests.post(url, json=payload)

def get_gold_price():
    url = "https://api.gold-api.com/price/XAUUSD"
    response = requests.get(url)
    data = response.json()
    return data["price"]

def session_active():
    now = datetime.utcnow()
    hour = now.hour
    minute = now.minute

    # London Session
    if 7 <= hour < 10:
        return "London"

    # New York Session
    if 13 <= hour < 16:
        return "New York"

    return None

def check_signal(price):

    # einfache Demo Logik
    if price > 2200:
        return "BUY"

    if price < 2100:
        return "SELL"

    return None

def send_trade(signal, price, session):

    message = f"""
XAUUSD SIGNAL

Signal: {signal}
Price: {price}

Session: {session}

Bot running on Railway
"""

    send_message(message)

send_message("XAUUSD AI Trader Bot gestartet")

while True:

    try:

        session = session_active()

        if session:

            price = get_gold_price()
            signal = check_signal(price)

            if signal:
                send_trade(signal, price, session)

        time.sleep(300)

    except Exception as e:
        print(e)
        time.sleep(60)
