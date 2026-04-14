import logging
import time
import csv
import os
import requests
import threading

from flask import Flask, jsonify
from apscheduler.schedulers.background import BackgroundScheduler

from data import get_candles
from strategy import generate_signal, is_active_session
from config import TELEGRAM_TOKEN, CHAT_ID
import database

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
    rr = round(trade["tp_dist"] / trade["sl_dist"], 1) if trade["sl_dist"] > 0 else 0
    date_utc = time.strftime("%Y-%m-%d %H:%M", time.gmtime(trade["timestamp"]))

    # CSV logging (backup)
    try:
        with open(CSV_FILE, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                trade["timestamp"], date_utc,
                trade["direction"], trade["entry"],
                trade["sl"], trade["tp"],
                trade["sl_dist"], trade["tp_dist"],
                rr, trade["score"],
                trade.get("confidence", ""),
                result, round(pnl, 2), round(duration_h, 1)
            ])
        log.info("CSV logged: %s %s | %s | $%.2f",
                 trade["direction"], trade["entry"], result, pnl)
    except Exception as e:
        log.error("CSV log failed: %s", e)

    # Supabase logging (primary)
    database.save_trade({
        "timestamp": trade["timestamp"],
        "date_utc": date_utc,
        "direction": trade["direction"],
        "entry": trade["entry"],
        "sl": trade["sl"],
        "tp": trade["tp"],
        "sl_dist": trade["sl_dist"],
        "tp_dist": trade["tp_dist"],
        "rr": rr,
        "score": trade["score"],
        "confidence": trade.get("confidence", ""),
        "result": result,
        "pnl": round(pnl, 2),
        "duration_h": round(duration_h, 1),
    })


# ==============================
# FLASK
# ==============================

app = Flask(__name__)


@app.route("/")
def home():
    return {"status": "running", "mode": "live"}, 200


@app.route("/dashboard")
def dashboard_json():
    stats = database.get_stats()
    if not stats:
        return {"error": "No data available"}, 503

    recent = database.get_recent_trades(20)
    stats["active_trades"] = len(active_trades)
    stats["last_20_trades"] = recent or []
    return jsonify(stats)


@app.route("/dashboard/html")
def dashboard_html():
    stats = database.get_stats()
    recent = database.get_recent_trades(10) or []

    if not stats:
        stats = {
            "total_trades": 0, "wins": 0, "losses": 0, "winrate": 0,
            "total_pnl": 0, "avg_pnl": 0, "best_trade": None,
            "worst_trade": None, "current_streak": {"type": "none", "count": 0},
        }

    streak = stats["current_streak"]
    session_active = is_active_session()
    session_color = "#00c853" if session_active else "#ff1744"
    session_label = "IN SESSION" if session_active else "OFFLINE"
    utc_now = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())

    # Best/worst trade display
    best = stats.get("best_trade")
    worst = stats.get("worst_trade")
    best_str = f"${best['pnl']} ({best['direction']})" if best else "—"
    worst_str = f"${worst['pnl']} ({worst['direction']})" if worst else "—"

    # Confidence breakdown from recent trades
    all_trades = database.get_all_trades() or []
    sniper = sum(1 for t in all_trades if t.get("confidence") == "SNIPER")
    high = sum(1 for t in all_trades if t.get("confidence") == "HIGH")
    moderate = sum(1 for t in all_trades if t.get("confidence") == "MODERATE")
    conf_total = sniper + high + moderate
    sniper_pct = round(sniper / conf_total * 100) if conf_total else 0
    high_pct = round(high / conf_total * 100) if conf_total else 0
    moderate_pct = round(moderate / conf_total * 100) if conf_total else 0

    # Trade rows
    trades_rows = ""
    for t in recent:
        r = t.get("result", "")
        if r == "WIN":
            emoji, color = "&#x2705;", "#00c853"
        elif r == "LOSS":
            emoji, color = "&#x274C;", "#ff1744"
        else:
            emoji, color = "&#x23F0;", "#d4af37"
        pnl = t.get("pnl", 0)
        pnl_sign = "+" if pnl > 0 else ""
        trades_rows += (
            f"<tr>"
            f"<td>{emoji}</td>"
            f"<td style='color:#aaa'>{t.get('date_utc', '')[5:]}</td>"
            f"<td><span style='color:{'#00c853' if t.get('direction')=='BUY' else '#ff1744'}'>"
            f"{t.get('direction', '')}</span></td>"
            f"<td>{t.get('entry', '')}</td>"
            f"<td style='color:{color};font-weight:600'>{pnl_sign}${pnl}</td>"
            f"<td>{t.get('score', '')}</td>"
            f"<td>{t.get('rr', '')}</td>"
            f"</tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>XAUUSD Signal Bot</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0a0a0f;color:#c8c8d0;font-family:-apple-system,system-ui,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:16px;max-width:600px;margin:0 auto}}
.header{{display:flex;align-items:center;justify-content:space-between;padding:16px 0;border-bottom:1px solid #1a1a2e;margin-bottom:20px}}
.header h1{{color:#d4af37;font-size:1.15rem;letter-spacing:1px}}
.status{{display:flex;align-items:center;gap:6px;font-size:0.7rem;color:{session_color};text-transform:uppercase;letter-spacing:1px;font-weight:600}}
.status .dot{{width:8px;height:8px;border-radius:50%;background:{session_color};box-shadow:0 0 6px {session_color}}}
.section-title{{color:#d4af37;font-size:0.7rem;text-transform:uppercase;letter-spacing:2px;margin:20px 0 10px;font-weight:600}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
.card{{background:#1a1a2e;border-radius:10px;padding:14px;border:1px solid #252540}}
.card .label{{color:#666;font-size:0.65rem;text-transform:uppercase;letter-spacing:1px}}
.card .value{{font-size:1.35rem;font-weight:700;margin-top:4px;color:#e8e8f0}}
.card .value.green{{color:#00c853}}
.card .value.red{{color:#ff1744}}
.card .value.gold{{color:#d4af37}}
.conf-bar{{margin-top:4px;height:6px;border-radius:3px;background:#252540;overflow:hidden;display:flex}}
.conf-bar .seg{{height:100%}}
.conf-legend{{display:flex;gap:12px;margin-top:8px;font-size:0.7rem;color:#888}}
.conf-legend span{{display:flex;align-items:center;gap:4px}}
.conf-legend .dot-s{{width:6px;height:6px;border-radius:50%;background:#d4af37}}
.conf-legend .dot-h{{width:6px;height:6px;border-radius:50%;background:#00c853}}
.conf-legend .dot-m{{width:6px;height:6px;border-radius:50%;background:#555}}
table{{width:100%;border-collapse:collapse;font-size:0.78rem}}
thead th{{text-align:left;color:#555;font-size:0.65rem;text-transform:uppercase;letter-spacing:1px;padding:8px 4px;border-bottom:1px solid #1a1a2e}}
tbody td{{padding:10px 4px;border-bottom:1px solid #111118}}
tbody tr:hover{{background:#111118}}
.footer{{text-align:center;color:#444;font-size:0.65rem;padding:20px 0 8px;border-top:1px solid #1a1a2e;margin-top:24px}}
</style></head><body>

<div class="header">
<h1>XAUUSD SIGNAL BOT</h1>
<div class="status"><div class="dot"></div>{session_label}</div>
</div>

<div class="section-title">Performance</div>
<div class="grid">
<div class="card"><div class="label">Total Trades</div><div class="value">{stats['total_trades']}</div></div>
<div class="card"><div class="label">Winrate</div><div class="value {'green' if stats['winrate']>=50 else 'red'}">{stats['winrate']}%</div></div>
<div class="card"><div class="label">Total PnL</div><div class="value {'green' if stats['total_pnl']>=0 else 'red'}">{'+'if stats['total_pnl']>=0 else ''}${stats['total_pnl']}</div></div>
<div class="card"><div class="label">Avg / Trade</div><div class="value {'green' if stats['avg_pnl']>=0 else 'red'}">{'+'if stats['avg_pnl']>=0 else ''}${stats['avg_pnl']}</div></div>
<div class="card"><div class="label">Best Trade</div><div class="value green" style="font-size:1rem">{best_str}</div></div>
<div class="card"><div class="label">Worst Trade</div><div class="value red" style="font-size:1rem">{worst_str}</div></div>
</div>

<div class="section-title">Confidence Breakdown</div>
<div class="card">
<div class="conf-bar">
<div class="seg" style="width:{sniper_pct}%;background:#d4af37"></div>
<div class="seg" style="width:{high_pct}%;background:#00c853"></div>
<div class="seg" style="width:{moderate_pct}%;background:#555"></div>
</div>
<div class="conf-legend">
<span><div class="dot-s"></div>SNIPER {sniper}</span>
<span><div class="dot-h"></div>HIGH {high}</span>
<span><div class="dot-m"></div>MOD {moderate}</span>
</div>
</div>

<div class="section-title">Recent Trades</div>
<table>
<thead><tr><th></th><th>Date</th><th>Dir</th><th>Entry</th><th>PnL</th><th>Score</th><th>RR</th></tr></thead>
<tbody>{trades_rows if trades_rows else '<tr><td colspan="7" style="text-align:center;color:#444;padding:20px">No trades yet</td></tr>'}</tbody>
</table>

<div class="footer">Last updated: {utc_now}</div>
</body></html>"""
    return html


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
        # Try Supabase first, CSV as fallback
        stats = database.get_stats()

        if stats:
            wins = stats["wins"]
            losses = stats["losses"]
            winrate = stats["winrate"]
            total_pnl = stats["total_pnl"]
            avg = stats["avg_pnl"]
        else:
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

    elif text == "/dashboard":
        stats = database.get_stats()

        if not stats:
            send_telegram("Dashboard unavailable — no Supabase data.")
            return

        streak = stats["current_streak"]
        streak_emoji = "🟢" if streak["type"] == "WIN" else "🔴" if streak["type"] == "LOSS" else "⚪"

        msg = (
            "<b>Dashboard</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Trades: {stats['total_trades']}\n"
            f"Wins: {stats['wins']} | Losses: {stats['losses']}\n"
            f"Winrate: {stats['winrate']}%\n\n"
            f"Total PnL: ${stats['total_pnl']}\n"
            f"Avg/Trade: ${stats['avg_pnl']}\n\n"
            f"{streak_emoji} Streak: {streak['count']}x {streak['type']}\n"
            f"Active: {len(active_trades)} trade(s)\n\n"
        )

        if stats["best_trade"]:
            b = stats["best_trade"]
            msg += f"Best: {b['direction']} @ {b['entry']} → ${b['pnl']}\n"
        if stats["worst_trade"]:
            w = stats["worst_trade"]
            msg += f"Worst: {w['direction']} @ {w['entry']} → ${w['pnl']}"

        send_telegram(msg)

    elif text == "/review":
        generate_weekly_review()

    elif text == "/trades":
        trades = database.get_recent_trades(10)

        if trades is None:
            trades = []
            if os.path.exists(CSV_FILE):
                with open(CSV_FILE, "r") as f:
                    rows = list(csv.DictReader(f))
                for row in rows[-10:]:
                    trades.append({
                        "direction": row.get("direction", ""),
                        "entry": row.get("entry", ""),
                        "pnl": float(row.get("pnl", 0)),
                        "result": row.get("result", ""),
                        "score": row.get("score", ""),
                        "duration_h": row.get("duration_h", ""),
                    })

        if not trades:
            send_telegram("No trades yet.")
            return

        lines = ["<b>Last 10 Trades</b>\n━━━━━━━━━━━━━━━━━━━━\n"]
        total_pnl = 0
        wins = 0
        losses = 0

        for t in trades:
            r = t.get("result", "")
            emoji = "✅" if r == "WIN" else "❌" if r == "LOSS" else "⏰"
            pnl = t.get("pnl", 0)
            total_pnl += pnl
            if r == "WIN":
                wins += 1
            elif r == "LOSS":
                losses += 1
            lines.append(
                f"{emoji} {t.get('direction', '')} @ {t.get('entry', '')} | "
                f"${pnl} | Score {t.get('score', '')} | {t.get('duration_h', '')}h"
            )

        count = wins + losses
        wr = round((wins / count) * 100, 1) if count > 0 else 0
        lines.append(f"\n{wins}W/{losses}L | WR {wr}% | PnL ${round(total_pnl, 2)}")
        send_telegram("\n".join(lines))

    elif text == "/today":
        trades = database.get_trades_today()

        if trades is None:
            trades = []
            if os.path.exists(CSV_FILE):
                today_str = time.strftime("%Y-%m-%d", time.gmtime())
                with open(CSV_FILE, "r") as f:
                    for row in csv.DictReader(f):
                        if row.get("date_utc", "").startswith(today_str):
                            trades.append({
                                "result": row.get("result", ""),
                                "pnl": float(row.get("pnl", 0)),
                            })

        session = "Active" if is_active_session() else "Inactive"
        utc_now = time.strftime("%H:%M UTC", time.gmtime())

        if not trades:
            send_telegram(
                f"<b>Today's Summary</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"No trades today.\n\n"
                f"Session: {session}\n"
                f"Time: {utc_now}"
            )
            return

        wins = sum(1 for t in trades if t.get("result") == "WIN")
        losses = sum(1 for t in trades if t.get("result") == "LOSS")
        pnl = round(sum(t.get("pnl", 0) for t in trades), 2)

        send_telegram(
            f"<b>Today's Summary</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Trades: {len(trades)}\n"
            f"Wins: {wins} | Losses: {losses}\n"
            f"PnL: ${pnl}\n\n"
            f"Session: {session}\n"
            f"Time: {utc_now}"
        )

    elif text == "/pnl":
        weeks = database.get_weekly_pnl(4)

        if not weeks or all(w["trades"] == 0 for w in weeks):
            send_telegram("No PnL data available.")
            return

        lines = ["<b>Weekly PnL (Last 4 Weeks)</b>\n━━━━━━━━━━━━━━━━━━━━\n"]
        total = 0

        for w in reversed(weeks):
            pnl = w["pnl"]
            total += pnl
            emoji = "📈" if pnl >= 0 else "📉"
            sign = "+" if pnl >= 0 else ""
            lines.append(f"W{w['week']}: {sign}${pnl} {emoji} ({w['trades']} trades)")

        total_emoji = "📈" if total >= 0 else "📉"
        sign = "+" if total >= 0 else ""
        lines.append(f"\nTotal: {sign}${round(total, 2)} {total_emoji}")
        send_telegram("\n".join(lines))

    elif text == "/help":
        send_telegram(
            "<b>Available Commands</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "/status — Bot status, active trades, time\n"
            "/stats — Winrate, total PnL, avg per trade\n"
            "/trades — Last 10 trades with details\n"
            "/today — Today's summary\n"
            "/pnl — Weekly PnL (last 4 weeks)\n"
            "/dashboard — Full performance overview\n"
            "/review — Weekly review (auto: Fri 21 UTC)\n"
            "/log — Download trade_log.csv\n"
            "/help — This message"
        )


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
# WEEKLY REVIEW
# ==============================

def generate_weekly_review():
    now = time.time()
    week_ago = now - 7 * 24 * 3600
    week_nr = time.strftime("%W", time.gmtime())

    # Try Supabase, fallback to CSV
    trades = database.get_trades_since(week_ago)

    if trades is None:
        trades = []
        if os.path.exists(CSV_FILE):
            with open(CSV_FILE, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        ts = float(row["timestamp"])
                    except (ValueError, KeyError):
                        continue
                    if ts >= week_ago:
                        trades.append({
                            "direction": row.get("direction", ""),
                            "entry": float(row.get("entry", 0)),
                            "pnl": float(row.get("pnl", 0)),
                            "result": row.get("result", ""),
                            "rr": float(row.get("rr", 0)),
                            "duration_h": float(row.get("duration_h", 0)),
                            "score": float(row.get("score", 0)),
                            "confidence": row.get("confidence", ""),
                        })

    if not trades:
        send_telegram("No trades this week.")
        return

    wins = [t for t in trades if t.get("result") == "WIN"]
    losses = [t for t in trades if t.get("result") == "LOSS"]
    resolved = len(wins) + len(losses)
    total_pnl = sum(t.get("pnl", 0) for t in trades)
    winrate = round((len(wins) / resolved) * 100, 1) if resolved > 0 else 0
    avg_pnl = round(total_pnl / resolved, 2) if resolved > 0 else 0

    sorted_by_pnl = sorted(trades, key=lambda t: t.get("pnl", 0))
    best = sorted_by_pnl[-1]
    worst = sorted_by_pnl[0]

    rr_values = [t.get("rr", 0) for t in trades if t.get("rr")]
    avg_rr = round(sum(rr_values) / len(rr_values), 1) if rr_values else 0

    dur_values = [t.get("duration_h", 0) for t in trades if t.get("duration_h")]
    avg_dur = round(sum(dur_values) / len(dur_values), 1) if dur_values else 0

    sniper = sum(1 for t in trades if t.get("confidence") == "SNIPER")
    high = sum(1 for t in trades if t.get("confidence") == "HIGH")
    moderate = sum(1 for t in trades if t.get("confidence") == "MODERATE")

    msg = (
        f"<b>WEEKLY REVIEW — Week {week_nr}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Trades: {len(trades)} | Wins: {len(wins)} | Losses: {len(losses)}\n"
        f"Winrate: {winrate}%\n"
        f"Total PnL: ${round(total_pnl, 2)}\n"
        f"Avg PnL: ${avg_pnl}\n\n"
        f"Best Trade: ${best.get('pnl', 0)} ({best.get('direction', '')} @ {best.get('entry', '')})\n"
        f"Worst Trade: ${worst.get('pnl', 0)} ({worst.get('direction', '')} @ {worst.get('entry', '')})\n\n"
        f"Avg RR: {avg_rr}:1\n"
        f"Avg Duration: {avg_dur}h\n\n"
        f"<b>Confidence Breakdown:</b>\n"
        f"SNIPER: {sniper} trades\n"
        f"HIGH: {high} trades\n"
        f"MODERATE: {moderate} trades"
    )

    send_telegram(msg)
    log.info("Weekly review sent — Week %s, %s trades", week_nr, len(trades))


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

_last_outside_session_log = 0


def run_analysis():
    global _last_outside_session_log
    try:
        if not is_active_session():
            now = time.time()
            if now - _last_outside_session_log >= 900:
                log.info("Outside trading session")
                _last_outside_session_log = now
            return

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
scheduler.add_job(run_analysis, "interval", minutes=5)
scheduler.add_job(check_active_trades, "interval", minutes=2)
scheduler.add_job(generate_weekly_review, "cron", day_of_week="fri", hour=21, minute=0)
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