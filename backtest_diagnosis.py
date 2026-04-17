"""
XAUUSD Filter Funnel Diagnosis - identifies which filter rejects the most candles.

Config locked to current LIVE configuration (V6 OB Midpoint):
  chop_filter:         False
  ob_midpoint:         True
  entry_confirmation:  False
  structural_sl_tp:    False
  SCORE_THRESHOLD:     6.0

For every M5 candle inside the trading window (London 7 UTC -> NY 21 UTC, no
weekend, no Friday >= 19 UTC, no active trade) the gates are checked in order.
The FIRST failed gate's counter is incremented. Exactly one counter per candle.

Data loading is identical to backtest_variants.py (TwelveData).
"""

import os
import sys
import time
import requests
import pandas as pd

# ==============================
# CONFIG
# ==============================

TWELVE_DATA_KEY = os.environ.get('TWELVE_DATA_KEY')
if not TWELVE_DATA_KEY:
    print('FEHLER: TWELVE_DATA_KEY nicht gesetzt')
    sys.exit(1)

SYMBOL = 'XAU/USD'
BACKTEST_DAYS = 60

LIVE_CONFIG = {
    'chop_filter': False,
    'ob_midpoint': True,
    'entry_confirmation': False,
    'structural_sl_tp': False,
}

SCORE_THRESHOLD = 6.0
COOLDOWN_AFTER_WIN = 24
COOLDOWN_AFTER_LOSS = 48
LONDON_OPEN_UTC = 7
NY_CLOSE_UTC = 21
FRIDAY_STOP_UTC = 19

GATE_NAMES = [
    'no_trend',
    'cooldown_active',
    'rsi_blocked',
    'no_orderblock',
    'ob_midpoint_failed',
    'ob_reused',
    'score_below_threshold',
    'signal_generated',
]

counters = {name: 0 for name in GATE_NAMES}

# ==============================
# DATA LOADING (TwelveData) - 1:1 aus backtest_variants.py
# ==============================

def fetch_twelvedata(interval, outputsize):
    url = 'https://api.twelvedata.com/time_series'
    params = {
        'symbol': SYMBOL,
        'interval': interval,
        'outputsize': outputsize,
        'apikey': TWELVE_DATA_KEY,
        'format': 'JSON',
        'order': 'ASC',
    }

    resp = requests.get(url, params=params, timeout=30)
    data = resp.json()

    if data.get('status') == 'error':
        print(f'TwelveData Error ({interval}): {data.get("message")}')
        return None

    if 'values' not in data:
        print(f'TwelveData: Keine Values fuer {interval}')
        return None

    df = pd.DataFrame(data['values'])
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.sort_values('datetime').reset_index(drop=True)

    for col in ['open', 'high', 'low', 'close']:
        df[col] = df[col].astype(float)

    return df


def load_data():
    print(f'Lade {SYMBOL} Daten von TwelveData ({BACKTEST_DAYS} Tage)...')

    m5 = fetch_twelvedata('5min', 5000)
    time.sleep(1)
    m15 = fetch_twelvedata('15min', 2000)
    time.sleep(1)
    h1 = fetch_twelvedata('1h', 1000)

    if m5 is None or m15 is None or h1 is None:
        print('Daten konnten nicht geladen werden')
        sys.exit(1)

    print(f'M5:  {len(m5)} candles von {m5.iloc[0]["datetime"]} bis {m5.iloc[-1]["datetime"]}')
    print(f'M15: {len(m15)} candles')
    print(f'H1:  {len(h1)} candles')
    print()

    return m5, m15, h1


def df_to_dict(df, end_idx=None):
    if end_idx is not None:
        df = df.iloc[:end_idx]
    return {
        'open': df['open'].values.tolist(),
        'high': df['high'].values.tolist(),
        'low': df['low'].values.tolist(),
        'close': df['close'].values.tolist(),
    }

# ==============================
# INDICATORS
# ==============================

def ema(values, period):
    if len(values) < period:
        return values[-1] if values else 0
    k = 2 / (period + 1)
    ema_val = sum(values[:period]) / period
    for v in values[period:]:
        ema_val = v * k + ema_val * (1 - k)
    return ema_val


def rsi(values, period=14):
    if len(values) < period + 1:
        return 50
    gains, losses = [], []
    for i in range(-period, 0):
        change = values[i] - values[i-1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return 3.0
    tr_list = []
    for i in range(-period, 0):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        tr_list.append(tr)
    return sum(tr_list) / len(tr_list)

# ==============================
# SWING POINTS
# ==============================

def find_swing_highs(highs, left=5, right=5):
    swings = []
    for i in range(left, len(highs) - right):
        window = highs[i-left:i+right+1]
        if highs[i] == max(window) and len(set(window)) > 1:
            swings.append((i, highs[i]))
    return swings


def find_swing_lows(lows, left=5, right=5):
    swings = []
    for i in range(left, len(lows) - right):
        window = lows[i-left:i+right+1]
        if lows[i] == min(window) and len(set(window)) > 1:
            swings.append((i, lows[i]))
    return swings

# ==============================
# STRATEGY LOGIC
# ==============================

def trend_direction(closes):
    if len(closes) < 200:
        return None
    e50 = ema(closes, 50)
    e200 = ema(closes, 200)
    if e50 > e200:
        return 'bullish'
    if e50 < e200:
        return 'bearish'
    return None


def market_structure(highs, lows):
    sh = find_swing_highs(highs)
    sl = find_swing_lows(lows)
    if len(sh) < 2 or len(sl) < 2:
        return 'ranging', 0.0
    hh = sh[-1][1] > sh[-2][1]
    hl = sl[-1][1] > sl[-2][1]
    lh = sh[-1][1] < sh[-2][1]
    ll = sl[-1][1] < sl[-2][1]
    if hh and hl:
        return 'bullish', 1.0
    if lh and ll:
        return 'bearish', 1.0
    if hh or hl:
        return 'bullish', 0.5
    if lh or ll:
        return 'bearish', 0.5
    return 'ranging', 0.0


def detect_bos(highs, lows, closes):
    sh = find_swing_highs(highs)
    sl = find_swing_lows(lows)
    if not sh or not sl:
        return None
    if closes[-1] > sh[-1][1]:
        return 'bullish'
    if closes[-1] < sl[-1][1]:
        return 'bearish'
    return None


def detect_orderblock(highs, lows, opens, closes, direction):
    if len(closes) < 22:
        return None, None
    best = None
    for i in range(len(closes) - 20, len(closes) - 2):
        body = abs(opens[i] - closes[i])
        if body < 0.01:
            continue
        if direction == 'bullish' and closes[i] < opens[i]:
            future_high = max(highs[i+1:i+4])
            displacement = future_high - lows[i]
            if displacement > body * 2:
                mitigated = any(closes[j] < lows[i] for j in range(i+1, len(closes)))
                if not mitigated:
                    best = (lows[i], highs[i])
        if direction == 'bearish' and closes[i] > opens[i]:
            future_low = min(lows[i+1:i+4])
            displacement = highs[i] - future_low
            if displacement > body * 2:
                mitigated = any(closes[j] > highs[i] for j in range(i+1, len(closes)))
                if not mitigated:
                    best = (lows[i], highs[i])
    return best if best else (None, None)


def liquidity_sweep(highs, lows, closes):
    if len(highs) < 10:
        return None
    prev_high = max(highs[-10:-1])
    prev_low = min(lows[-10:-1])
    if highs[-1] > prev_high and closes[-1] < prev_high:
        return 'bearish'
    if lows[-1] < prev_low and closes[-1] > prev_low:
        return 'bullish'
    return None


def premium_discount(highs, lows, price):
    hi = max(highs[-50:])
    lo = min(lows[-50:])
    if hi == lo:
        return 'mid'
    pct = (price - lo) / (hi - lo)
    if pct > 0.65:
        return 'premium'
    if pct < 0.35:
        return 'discount'
    return 'mid'


def calculate_score(direction, trend, structure, struct_str, bos, at_ob, sweep, zone, rsi_val):
    score = 0.0
    if trend == direction:
        score += 2.0
    else:
        score -= 1.0
    if structure == direction:
        score += 1.0 + struct_str
    if bos == direction:
        score += 2.0
    if at_ob:
        score += 1.5
    if sweep == direction:
        score += 0.5
    if direction == 'bullish' and zone == 'discount':
        score += 0.5
    if direction == 'bearish' and zone == 'premium':
        score += 0.5
    if direction == 'bullish' and 30 < rsi_val < 55:
        score += 0.5
    if direction == 'bearish' and 45 < rsi_val < 70:
        score += 0.5
    return round(score, 1)


def calculate_sl_tp_simple(direction, price, highs, lows, closes):
    atr_val = calculate_atr(highs, lows, closes)
    if direction == 'bullish':
        swing_lows = find_swing_lows(lows, 3, 3)
        structure_sl = swing_lows[-1][1] if swing_lows else min(lows[-15:])
        sl_dist = price - (structure_sl - atr_val * 0.3)
    else:
        swing_highs = find_swing_highs(highs, 3, 3)
        structure_sl = swing_highs[-1][1] if swing_highs else max(highs[-15:])
        sl_dist = (structure_sl + atr_val * 0.3) - price
    sl_dist = max(8.0, min(12.0, sl_dist))
    sl = price - sl_dist if direction == 'bullish' else price + sl_dist
    tp_dist = sl_dist * 2
    tp = price + tp_dist if direction == 'bullish' else price - tp_dist
    return sl, tp, sl_dist, 2.0

# ==============================
# SIGNAL GENERATOR WITH FILTER FUNNEL COUNTERS
# ==============================

def generate_signal_diag(data_m5, data_m15, data_h1, candle_index,
                         last_signal_idx, used_ob, last_result):
    """
    Mirrors generate_signal from backtest_variants.py but increments exactly
    ONE gate counter per call and returns None on any reject. Gates are
    ordered per task:
      1 no_trend
      2 cooldown_active
      3 rsi_blocked
      4 no_orderblock
      5 ob_midpoint_failed
      6 ob_reused
      7 score_below_threshold
      8 signal_generated
    chop_filter / entry_confirmation / structural_sl_tp are disabled in LIVE_CONFIG
    so they are NOT counted.
    """
    c5 = data_m5['close']
    h5 = data_m5['high']
    l5 = data_m5['low']

    if len(c5) < 200 or len(data_m15['close']) < 50 or len(data_h1['close']) < 200:
        counters['no_trend'] += 1
        return None, used_ob, last_signal_idx

    c1 = data_h1['close']
    c15 = data_m15['close']
    h15 = data_m15['high']
    l15 = data_m15['low']
    o15 = data_m15['open']
    price = c5[-1]

    # Gate 1 - trend direction
    trend = trend_direction(c1)
    if trend is None:
        counters['no_trend'] += 1
        return None, used_ob, last_signal_idx

    # Gate 2 - cooldown
    cooldown = COOLDOWN_AFTER_LOSS if last_result == 'LOSS' else COOLDOWN_AFTER_WIN
    if candle_index - last_signal_idx < cooldown:
        counters['cooldown_active'] += 1
        return None, used_ob, last_signal_idx

    # Gate 3 - RSI
    direction = trend
    rsi_val = rsi(c5)
    if direction == 'bullish' and rsi_val > 60:
        counters['rsi_blocked'] += 1
        return None, used_ob, last_signal_idx
    if direction == 'bearish' and rsi_val < 40:
        counters['rsi_blocked'] += 1
        return None, used_ob, last_signal_idx

    # Gate 4 - orderblock presence
    ob_low, ob_high = detect_orderblock(h15, l15, o15, c15, direction)
    if ob_low is None:
        counters['no_orderblock'] += 1
        return None, used_ob, last_signal_idx

    # Gate 5 - OB midpoint (LIVE uses ob_midpoint=True)
    mid = (ob_low + ob_high) / 2
    if direction == 'bullish' and price > mid:
        counters['ob_midpoint_failed'] += 1
        return None, used_ob, last_signal_idx
    if direction == 'bearish' and price < mid:
        counters['ob_midpoint_failed'] += 1
        return None, used_ob, last_signal_idx

    # Gate 6 - OB reuse
    ob_id = (round(ob_low, 0), round(ob_high, 0))
    if ob_id == used_ob:
        counters['ob_reused'] += 1
        return None, used_ob, last_signal_idx

    # Gate 7 - score
    sweep = liquidity_sweep(h5, l5, c5)
    zone = premium_discount(h15, l15, price)
    structure, struct_str = market_structure(h15, l15)
    bos = detect_bos(h15, l15, c15)
    score = calculate_score(direction, trend, structure, struct_str, bos,
                            True, sweep, zone, rsi_val)
    if score < SCORE_THRESHOLD:
        counters['score_below_threshold'] += 1
        return None, used_ob, last_signal_idx

    # Gate 8 - signal passes
    sl, tp, sl_dist, rr = calculate_sl_tp_simple(direction, price, h5, l5, c5)
    signal = {
        'direction': 'BUY' if direction == 'bullish' else 'SELL',
        'entry': round(price, 2),
        'sl': round(sl, 2),
        'tp': round(tp, 2),
        'sl_dist': round(sl_dist, 2),
        'tp_dist': round(abs(tp - price), 2),
        'rr': rr,
        'score': score,
    }
    counters['signal_generated'] += 1
    return signal, ob_id, candle_index

# ==============================
# BACKTEST ENGINE (diagnosis variant)
# ==============================

def map_htf_index(m5_time, htf_df):
    for i in range(len(htf_df)):
        if htf_df.iloc[i]['datetime'] > m5_time:
            return max(0, i - 1)
    return len(htf_df) - 1


def run_diagnosis(m5, m15, h1):
    active_trade = None
    last_signal_idx = -1000
    used_ob = None
    last_result = 'WIN'

    total_checked = 0

    for i in range(200, len(m5)):
        current_time = m5.iloc[i]['datetime']
        hour = current_time.hour
        dow = current_time.dayofweek  # Mon=0 ... Sun=6

        # Session filter
        if hour < LONDON_OPEN_UTC or hour >= NY_CLOSE_UTC:
            continue
        # Weekend
        if dow >= 5:
            continue
        # Friday after 19 UTC (FTMO gap rule)
        if dow == 4 and hour >= FRIDAY_STOP_UTC:
            continue

        # Active trade management
        if active_trade is not None:
            high = m5.iloc[i]['high']
            low = m5.iloc[i]['low']
            closed = False

            if active_trade['direction'] == 'BUY':
                if low <= active_trade['sl']:
                    last_result = 'LOSS'
                    closed = True
                elif high >= active_trade['tp']:
                    last_result = 'WIN'
                    closed = True
            else:
                if high >= active_trade['sl']:
                    last_result = 'LOSS'
                    closed = True
                elif low <= active_trade['tp']:
                    last_result = 'WIN'
                    closed = True

            if closed:
                active_trade = None
            elif i - active_trade['open_idx'] > 288:
                active_trade = None

        if active_trade is not None:
            continue

        # Map HTF indices
        m15_idx = map_htf_index(current_time, m15)
        h1_idx = map_htf_index(current_time, h1)

        if m15_idx < 50 or h1_idx < 200:
            # Not enough HTF data -> treat as no_trend reject
            counters['no_trend'] += 1
            total_checked += 1
            continue

        data_m5 = df_to_dict(m5, i + 1)
        data_m15 = df_to_dict(m15, m15_idx + 1)
        data_h1 = df_to_dict(h1, h1_idx + 1)

        signal, new_used_ob, new_last_signal_idx = generate_signal_diag(
            data_m5, data_m15, data_h1, i,
            last_signal_idx, used_ob, last_result
        )

        total_checked += 1

        if signal:
            active_trade = {**signal, 'open_idx': i}
            used_ob = new_used_ob
            last_signal_idx = i

    return total_checked

# ==============================
# REPORT
# ==============================

def print_report(total_checked):
    print('=' * 70)
    print('FILTER FUNNEL ANALYSIS')
    print('=' * 70)
    print(f'Total candles checked: {total_checked}')
    print()

    labels = {
        'no_trend':              'Gate 1 - no_trend:             ',
        'cooldown_active':       'Gate 2 - cooldown_active:      ',
        'rsi_blocked':           'Gate 3 - rsi_blocked:          ',
        'no_orderblock':         'Gate 4 - no_orderblock:        ',
        'ob_midpoint_failed':    'Gate 5 - ob_midpoint_failed:   ',
        'ob_reused':             'Gate 6 - ob_reused:            ',
        'score_below_threshold': 'Gate 7 - score_below_threshold:',
        'signal_generated':      'Gate 8 - signal_generated:     ',
    }

    for name in GATE_NAMES:
        n = counters[name]
        pct = (n / total_checked * 100) if total_checked else 0.0
        print(f'{labels[name]} {n:6d} ({pct:5.1f}%)')
    print()

    total_sum = sum(counters.values())
    match = 'OK' if total_sum == total_checked else 'MISMATCH'
    print(f'Sum check: {total_sum} (must == {total_checked})  [{match}]')
    print()

    print('=' * 70)
    print('BOTTLENECK RANKING')
    print('=' * 70)
    ranked = sorted(
        [(n, counters[n]) for n in GATE_NAMES if n != 'signal_generated'],
        key=lambda x: x[1],
        reverse=True,
    )
    for rank, (name, n) in enumerate(ranked, 1):
        pct = (n / total_checked * 100) if total_checked else 0.0
        print(f'{rank}. {name}: {pct:.1f}% of candles ({n})')
    print()

    print('=' * 70)
    print('RECOMMENDATION')
    print('=' * 70)
    top3 = ranked[:3]
    print('Top-3 Bottlenecks identifiziert. Gezielte Lockerung empfohlen bei:')
    for rank, (name, n) in enumerate(top3, 1):
        pct = (n / total_checked * 100) if total_checked else 0.0
        print(f'  {rank}. {name} ({pct:.1f}%)')
    print()


def main():
    print('=' * 70)
    print('XAUUSD FILTER FUNNEL DIAGNOSIS - LIVE V6 CONFIG')
    print('=' * 70)
    print(f'Config: {LIVE_CONFIG}')
    print(f'Score threshold: {SCORE_THRESHOLD}')
    print()

    m5, m15, h1 = load_data()
    total_checked = run_diagnosis(m5, m15, h1)
    print_report(total_checked)
    print(f'Data source: TwelveData {SYMBOL}, M5/M15/H1')


if __name__ == '__main__':
    main()
