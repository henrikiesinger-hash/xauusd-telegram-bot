import logging
logging.basicConfig(level=logging.INFO)

from flask import Flask

from data import get_candles
from strategy import generate_signal

app = Flask(__name__)


@app.route("/")
def home():
    return "BACKTEST MODE RUNNING"


# ==============================
# TRADE SIMULATION
# ==============================

def simulate_trade(data, entry_index, direction, entry, sl, tp):

    for i in range(entry_index + 1, len(data["close"])):

        high = data["high"][i]
        low = data["low"][i]

        if direction == "BUY":

            if low <= sl:
                return "LOSS"

            if high >= tp:
                return "WIN"

        else:  # SELL

            if high >= sl:
                return "LOSS"

            if low <= tp:
                return "WIN"

    return "NO RESULT"


# ==============================
# BACKTEST ENGINE
# ==============================

def run_backtest():

    logging.info("🔥 START BACKTEST MODE")

    data = get_candles("5min")

    if not data:
        logging.error("❌ No data")
        return

    logging.info(f"📊 Candles loaded: {len(data['close'])}")

    wins = 0
    losses = 0
    total = 0

    # wir starten erst bei 50 Kerzen (sonst zu wenig Daten für Indikatoren)
    for i in range(50, len(data["close"])):

        sub_data = {
            "open": data["open"][:i],
            "high": data["high"][:i],
            "low": data["low"][:i],
            "close": data["close"][:i]
        }

        signal = generate_signal(sub_data)

        if signal:

            total += 1

            logging.info(f"📍 SIGNAL {total}: {signal}")

            result = simulate_trade(
                data,
                i,
                signal["direction"],
                signal["entry"],
                signal["sl"],
                signal["tp"]
            )

            logging.info(f"📊 RESULT: {result}")

            if result == "WIN":
                wins += 1
            elif result == "LOSS":
                losses += 1

    logging.info("====================================")
    logging.info(f"🔥 BACKTEST DONE")
    logging.info(f"Total Trades: {total}")
    logging.info(f"Wins: {wins}")
    logging.info(f"Losses: {losses}")

    if total > 0:
        winrate = (wins / total) * 100
        logging.info(f"Winrate: {round(winrate, 2)}%")

    logging.info("====================================")


# ==============================
# START
# ==============================

if __name__ == "__main__":
    run_backtest()
    app.run(host="0.0.0.0", port=8080)