import logging
logging.basicConfig(level=logging.INFO)

from flask import Flask
from data import get_candles
from strategy import generate_signal
import strategy

# 🔥 BACKTEST MODE AKTIVIEREN
strategy.BACKTEST_MODE = True

app = Flask(__name__)


@app.route("/")
def home():
    return "BACKTEST MODE"


# ==============================
# TRADE SIMULATION
# ==============================

def simulate_trade(data, entry_index, direction, entry, sl, tp1, tp2):
    tp1_hit = False

    for i in range(entry_index + 1, len(data["close"])):

        high = data["high"][i]
        low = data["low"][i]

        if direction == "BUY":

            if low <= sl:
                if tp1_hit:
                    return "PARTIAL", round(abs(tp1 - entry) - abs(entry - sl), 2)
                return "LOSS", round(-(entry - sl), 2)

            if not tp1_hit and high >= tp1:
                tp1_hit = True

            if high >= tp2:
                return "FULL WIN", round(abs(tp2 - entry), 2)

        else:  # SELL

            if high >= sl:
                if tp1_hit:
                    return "PARTIAL", round(abs(entry - tp1) - abs(sl - entry), 2)
                return "LOSS", round(-(sl - entry), 2)

            if not tp1_hit and low <= tp1:
                tp1_hit = True

            if low <= tp2:
                return "FULL WIN", round(abs(entry - tp2), 2)

    if tp1_hit:
        return "TP1 HIT", round(abs(tp1 - entry), 2)

    return "NO RESULT", 0.0


# ==============================
# BACKTEST ENGINE
# ==============================

def run_backtest():
    logging.info("🔥 START BACKTEST")

    data = get_candles("5min", 800)

    if not data:
        logging.error("❌ No data")
        return

    total_candles = len(data["close"])
    logging.info("Candles: %s", total_candles)

    total = 0
    full_wins = 0
    partial_wins = 0
    tp1_only = 0
    losses = 0
    no_result = 0
    total_pnl = 0.0

    for i in range(50, total_candles):

        sub_data = {
            "open": data["open"][:i],
            "high": data["high"][:i],
            "low": data["low"][:i],
            "close": data["close"][:i],
        }

        signal = generate_signal(sub_data, candle_index=i)

        if signal:
            total += 1

            tp1 = signal.get("tp1", signal.get("tp", 0))
            tp2 = signal.get("tp2", tp1)

            result, pnl = simulate_trade(
                data,
                i,
                signal["direction"],
                signal["entry"],
                signal["sl"],
                tp1,
                tp2,
            )

            total_pnl += pnl

            logging.info(
                "TRADE %s: %s @ %.2f | SL:%.2f | TP1:%.2f | TP2:%.2f | Score:%s | %s ($%.2f)",
                total,
                signal["direction"],
                signal["entry"],
                signal["sl"],
                tp1,
                tp2,
                signal.get("score", 0),
                result,
                pnl,
            )

            if result == "FULL WIN":
                full_wins += 1
            elif result == "PARTIAL":
                partial_wins += 1
            elif result == "TP1 HIT":
                tp1_only += 1
            elif result == "LOSS":
                losses += 1
            else:
                no_result += 1

    logging.info("====================================")
    logging.info("BACKTEST RESULTS")
    logging.info("====================================")
    logging.info("Total Trades: %s", total)
    logging.info("Full Wins: %s", full_wins)
    logging.info("Partial Wins: %s", partial_wins)
    logging.info("TP1 Only: %s", tp1_only)
    logging.info("Losses: %s", losses)
    logging.info("No Result: %s", no_result)

    winners = full_wins + partial_wins + tp1_only
    resolved = winners + losses

    if resolved > 0:
        winrate = (winners / resolved) * 100
        logging.info("Winrate: %.1f%% (%s/%s)", winrate, winners, resolved)

    logging.info("Total PnL: $%.2f", total_pnl)
    logging.info("====================================")


# 🔥 AUTO START
run_backtest()


# ==============================
# SERVER
# ==============================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)