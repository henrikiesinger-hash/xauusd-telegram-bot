import logging
logging.basicConfig(level=logging.INFO)

from flask import Flask
from data import get_candles
from strategy import generate_signal
import strategy

strategy.BACKTEST_MODE = True

app = Flask(__name__)

@app.route('/')
def home():
    return 'BACKTEST MODE'


# ==============================
# AGGREGATION
# ==============================

def aggregate_candles(data, factor):
    agg = {'open': [], 'high': [], 'low': [], 'close': []}
    total = len(data['close'])

    for i in range(0, total - factor + 1, factor):
        agg['open'].append(data['open'][i])
        agg['high'].append(max(data['high'][i:i + factor]))
        agg['low'].append(min(data['low'][i:i + factor]))
        agg['close'].append(data['close'][i + factor - 1])

    return agg


# ==============================
# MOCK HTF
# ==============================

_htf_store = {'m15': None, 'h1': None}

def mock_get_candles(interval, limit=200):
    if '15' in interval:
        return _htf_store['m15']
    if '1h' in interval or '60' in interval:
        return _htf_store['h1']
    return None


# ==============================
# TRADE SIMULATION
# ==============================

def simulate_trade(data, entry_index, direction, entry, sl, tp):
    for i in range(entry_index + 1, len(data['close'])):
        high = data['high'][i]
        low = data['low'][i]

        if direction == 'BUY':
            if low <= sl:
                return 'LOSS', round(-(entry - sl), 2)
            if high >= tp:
                return 'WIN', round(tp - entry, 2)

        else:
            if high >= sl:
                return 'LOSS', round(-(sl - entry), 2)
            if low <= tp:
                return 'WIN', round(entry - tp, 2)

    return 'NO RESULT', 0.0


# ==============================
# BACKTEST
# ==============================

def run_backtest():
    global _htf_store

    logging.info('START BACKTEST')

    data = get_candles('5min', 10000)

    if not data:
        logging.error('No data')
        return

    total_candles = len(data['close'])
    logging.info('M5 Candles: %s', total_candles)

    full_m15 = aggregate_candles(data, 3)
    full_h1 = aggregate_candles(data, 12)

    logging.info('M15: %s | H1: %s',
                 len(full_m15['close']), len(full_h1['close']))

    if len(full_h1['close']) < 210:
        logging.error('Not enough H1 candles')
        return

    import strategy as strat_module
    original_get_candles = strat_module.get_candles
    strat_module.get_candles = mock_get_candles

    wins = 0
    losses = 0
    no_result = 0
    total = 0
    total_pnl = 0.0

    start_index = 5000

    for i in range(start_index, total_candles):

        sub_all = {
            'open': data['open'][:i],
            'high': data['high'][:i],
            'low': data['low'][:i],
            'close': data['close'][:i],
        }

        m15 = aggregate_candles(sub_all, 3)
        h1 = aggregate_candles(sub_all, 12)

        if len(h1['close']) < 200 or len(m15['close']) < 50:
            continue

        _htf_store['m15'] = m15
        _htf_store['h1'] = h1

        signal = generate_signal(sub_all, candle_index=i)

        if signal:
            total += 1

            result, pnl = simulate_trade(
                data,
                i,
                signal['direction'],
                signal['entry'],
                signal['sl'],
                signal['tp'],
            )

            total_pnl += pnl

            logging.info(
                'TRADE %s: %s @ %.2f | SL:%.2f TP:%.2f RR:%s | $%.2f | Score:%s %s | %s ($%.2f)',
                total,
                signal['direction'],
                signal['entry'],
                signal['sl'],
                signal['tp'],
                signal.get('rr', '?'),
                signal.get('sl_dist', 0),
                signal.get('score', '?'),
                signal.get('confidence', ''),
                result,
                pnl
            )

            if result == 'WIN':
                wins += 1
            elif result == 'LOSS':
                losses += 1
            else:
                no_result += 1

    # Restore original
    strat_module.get_candles = original_get_candles

    logging.info('====================================')
    logging.info('BACKTEST RESULTS')
    logging.info('====================================')
    logging.info('Total Trades: %s', total)
    logging.info('Wins: %s', wins)
    logging.info('Losses: %s', losses)
    logging.info('No Result: %s', no_result)

    resolved = wins + losses

    if resolved > 0:
        winrate = (wins / resolved) * 100
        logging.info('Winrate: %.1f%% (%s/%s)', winrate, wins, resolved)
        logging.info('Total PnL: $%.2f', total_pnl)
        logging.info('Avg per trade: $%.2f', total_pnl / resolved)

    logging.info('====================================')


# ==============================
# RUN
# ==============================

run_backtest()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)