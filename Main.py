import requests
import time

TOKEN = "DEIN_TELEGRAM_TOKEN"
CHAT_ID = "DEINE_CHAT_ID"

def send_message(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": text
    }
    requests.post(url, data=data)

while True:
    send_message("Bot läuft und scannt den Markt...")
    time.sleep(300)
