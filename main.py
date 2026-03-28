import logging
import time
import requests

from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

from data import get_candles
from strategy import generate_signal
from config import TELEGRAM_TOKEN, CHAT_ID


# ==============================
# LOGGING
# ==============================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(message)s"
)

log = logging.getLogger("main")


# ==============================
# FLASK
# ==============================

app = Flask(__name__)

@app.route("/")
def home():
    return {"status": "running", "mode": "live"}, 200


# ==============================
# TELEGRAM
# ==============================

def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        log.error("Telegram credentials missing")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)

        if resp.status_code == 200:
            log.info("Telegram sent OK")
            return True
        else:
            log.error("Telegram error: %s", resp.text)
            return False

    except Exception as e:
        log.error("Telegram failed: %s", e)
        return False


# ==============================
# SIGNAL FORMAT
# ==============================

def format_signal(signal):
    direction = signal["direction"]

    emoji = "🟢" if direction == "BUY" else "🔴"

    entry = signal["entry"]
    sl = signal["sl"]
    tp = signal["tp"]
    rr = signal.get("rr", "?")
    sl_dist = signal.get("sl_dist", "?")
    score = signal.get("score", "?")
    conf = signal.get("confidence", "N/A")

    msg = (
        f"{emoji} <b>XAUUSD {direction} SIGNAL</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 Entry: <b>{entry}</b>\n"
        f"🛑 SL: {sl} (${sl_dist})\n"
        f"✅ TP: {tp} (RR {rr})\n\n"
        f"📊 Score: {score}/10\n"
        f"🔥 Confidence: {conf}\n\n"
        f"⏰ {time.strftime('%H:%M UTC', time.gmtime())}"
    )

    return msg


# ==============================
# CORE LOGIC
# ==============================

def run_analysis():
    try:
        log.info("=== Tick ===")

        data_m5 = get_candles("5min", 200)

        if not data_m5:
            log.warning("No M5 data")
            return

        signal = generate_signal(data_m5)

        if signal is None:
            log.info("No signal")
            return

        log.info(
            "SIGNAL: %s @ %s | Score: %s",
            signal["direction"],
            signal["entry"],
            signal.get("score")
        )

        msg = format_signal(signal)
        send_telegram(msg)

    except Exception as e:
        log.error("Analysis failed: %s", e, exc_info=True)


# ==============================
# SCHEDULER
# ==============================

scheduler = BackgroundScheduler()
scheduler.add_job(run_analysis, "interval", minutes=5)
scheduler.start()

log.info("Bot started - Live Mode")


# ==============================
# RUN
# ==============================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)