#!/usr/bin/env python3
'''
Comparative backtest: OLD strategy vs NEW strategy (v2 fixes).
Runs both versions over the same data and prints a comparison table.
Uses synthetic data when TWELVE_DATA_KEY is not available.
'''

import logging
import os
import random
import math

logging.basicConfig(level=logging.INFO, format='%(message)s')

from flask import Flask
import strategy

strategy.BACKTEST_MODE = True

app = Flask(__name__)


@app.route('/')
def home():
    return 'BACKTEST COMPARE MODE'


# ==============================
# SYNTHETIC DATA GENERATOR
# ==============================

def generate_synthetic_m5(num_candles=5000, seed=42):
    '''Generate realistic XAUUSD M5 candles with trends, ranges, and swings.'''
    random.seed(seed)

    price = 2350.0
    opens, highs, lows, closes = [], [], [], []

    # Create alternating trend/range regimes
    regime_length = 0
    regime_type = 'trend_up'
    trend_bias = 0.15

    for i in range(num_candles):
        if regime_length <= 0:
            regime_type = random.choice([
                'trend_up', 'trend_down', 'range', 'volatile_up', 'volatile_down'
            ])
            regime_length = random.randint(80, 300)

            if regime_type == 'trend_up':
                trend_bias = random.uniform(0.08, 0.25)
            elif regime_type == 'trend_down':
                trend_bias = random.uniform(-0.25, -0.08)
            elif regime_type == 'range':
                trend_bias = random.uniform(-0.03, 0.03)
            elif regime_type == 'volatile_up':
                trend_bias = random.uniform(0.1, 0.3)
            elif regime_type == 'volatile_down':
                trend_bias = random.uniform(-0.3, -0.1)

        regime_length -= 1

        # Base volatility depends on regime
        if 'volatile' in regime_type:
            vol = random.uniform(1.5, 4.0)
        elif regime_type == 'range':
            vol = random.uniform(0.5, 1.5)
        else:
            vol = random.uniform(0.8, 2.5)

        # Generate OHLC
        o = price
        change = trend_bias + random.gauss(0, vol)
        c = o + change

        # Wicks
        wick_up = abs(random.gauss(0, vol * 0.5))
        wick_down = abs(random.gauss(0, vol * 0.5))

        h = max(o, c) + wick_up
        l = min(o, c) - wick_down

        opens.append(round(o, 2))
        highs.append(round(h, 2))
        lows.append(round(l, 2))
        closes.append(round(c, 2))

        price = c

    return {
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
    }


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
                duration_candles = i - entry_index
                return 'LOSS', round(-(entry - sl), 2), duration_candles
            if high >= tp:
                duration_candles = i - entry_index
                return 'WIN', round(tp - entry, 2), duration_candles
        else:
            if high >= sl:
                duration_candles = i - entry_index
                return 'LOSS', round(-(sl - entry), 2), duration_candles
            if low <= tp:
                duration_candles = i - entry_index
                return 'WIN', round(entry - tp, 2), duration_candles

    return 'NO RESULT', 0.0, 0


# ==============================
# OLD STRATEGY SL/TP (pre-fix)
# ==============================

def old_calculate_sl_tp(direction, price, highs, lows, closes):
    '''Original SL/TP: ATR-based, clamped 8-12, TP = max(swing, 2x SL).'''
    atr_val = strategy.calculate_atr(highs, lows, closes)

    if direction == 'bullish':
        swing_lows = strategy.find_swing_lows(lows, 3, 3)
        structure_sl = swing_lows[-1][1] if swing_lows else min(lows[-15:])
        sl = structure_sl - atr_val * 0.3
        sl_dist = price - sl
    else:
        swing_highs = strategy.find_swing_highs(highs, 3, 3)
        structure_sl = swing_highs[-1][1] if swing_highs else max(highs[-15:])
        sl = structure_sl + atr_val * 0.3
        sl_dist = sl - price

    sl_dist = max(8.0, min(12.0, sl_dist))
    sl = price - sl_dist if direction == 'bullish' else price + sl_dist

    if direction == 'bullish':
        targets = [s[1] for s in strategy.find_swing_highs(highs, 3, 3) if s[1] > price]
        tp_dist = min(targets) - price if targets else sl_dist * 3
    else:
        targets = [s[1] for s in strategy.find_swing_lows(lows, 3, 3) if s[1] < price]
        tp_dist = price - max(targets) if targets else sl_dist * 3

    if tp_dist < sl_dist * 2:
        tp_dist = sl_dist * 2

    tp = price + tp_dist if direction == 'bullish' else price - tp_dist
    rr = round(tp_dist / sl_dist, 1)

    return round(sl, 2), round(tp, 2), round(sl_dist, 2), rr


# ==============================
# OLD SIGNAL GENERATOR (pre-fix logic)
# ==============================

def generate_signal_old(data_m5, m15, h1, candle_index=0):
    '''Old strategy: no entry confirmation, full OB zone, old SL/TP, no RR filter.'''
    from indicators import rsi

    if strategy.is_in_cooldown_backtest(candle_index):
        return None

    c5 = data_m5['close']
    h5 = data_m5['high']
    l5 = data_m5['low']

    c15 = m15['close']
    h15 = m15['high']
    l15 = m15['low']
    o15 = m15['open']

    c1 = h1['close']
    price = c5[-1]

    trend = strategy.trend_direction(c1)
    if trend is None:
        return None

    if strategy.is_choppy(c1):
        return None

    direction = trend
    rsi_val = rsi(c5)

    if direction == 'bullish' and rsi_val > 60:
        return None
    if direction == 'bearish' and rsi_val < 40:
        return None

    ob_low, ob_high = strategy.detect_orderblock(h15, l15, o15, c15, direction)
    if ob_low is None:
        return None

    # OLD: full OB zone check
    if not (ob_low <= price <= ob_high):
        return None

    structure_val, struct_str = strategy.market_structure(h15, l15)
    bos = strategy.detect_bos(h15, l15, c15)
    sweep = strategy.liquidity_sweep(h5, l5, c5)
    zone = strategy.premium_discount(h15, l15, price)

    score = strategy.calculate_score(
        direction, trend, structure_val, struct_str, bos,
        True, sweep, zone, rsi_val
    )

    if score < strategy.SCORE_THRESHOLD:
        return None

    # OLD: no entry confirmation, old SL/TP
    sl, tp, sl_dist, rr = old_calculate_sl_tp(direction, price, h5, l5, c5)

    strategy.record_signal_backtest(candle_index)

    if score >= 8.5:
        confidence = 'SNIPER'
    elif score >= 7.0:
        confidence = 'HIGH'
    else:
        confidence = 'MODERATE'

    return {
        'direction': 'BUY' if direction == 'bullish' else 'SELL',
        'entry': round(price, 2),
        'sl': sl,
        'tp': tp,
        'rr': rr,
        'sl_dist': sl_dist,
        'score': score,
        'confidence': confidence,
    }


# ==============================
# NEW SIGNAL GENERATOR (with fix tracking)
# ==============================

def generate_signal_new(data_m5, m15, h1, candle_index=0):
    '''New strategy with all 4 fixes. Returns (signal, filter_reason).'''
    from indicators import rsi

    if strategy.is_in_cooldown_backtest(candle_index):
        return None, None

    c5 = data_m5['close']
    h5 = data_m5['high']
    l5 = data_m5['low']
    o5 = data_m5['open']

    c15 = m15['close']
    h15 = m15['high']
    l15 = m15['low']
    o15 = m15['open']

    c1 = h1['close']
    price = c5[-1]

    trend = strategy.trend_direction(c1)
    if trend is None:
        return None, None

    if strategy.is_choppy(c1):
        return None, None

    direction = trend
    rsi_val = rsi(c5)

    if direction == 'bullish' and rsi_val > 60:
        return None, None
    if direction == 'bearish' and rsi_val < 40:
        return None, None

    ob_low, ob_high = strategy.detect_orderblock(h15, l15, o15, c15, direction)
    if ob_low is None:
        return None, None

    # Fix 2: OB Midpoint
    ob_mid = (ob_low + ob_high) / 2
    if direction == 'bullish' and price > ob_mid:
        return None, 'ob_midpoint'
    if direction == 'bearish' and price < ob_mid:
        return None, 'ob_midpoint'

    structure_val, struct_str = strategy.market_structure(h15, l15)
    bos = strategy.detect_bos(h15, l15, c15)
    sweep = strategy.liquidity_sweep(h5, l5, c5)
    zone = strategy.premium_discount(h15, l15, price)

    score = strategy.calculate_score(
        direction, trend, structure_val, struct_str, bos,
        True, sweep, zone, rsi_val
    )

    if score < strategy.SCORE_THRESHOLD:
        return None, None

    # Fix 1: Entry confirmation
    if direction == 'bullish' and c5[-1] <= o5[-1]:
        return None, 'entry_confirm'
    if direction == 'bearish' and c5[-1] >= o5[-1]:
        return None, 'entry_confirm'

    # Fix 3+4: Structure-based SL/TP
    sl, tp, sl_dist, rr, swing_sl, swing_tp = strategy.calculate_sl_tp(
        direction, price, h5, l5, c5, h1['high'], h1['low']
    )

    # Fix 4: RR filter
    if rr < 1.5:
        return None, 'rr_filter'

    strategy.record_signal_backtest(candle_index)

    if score >= 8.5:
        confidence = 'SNIPER'
    elif score >= 7.0:
        confidence = 'HIGH'
    else:
        confidence = 'MODERATE'

    return {
        'direction': 'BUY' if direction == 'bullish' else 'SELL',
        'entry': round(price, 2),
        'sl': sl,
        'tp': tp,
        'rr': rr,
        'sl_dist': sl_dist,
        'score': score,
        'confidence': confidence,
        'swing_sl': round(swing_sl, 2) if swing_sl is not None else None,
        'swing_tp': round(swing_tp, 2) if swing_tp is not None else None,
    }, None


# ==============================
# BACKTEST RUNNER
# ==============================

def run_backtest():
    global _htf_store

    logging.info('=' * 60)
    logging.info('COMPARATIVE BACKTEST: OLD vs NEW Strategy')
    logging.info('=' * 60)

    # Try API first, fall back to synthetic data
    api_key = os.environ.get('TWELVE_DATA_KEY', '')
    data = None
    if api_key:
        from data import get_candles as api_get_candles
        data = api_get_candles('5min', 5000)

    if not data:
        logging.info('No API key or data — using synthetic XAUUSD data')
        data = generate_synthetic_m5(5000, seed=42)

    total_candles = len(data['close'])
    logging.info('M5 Candles loaded: %s', total_candles)

    # Pre-compute full HTF
    full_m15 = aggregate_candles(data, 3)
    full_h1 = aggregate_candles(data, 12)
    logging.info('M15: %s | H1: %s', len(full_m15['close']), len(full_h1['close']))

    if len(full_h1['close']) < 210:
        logging.error('Not enough H1 candles for backtest')
        return

    # Patch get_candles for strategy module
    import strategy as strat_module
    original_get_candles = strat_module.get_candles
    strat_module.get_candles = mock_get_candles

    # ---- OLD STRATEGY RUN ----
    old_results = {'wins': 0, 'losses': 0, 'no_result': 0, 'total_pnl': 0.0,
                   'trades': [], 'fast_stops': 0}

    strategy._last_signal_candle = -999
    start_index = 2500

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

        signal = generate_signal_old(sub_all, m15, h1, candle_index=i)
        if signal:
            result, pnl, dur_candles = simulate_trade(
                data, i, signal['direction'], signal['entry'],
                signal['sl'], signal['tp']
            )
            duration_h = dur_candles * 5 / 60

            old_results['total_pnl'] += pnl
            old_results['trades'].append({
                'result': result, 'pnl': pnl, 'rr': signal['rr'],
                'duration_h': duration_h,
            })

            if result == 'WIN':
                old_results['wins'] += 1
            elif result == 'LOSS':
                old_results['losses'] += 1
                if duration_h < 0.1:
                    old_results['fast_stops'] += 1
            else:
                old_results['no_result'] += 1

    # ---- NEW STRATEGY RUN ----
    new_results = {'wins': 0, 'losses': 0, 'no_result': 0, 'total_pnl': 0.0,
                   'trades': [], 'fast_stops': 0}
    filter_counts = {'entry_confirm': 0, 'ob_midpoint': 0, 'rr_filter': 0}

    strategy._last_signal_candle = -999
    strategy._used_ob = None

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

        signal, filter_reason = generate_signal_new(sub_all, m15, h1, candle_index=i)

        if filter_reason:
            filter_counts[filter_reason] += 1

        if signal:
            result, pnl, dur_candles = simulate_trade(
                data, i, signal['direction'], signal['entry'],
                signal['sl'], signal['tp']
            )
            duration_h = dur_candles * 5 / 60

            new_results['total_pnl'] += pnl
            new_results['trades'].append({
                'result': result, 'pnl': pnl, 'rr': signal['rr'],
                'duration_h': duration_h,
            })

            if result == 'WIN':
                new_results['wins'] += 1
            elif result == 'LOSS':
                new_results['losses'] += 1
                if duration_h < 0.1:
                    new_results['fast_stops'] += 1
            else:
                new_results['no_result'] += 1

    # Restore
    strat_module.get_candles = original_get_candles

    # ==============================
    # RESULTS TABLE
    # ==============================

    def calc_stats(r):
        total = r['wins'] + r['losses']
        winrate = round((r['wins'] / total) * 100, 1) if total > 0 else 0
        rr_vals = [t['rr'] for t in r['trades'] if t['result'] in ('WIN', 'LOSS')]
        avg_rr = round(sum(rr_vals) / len(rr_vals), 1) if rr_vals else 0
        avg_pnl = round(r['total_pnl'] / total, 2) if total > 0 else 0
        fast_rate = round((r['fast_stops'] / total) * 100, 1) if total > 0 else 0
        return total, winrate, avg_rr, avg_pnl, fast_rate

    old_total, old_wr, old_avg_rr, old_avg_pnl, old_fast = calc_stats(old_results)
    new_total, new_wr, new_avg_rr, new_avg_pnl, new_fast = calc_stats(new_results)

    logging.info('')
    logging.info('=' * 60)
    logging.info('RESULTS COMPARISON')
    logging.info('=' * 60)
    logging.info('')
    logging.info('%-25s %12s %12s', 'Metric', 'OLD', 'NEW')
    logging.info('-' * 50)
    logging.info('%-25s %12d %12d', 'Total Trades', old_total, new_total)
    logging.info('%-25s %12d %12d', 'Wins', old_results['wins'], new_results['wins'])
    logging.info('%-25s %12d %12d', 'Losses', old_results['losses'], new_results['losses'])
    logging.info('%-25s %11.1f%% %11.1f%%', 'Winrate', old_wr, new_wr)
    logging.info('%-25s %11.2f %11.2f', 'Total PnL ($)', old_results['total_pnl'], new_results['total_pnl'])
    logging.info('%-25s %11.2f %11.2f', 'Avg PnL/Trade ($)', old_avg_pnl, new_avg_pnl)
    logging.info('%-25s %11.1f %11.1f', 'Avg RR', old_avg_rr, new_avg_rr)
    logging.info('%-25s %12d %12d', 'Fast Stops (<0.1h)', old_results['fast_stops'], new_results['fast_stops'])
    logging.info('%-25s %11.1f%% %11.1f%%', 'Fast Stop Rate', old_fast, new_fast)

    logging.info('')
    logging.info('=' * 60)
    logging.info('FILTER BREAKDOWN (trades blocked by new fixes)')
    logging.info('=' * 60)
    logging.info('%-30s %10s', 'Filter', 'Blocked')
    logging.info('-' * 42)
    logging.info('%-30s %10d', 'Entry Confirmation (Fix 1)', filter_counts['entry_confirm'])
    logging.info('%-30s %10d', 'OB Midpoint (Fix 2)', filter_counts['ob_midpoint'])
    logging.info('%-30s %10d', 'RR < 1.5 (Fix 4)', filter_counts['rr_filter'])
    logging.info('%-30s %10d', 'TOTAL FILTERED',
                 sum(filter_counts.values()))

    logging.info('')
    logging.info('Trades removed: %d -> %d (-%d)',
                 old_total, new_total, old_total - new_total)
    logging.info('=' * 60)


# ==============================
# RUN
# ==============================

run_backtest()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
