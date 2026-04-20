'''
XAUUSD SELL-Signal Diagnose

Misst fuer jeden M5-Candle im Trading-Fenster, welcher Gate im generate_signal
Funnel das Signal killt. Vergleicht bearish (SELL) vs bullish (BUY) Trends,
um systematische Bias-Bugs in der Strategy zu identifizieren.

Nutzt die aktuelle V_G Live-Config:
  - SCORE_THRESHOLD = 6.5
  - COOLDOWN_AFTER_WIN = 6, COOLDOWN_AFTER_LOSS = 12
  - RSI-Filter: BUY nur bei RSI < 75, SELL nur bei RSI > 25
  - OB Midpoint-Gate aktiv (Price muss noch vor OB-Mid stehen)

READ-ONLY diagnostic script. Beeinflusst Live-Bot nicht.

Daten-Loading wird 1:1 aus backtest_variants.py uebernommen.

USAGE (Railway Shell):
  python backtest_sell_diagnosis.py
'''

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

# V_G Live-Config
SCORE_THRESHOLD = 6.5
COOLDOWN_AFTER_WIN = 6
COOLDOWN_AFTER_LOSS = 12
RSI_MAX_BUY = 75
RSI_MIN_SELL = 25
OB_MIDPOINT_ON = True

LONDON_OPEN_UTC = 7
NY_CLOSE_UTC = 21

# ==============================
# DATA LOADING (1:1 aus backtest_variants.py)
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
# INDICATORS / SWING / STRUCTURE (1:1 aus backtest_variants.py)
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
# DIAGNOSTIC SIGNAL FUNNEL
# ==============================

GATE_ORDER = [
    'cooldown',
    'rsi_block',
    'no_ob',
    'ob_midpoint_fail',
    'ob_reused',
    'score_below',
    'signal_generated',
]


def init_counters():
    counters = {
        'trend_bullish': 0,
        'trend_bearish': 0,
        'trend_none': 0,
    }
    for side in ('bearish', 'bullish'):
        for gate in GATE_ORDER:
            counters[f'{side}_{gate}'] = 0
    return counters


def diagnose_candle(data_m5, data_m15, data_h1, candle_index,
                    last_signal_idx, used_ob, last_result, counters):
    c5 = data_m5['close']
    h5 = data_m5['high']
    l5 = data_m5['low']

    if len(c5) < 200 or len(data_m15['close']) < 50 or len(data_h1['close']) < 200:
        return None, used_ob, last_signal_idx

    c15 = data_m15['close']
    h15 = data_m15['high']
    l15 = data_m15['low']
    o15 = data_m15['open']
    c1 = data_h1['close']
    price = c5[-1]

    # Counter 1: H1 trend distribution
    trend = trend_direction(c1)
    if trend == 'bullish':
        counters['trend_bullish'] += 1
        prefix = 'bullish'
    elif trend == 'bearish':
        counters['trend_bearish'] += 1
        prefix = 'bearish'
    else:
        counters['trend_none'] += 1
        return None, used_ob, last_signal_idx

    direction = trend

    # Gate 1: cooldown
    cooldown = COOLDOWN_AFTER_LOSS if last_result == 'LOSS' else COOLDOWN_AFTER_WIN
    if candle_index - last_signal_idx < cooldown:
        counters[f'{prefix}_cooldown'] += 1
        return None, used_ob, last_signal_idx

    # Gate 2: RSI filter
    rsi_val = rsi(c5)
    if direction == 'bullish' and rsi_val > RSI_MAX_BUY:
        counters[f'{prefix}_rsi_block'] += 1
        return None, used_ob, last_signal_idx
    if direction == 'bearish' and rsi_val < RSI_MIN_SELL:
        counters[f'{prefix}_rsi_block'] += 1
        return None, used_ob, last_signal_idx

    # Gate 3: orderblock detection
    ob_low, ob_high = detect_orderblock(h15, l15, o15, c15, direction)
    if ob_low is None:
        counters[f'{prefix}_no_ob'] += 1
        return None, used_ob, last_signal_idx

    # Gate 4: OB midpoint (price must be past midpoint)
    if OB_MIDPOINT_ON:
        mid = (ob_low + ob_high) / 2
        if direction == 'bullish' and price > mid:
            counters[f'{prefix}_ob_midpoint_fail'] += 1
            return None, used_ob, last_signal_idx
        if direction == 'bearish' and price < mid:
            counters[f'{prefix}_ob_midpoint_fail'] += 1
            return None, used_ob, last_signal_idx

    # Gate 5: OB one-shot reuse
    ob_id = (round(ob_low, 0), round(ob_high, 0))
    if ob_id == used_ob:
        counters[f'{prefix}_ob_reused'] += 1
        return None, used_ob, last_signal_idx

    # Score components
    sweep = liquidity_sweep(h5, l5, c5)
    zone = premium_discount(h15, l15, price)
    structure, struct_str = market_structure(h15, l15)
    bos = detect_bos(h15, l15, c15)

    score = calculate_score(direction, trend, structure, struct_str, bos,
                            True, sweep, zone, rsi_val)

    # Gate 6: score threshold
    if score < SCORE_THRESHOLD:
        counters[f'{prefix}_score_below'] += 1
        return None, used_ob, last_signal_idx

    # Gate 7: signal generated
    counters[f'{prefix}_signal_generated'] += 1

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
    return signal, ob_id, candle_index

# ==============================
# ENGINE
# ==============================

def map_htf_index(m5_time, htf_df):
    for i in range(len(htf_df)):
        if htf_df.iloc[i]['datetime'] > m5_time:
            return max(0, i - 1)
    return len(htf_df) - 1


def run_diagnosis(m5, m15, h1):
    counters = init_counters()

    active_trade = None
    last_signal_idx = -1000
    used_ob = None
    last_result = 'WIN'

    scanned = 0

    for i in range(200, len(m5)):
        current_time = m5.iloc[i]['datetime']
        hour = current_time.hour
        weekday = current_time.weekday()

        # Session filter (mirrors live is_active_session)
        if weekday >= 5:
            continue
        if weekday == 4 and hour >= 19:
            continue
        if hour < LONDON_OPEN_UTC or hour >= NY_CLOSE_UTC:
            continue

        # Simulate active trade closure to update last_result
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

        m15_idx = map_htf_index(current_time, m15)
        h1_idx = map_htf_index(current_time, h1)

        if m15_idx < 50 or h1_idx < 200:
            continue

        data_m5 = df_to_dict(m5, i + 1)
        data_m15 = df_to_dict(m15, m15_idx + 1)
        data_h1 = df_to_dict(h1, h1_idx + 1)

        signal, new_used_ob, new_last_signal_idx = diagnose_candle(
            data_m5, data_m15, data_h1, i,
            last_signal_idx, used_ob, last_result, counters
        )

        scanned += 1

        if signal:
            active_trade = {**signal, 'open_idx': i}
            used_ob = new_used_ob
            last_signal_idx = i

    return counters, scanned

# ==============================
# REPORT
# ==============================

def pct(part, total):
    return (part / total * 100.0) if total > 0 else 0.0


def print_funnel(counters, side, total):
    print(f'=== {side.upper()} FUNNEL (fuer trend={side}) ===')
    for idx, gate in enumerate(GATE_ORDER, start=1):
        key = f'{side}_{gate}'
        val = counters[key]
        label = f'{side}_{gate}'
        print(f'Gate {idx} {label:30s}: {val:5d} ({pct(val, total):5.1f}%)')
    print()


def print_report(counters, scanned):
    total_trend = (counters['trend_bullish']
                   + counters['trend_bearish']
                   + counters['trend_none'])

    print('=== CONTEXT ===')
    print(f'Scanned candles (session-filtered, no active trade): {scanned}')
    print(f'Trend samples (>= 200 HTF history): {total_trend}')
    print()

    print('=== H1 TREND DISTRIBUTION ===')
    print(f'trend_bullish: {counters["trend_bullish"]:5d} candles ({pct(counters["trend_bullish"], total_trend):5.1f}%)')
    print(f'trend_bearish: {counters["trend_bearish"]:5d} candles ({pct(counters["trend_bearish"], total_trend):5.1f}%)')
    print(f'trend_none:    {counters["trend_none"]:5d} candles ({pct(counters["trend_none"], total_trend):5.1f}%)')
    print()
    print('Interpretation: Wenn bearish Anteil > 20%, aber 0 SELL-Signale, dann Bug bestaetigt')
    print()

    print_funnel(counters, 'bearish', counters['trend_bearish'])
    print_funnel(counters, 'bullish', counters['trend_bullish'])

    print('=== HYPOTHESEN-CHECK ===')
    b_total = counters['trend_bearish']
    u_total = counters['trend_bullish']

    b_no_ob_pct = pct(counters['bearish_no_ob'], b_total)
    u_no_ob_pct = pct(counters['bullish_no_ob'], u_total)
    b_mid_pct = pct(counters['bearish_ob_midpoint_fail'], b_total)
    u_mid_pct = pct(counters['bullish_ob_midpoint_fail'], u_total)
    b_score_pct = pct(counters['bearish_score_below'], b_total)
    u_score_pct = pct(counters['bullish_score_below'], u_total)

    print(f'bearish_no_ob={b_no_ob_pct:.1f}% vs bullish_no_ob={u_no_ob_pct:.1f}%')
    if b_total > 0 and u_total > 0 and b_no_ob_pct > u_no_ob_pct * 1.5:
        print('  -> detect_orderblock hat bearish-Bug')

    print(f'bearish_ob_midpoint_fail={b_mid_pct:.1f}% vs bullish_ob_midpoint_fail={u_mid_pct:.1f}%')
    if b_total > 0 and u_total > 0 and b_mid_pct > u_mid_pct * 1.5:
        print('  -> Midpoint-Logik ist asymmetrisch')

    print(f'bearish_score_below={b_score_pct:.1f}% vs bullish_score_below={u_score_pct:.1f}%')
    if b_total > 0 and u_total > 0 and b_score_pct > u_score_pct * 1.5:
        print('  -> Scoring-System bias gegen bearish')

    print()
    print(f'bearish_signal_generated: {counters["bearish_signal_generated"]}')
    print(f'bullish_signal_generated: {counters["bullish_signal_generated"]}')

# ==============================
# MAIN
# ==============================

def main():
    print('=' * 70)
    print('XAUUSD SELL-SIGNAL DIAGNOSIS')
    print('V_G config: Score 6.5, Cooldown 6/12, RSI 75/25, OB Midpoint ON')
    print('=' * 70)
    print()

    m5, m15, h1 = load_data()
    counters, scanned = run_diagnosis(m5, m15, h1)
    print_report(counters, scanned)

    print()
    print(f'Data source: TwelveData {SYMBOL}, M5/M15/H1')


if __name__ == '__main__':
    main()
