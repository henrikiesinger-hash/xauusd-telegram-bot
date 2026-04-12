import logging
import time
import csv
import os
import requests
import threading

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
# CSV TRADE LOG
# ==============================

CSV_FILE = "trade_log.csv"


def init_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp", "date_utc", "direction", "entry", "sl", "tp",
                "sl_dist", "tp_dist", "rr", "score", "confidence",
                "result", "pnl", "duration_h"
            ])


init_csv()


def log_trade(trade, result, pnl, duration_h):
    try:
        with open(CSV_FILE, "a", newline="") as f:
            writer = csv.writer(f)

            rr = round(trade["tp_dist"] / trade["sl_dist"], 1) if trade["sl_dist"] > 0 else 0

            writer.writerow([
                trade["timestamp"],
                time.strftime("%Y-%m-%d %H:%M", time.gmtime(trade["timestamp"])),
                trade["direction"],
                trade["entry"],
                trade["sl"],
                trade["tp"],
                trade["sl_dist"],
                trade["tp_dist"],
                rr,
                trade["score"],
                trade.get("confidence", ""),
                result,
                round(pnl, 2),
                round(duration_h, 1)
            ])

        log.info("CSV logged: %s %s | %s | $%.2f",
                 trade["direction"], trade["entry"], result, pnl)

    except Exception as e:
        log.error("CSV log failed: %s", e)


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


def send_telegram_file(file_path):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"

    try:
        with open(file_path, "rb") as f:
            resp = requests.post(
                url,
                data={"chat_id": CHAT_ID},
                files={"document": (os.path.basename(file_path), f)},
                timeout=30
            )

        if resp.status_code == 200:
            log.info("Telegram file sent OK")
            return True
        else:
            log.error("Telegram file error: %s", resp.text)
            return False

    except Exception as e:
        log.error("Telegram file failed: %s", e)
        return False


# ==============================
# TELEGRAM COMMANDS
# ==============================

def handle_command(text):
    if text == "/log":
        if os.path.exists(CSV_FILE):
            send_telegram_file(CSV_FILE)
        else:
            send_telegram("No trade log yet.")

    elif text == "/status":
        msg = (
            "<b>Bot Status</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Mode: LIVE\n"
            f"Active trades: {len(active_trades)}\n"
            f"Time: {time.strftime('%H:%M UTC', time.gmtime())}"
        )
        send_telegram(msg)

    elif text == "/stats":
        if not os.path.exists(CSV_FILE):
            send_telegram("No trade data yet.")
            return

        wins = 0
        losses = 0
        total_pnl = 0.0

        with open(CSV_FILE, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["result"] == "WIN":
                    wins += 1
                elif row["result"] == "LOSS":
                    losses += 1
                try:
                    total_pnl += float(row["pnl"])
                except:
                    pass

        total = wins + losses
        winrate = round((wins / total) * 100, 1) if total > 0 else 0
        avg = round(total_pnl / total, 2) if total > 0 else 0

        msg = (
            "<b>Performance Stats</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Wins: {wins}\n"
            f"Losses: {losses}\n"
            f"Winrate: {winrate}%\n"
            f"Total PnL: ${round(total_pnl, 2)}\n"
            f"Avg/Trade: ${avg}"
        )

        send_telegram(msg)


def poll_telegram():
    offset = 0
    log.info("Telegram polling started")

    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"

            resp = requests.get(
                url,
                params={"offset": offset, "timeout": 30},
                timeout=35
            )

            if resp.status_code == 200:
                updates = resp.json().get("result", [])

                for update in updates:
                    offset = update["update_id"] + 1

                    message = update.get("message", {})
                    text = message.get("text", "").strip().lower()
                    chat_id = str(message.get("chat", {}).get("id", ""))

                    if chat_id != str(CHAT_ID):
                        continue

                    if text.startswith("/"):
                        handle_command(text)

        except Exception as e:
            log.error("Polling error: %s", e)
            time.sleep(5)


# ==============================
# TRADE CHECK
# ==============================

def check_trade_result(trade):
    try:
        data = get_candles("5min", 50)
        if not data:
            return None

        trade_age_seconds = time.time() - trade["timestamp"]
        candles_since_trade = int(trade_age_seconds / 300)

        if candles_since_trade < 1:
            return None

        start = max(0, len(data["close"]) - candles_since_trade)

        for i in range(start, len(data["close"])):
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
            import strategy
            strategy._last_trade_result = result

        if result:
            emoji = "✅" if result == "WIN" else "❌"
            pnl = trade["tp_dist"] if result == "WIN" else -trade["sl_dist"]

            msg = (
                f"{emoji} <b>TRADE {result}</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"Direction: {trade['direction']}\n"
                f"Entry: {trade['entry']}\n"
                f"{'TP HIT' if result == 'WIN' else 'SL HIT'}: "
                f"{trade['tp'] if result == 'WIN' else trade['sl']}\n"
                f"PnL: ${pnl:.2f}\n"
                f"Score: {trade['score']}/10\n\n"
                f"⏱ Duration: {age_hours:.1f}h"
            )

            send_telegram(msg)
            log_trade(trade, result, pnl, age_hours)

        elif age_hours > 24:
            send_telegram(
                f"⏰ Trade expired: {trade['direction']} @ {trade['entry']}"
            )
            log_trade(trade, "EXPIRED", 0, age_hours)

        else:
            remaining.append(trade)

    active_trades = remaining


# ==============================
# SIGNAL FORMAT
# ==============================

def format_signal(signal):
    emoji = "🟢" if signal["direction"] == "BUY" else "🔴"

    return (
        f"{emoji} <b>XAUUSD {signal['direction']} SIGNAL</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 Entry: <b>{signal['entry']}</b>\n"
        f"🛑 SL: {signal['sl']} (${signal.get('sl_dist')})\n"
        f"✅ TP: {signal['tp']} (RR {signal.get('rr')})\n\n"
        f"📊 Score: {signal.get('score')}/10\n"
        f"🔥 Confidence: {signal.get('confidence')}\n\n"
        f"⏰ {time.strftime('%H:%M UTC', time.gmtime())}"
    )


# ==============================
# CORE
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

        send_telegram(format_signal(signal))

        tp_dist = abs(signal["tp"] - signal["entry"])

        active_trades.append({
            "direction": signal["direction"],
            "entry": signal["entry"],
            "sl": signal["sl"],
            "tp": signal["tp"],
            "sl_dist": signal.get("sl_dist", 0),
            "tp_dist": tp_dist,
            "score": signal.get("score", 0),
            "confidence": signal.get("confidence", ""),
            "timestamp": time.time(),
        })

    except Exception as e:
        log.error("Analysis failed: %s", e, exc_info=True)


# ==============================
# STARTUP
# ==============================

scheduler = BackgroundScheduler()
scheduler.add_job(run_analysis, "interval", minutes=1)
scheduler.add_job(check_active_trades, "interval", minutes=1)
scheduler.start()

try:
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook",
        timeout=10
    )
except:
    pass

threading.Thread(target=poll_telegram, daemon=True).start()

log.info("Bot started - FULL SYSTEM")

# ==============================
# RUN
# ==============================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)