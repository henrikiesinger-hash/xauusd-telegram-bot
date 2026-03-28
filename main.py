import logging
logging.basicConfig(level=logging.INFO)

from flask import Flask
from data import get_candles
from strategy import generate_signal
import strategy

strategy.BACKTEST_MODE = True

app = Flask(__name__)

@app.route("/")
def home():
    return "BACKTEST MODE"

def simulate_trade(data, entry_index, direction, entry, sl, tp):

    for i in range(entry_index + 1, len(data["close"])):

        high = data["high"][i]
        low = data["low"][i]

        if direction == "BUY":
            if low <= sl:
                return "LOSS"
            if high >= tp:
                return "WIN"

        else:
            if high >= sl:
                return "LOSS"
            if low <= tp:
                return "WIN"

    return "NO RESULT"

def run_backtest():

    logging.info("🔥 START BACKTEST")

    data = get_candles("5min")

    wins = 0
    losses = 0
    total = 0

    for i in range(50, len(data["close"])):

        sub_data = {
            "open": data["open"][:i],
            "high": data["high"][:i],
            "low": data["low"][:i],
            "close": data["close"][:i]
        }

        signal = generate_signal(sub_data, candle_index=i)

        if signal:
            total += 1

            result = simulate_trade(
                data,
                i,
                signal["direction"],
                signal["entry"],
                signal["sl"],
                signal["tp"]
            )

            logging.info(f"{signal} → {result}")

            if result == "WIN":
                wins += 1
            elif result == "LOSS":
                losses += 1

    logging.info(f"Trades: {total}")
    logging.info(f"Wins: {wins}")
    logging.info(f"Losses: {losses}")

    if total > 0:
        logging.info(f"Winrate: {round((wins/total)*100,2)}%")

run_backtest()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)