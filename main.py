import requests
import time

TOKEN = "8725949555:AAGAP_yRzQuiaRKumniwkBSu7SdMLQHgtzA
"
CHAT_ID = "6669831090"

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
