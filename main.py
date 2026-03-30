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
# GLOBAL TRADE STORAGE
# ==============================

active_trades = []


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
# TRADE CHECK
# ==============================

def check_trade_result(trade):
    try:
        data = get_candles("5min", 50)
        if not data:
            return None

        for i in range(len(data["close"])):
            high = data["high"][i]
            low = data["low"][i]

            if trade["direction"] == "BUY":
                if low <= trade["sl"]:
                    return "LOSS"
                if high >= trade["tp"]:
                    return "WIN"
            else:
                if high >= trade["sl"]:
                    return "LOSS"
                if low <= trade["tp"]:
                    return "WIN"

        return None
    except Exception as e:
        log.error("Trade check failed: %s", e)
        return None


def check_active_trades():
    global active_trades
    remaining = []

    for trade in active_trades:
        age_hours = (time.time() - trade["timestamp"]) / 3600

        result = check_trade_result(trade)

        if result:
            emoji = "✅" if result == "WIN" else "❌"
            pnl = trade["tp_dist"] if result == "WIN" else -trade["sl_dist"]

            msg = (
                f"{emoji} <b>TRADE {result}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"Direction: {trade['direction']}\n"
                f"Entry: {trade['entry']}\n"
                f"{'TP HIT' if result == 'WIN' else 'SL HIT'}: "
                f"{trade['tp'] if result == 'WIN' else trade['sl']}\n"
                f"PnL: ${pnl:.2f}\n"
                f"Score: {trade['score']}/10\n\n"
                f"⏱ Duration: {age_hours:.1f}h"
            )

            send_telegram(msg)
            log.info(
                "TRADE CLOSED: %s %s | %s | $%.2f",
                trade["direction"],
                trade["entry"],
                result,
                pnl
            )

        elif age_hours > 24:
            send_telegram(
                f"⏰ Trade expired: {trade['direction']} @ {trade['entry']} (no SL/TP hit in 24h)"
            )
            log.info("TRADE EXPIRED: %s @ %s", trade["direction"], trade["entry"])

        else:
            remaining.append(trade)

    active_trades = remaining


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

        # 🔥 STORE TRADE
        tp_dist = abs(signal["tp"] - signal["entry"])

        active_trades.append({
            "direction": signal["direction"],
            "entry": signal["entry"],
            "sl": signal["sl"],
            "tp": signal["tp"],
            "sl_dist": signal.get("sl_dist", 0),
            "tp_dist": tp_dist,
            "score": signal.get("score", 0),
            "timestamp": time.time(),
        })

    except Exception as e:
        log.error("Analysis failed: %s", e, exc_info=True)


# ==============================
# SCHEDULER
# ==============================

scheduler = BackgroundScheduler()
scheduler.add_job(run_analysis, "interval", minutes=5)
scheduler.add_job(check_active_trades, "interval", minutes=5)
scheduler.start()

log.info("Bot started - Live Mode")


# ==============================
# RUN
# ==============================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)