“””
XAUUSD Strategy Backtest — 8 Varianten Vergleich
Railway-kompatibel, nutzt TwelveData API

USAGE (Railway Shell):
python backtest_variants.py

Der TWELVE_DATA_KEY wird aus den Railway Environment Variables gelesen.
Live-Bot wird NICHT beeinflusst — dieses Script laeuft nur einmal on-demand.
“””

import os
import sys
import time
import requests
import pandas as pd

# ==============================

# CONFIG

# ==============================

TWELVE_DATA_KEY = os.environ.get(‘TWELVE_DATA_KEY’)
if not TWELVE_DATA_KEY:
print(‘FEHLER: TWELVE_DATA_KEY nicht gesetzt’)
sys.exit(1)

SYMBOL = ‘XAU/USD’
BACKTEST_DAYS = 60

VARIANTS = {
‘V1_Baseline_WeekOne’: {
‘chop_filter’: False,
‘entry_confirmation’: False,
‘ob_midpoint’: False,
‘structural_sl_tp’: False,
},
‘V2_CurrentLive’: {
‘chop_filter’: True,
‘entry_confirmation’: False,
‘ob_midpoint’: False,
‘structural_sl_tp’: False,
},
‘V3_FourFixes_NoChop’: {
‘chop_filter’: False,
‘entry_confirmation’: True,
‘ob_midpoint’: True,
‘structural_sl_tp’: True,
},
‘V4_FourFixes_WithChop’: {
‘chop_filter’: True,
‘entry_confirmation’: True,
‘ob_midpoint’: True,
‘structural_sl_tp’: True,
},
‘V5_OnlyEntryConfirm’: {
‘chop_filter’: False,
‘entry_confirmation’: True,
‘ob_midpoint’: False,
‘structural_sl_tp’: False,
},
‘V6_OnlyOBMidpoint’: {
‘chop_filter’: False,
‘entry_confirmation’: False,
‘ob_midpoint’: True,
‘structural_sl_tp’: False,
},
‘V7_OnlyStructuralSLTP’: {
‘chop_filter’: False,
‘entry_confirmation’: False,
‘ob_midpoint’: False,
‘structural_sl_tp’: True,
},
‘V8_Chop_Plus_StructuralSLTP’: {
‘chop_filter’: True,
‘entry_confirmation’: False,
‘ob_midpoint’: False,
‘structural_sl_tp’: True,
},
}

SCORE_THRESHOLD = 6.0
COOLDOWN_AFTER_WIN = 24
COOLDOWN_AFTER_LOSS = 48
LONDON_OPEN_UTC = 7
NY_CLOSE_UTC = 21

# ==============================

# DATA LOADING (TwelveData)

# ==============================

def fetch_twelvedata(interval, outputsize):
url = ‘https://api.twelvedata.com/time_series’
params = {
‘symbol’: SYMBOL,
‘interval’: interval,
‘outputsize’: outputsize,
‘apikey’: TWELVE_DATA_KEY,
‘format’: ‘JSON’,
‘order’: ‘ASC’,
}

```
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
```

def load_data():
print(f’Lade {SYMBOL} Daten von TwelveData ({BACKTEST_DAYS} Tage)…’)

```
# M5: 60 Tage * 288 candles/Tag = 17280 (max 5000 per call — aber Free Plan limitiert)
# Wir nutzen max. 5000 candles pro Request
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
```

def df_to_dict(df, end_idx=None):
if end_idx is not None:
df = df.iloc[:end_idx]
return {
‘open’: df[‘open’].values.tolist(),
‘high’: df[‘high’].values.tolist(),
‘low’: df[‘low’].values.tolist(),
‘close’: df[‘close’].values.tolist(),
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
return ‘bullish’
if e50 < e200:
return ‘bearish’
return None

def is_choppy(closes, threshold_pct=0.1):
if len(closes) < 200:
return True
e50 = ema(closes, 50)
e200 = ema(closes, 200)
spread_pct = abs(e50 - e200) / closes[-1] * 100
return spread_pct < threshold_pct

def market_structure(highs, lows):
sh = find_swing_highs(highs)
sl = find_swing_lows(lows)
if len(sh) < 2 or len(sl) < 2:
return ‘ranging’, 0.0
hh = sh[-1][1] > sh[-2][1]
hl = sl[-1][1] > sl[-2][1]
lh = sh[-1][1] < sh[-2][1]
ll = sl[-1][1] < sl[-2][1]
if hh and hl:
return ‘bullish’, 1.0
if lh and ll:
return ‘bearish’, 1.0
if hh or hl:
return ‘bullish’, 0.5
if lh or ll:
return ‘bearish’, 0.5
return ‘ranging’, 0.0

def detect_bos(highs, lows, closes):
sh = find_swing_highs(highs)
sl = find_swing_lows(lows)
if not sh or not sl:
return None
if closes[-1] > sh[-1][1]:
return ‘bullish’
if closes[-1] < sl[-1][1]:
return ‘bearish’
return None

def detect_orderblock(highs, lows, opens, closes, direction):
if len(closes) < 22:
return None, None
best = None
for i in range(len(closes) - 20, len(closes) - 2):
body = abs(opens[i] - closes[i])
if body < 0.01:
continue
if direction == ‘bullish’ and closes[i] < opens[i]:
future_high = max(highs[i+1:i+4])
displacement = future_high - lows[i]
if displacement > body * 2:
mitigated = any(closes[j] < lows[i] for j in range(i+1, len(closes)))
if not mitigated:
best = (lows[i], highs[i])
if direction == ‘bearish’ and closes[i] > opens[i]:
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
return ‘bearish’
if lows[-1] < prev_low and closes[-1] > prev_low:
return ‘bullish’
return None

def premium_discount(highs, lows, price):
hi = max(highs[-50:])
lo = min(lows[-50:])
if hi == lo:
return ‘mid’
pct = (price - lo) / (hi - lo)
if pct > 0.65:
return ‘premium’
if pct < 0.35:
return ‘discount’
return ‘mid’

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
if direction == ‘bullish’ and zone == ‘discount’:
score += 0.5
if direction == ‘bearish’ and zone == ‘premium’:
score += 0.5
if direction == ‘bullish’ and 30 < rsi_val < 55:
score += 0.5
if direction == ‘bearish’ and 45 < rsi_val < 70:
score += 0.5
return round(score, 1)

# ==============================

# SL/TP

# ==============================

def calculate_sl_tp_simple(direction, price, highs, lows, closes):
atr_val = calculate_atr(highs, lows, closes)
if direction == ‘bullish’:
swing_lows = find_swing_lows(lows, 3, 3)
structure_sl = swing_lows[-1][1] if swing_lows else min(lows[-15:])
sl_dist = price - (structure_sl - atr_val * 0.3)
else:
swing_highs = find_swing_highs(highs, 3, 3)
structure_sl = swing_highs[-1][1] if swing_highs else max(highs[-15:])
sl_dist = (structure_sl + atr_val * 0.3) - price
sl_dist = max(8.0, min(12.0, sl_dist))
sl = price - sl_dist if direction == ‘bullish’ else price + sl_dist
tp_dist = sl_dist * 2
tp = price + tp_dist if direction == ‘bullish’ else price - tp_dist
return sl, tp, sl_dist, 2.0

def calculate_sl_tp_structural(direction, price, highs, lows):
if direction == ‘bullish’:
swing_lows = find_swing_lows(lows, 3, 3)
if not swing_lows:
return None
structural_sl = swing_lows[-1][1] - 0.5
sl_dist = price - structural_sl
if sl_dist > 12.0 or sl_dist <= 0:
return None
swing_highs_above = [s[1] for s in find_swing_highs(highs, 3, 3) if s[1] > price]
tp_dist = (min(swing_highs_above) - price) if swing_highs_above else sl_dist * 2.0
rr = tp_dist / sl_dist
if rr < 1.5:
return None
sl = structural_sl
tp = price + tp_dist
else:
swing_highs = find_swing_highs(highs, 3, 3)
if not swing_highs:
return None
structural_sl = swing_highs[-1][1] + 0.5
sl_dist = structural_sl - price
if sl_dist > 12.0 or sl_dist <= 0:
return None
swing_lows_below = [s[1] for s in find_swing_lows(lows, 3, 3) if s[1] < price]
tp_dist = (price - max(swing_lows_below)) if swing_lows_below else sl_dist * 2.0
rr = tp_dist / sl_dist
if rr < 1.5:
return None
sl = structural_sl
tp = price - tp_dist
return sl, tp, sl_dist, round(rr, 2)

# ==============================

# SIGNAL GENERATOR

# ==============================

def generate_signal(data_m5, data_m15, data_h1, config, candle_index,
last_signal_idx, used_ob, last_result):
c5 = data_m5[‘close’]
h5 = data_m5[‘high’]
l5 = data_m5[‘low’]
o5 = data_m5[‘open’]

```
if len(c5) < 200 or len(data_m15['close']) < 50 or len(data_h1['close']) < 200:
    return None, used_ob, last_signal_idx

cooldown = COOLDOWN_AFTER_LOSS if last_result == 'LOSS' else COOLDOWN_AFTER_WIN
if candle_index - last_signal_idx < cooldown:
    return None, used_ob, last_signal_idx

c15 = data_m15['close']
h15 = data_m15['high']
l15 = data_m15['low']
o15 = data_m15['open']
c1 = data_h1['close']
price = c5[-1]

trend = trend_direction(c1)
if trend is None:
    return None, used_ob, last_signal_idx

if config['chop_filter'] and is_choppy(c1):
    return None, used_ob, last_signal_idx

direction = trend
rsi_val = rsi(c5)
if direction == 'bullish' and rsi_val > 60:
    return None, used_ob, last_signal_idx
if direction == 'bearish' and rsi_val < 40:
    return None, used_ob, last_signal_idx

ob_low, ob_high = detect_orderblock(h15, l15, o15, c15, direction)
if ob_low is None:
    return None, used_ob, last_signal_idx

if config['ob_midpoint']:
    mid = (ob_low + ob_high) / 2
    if direction == 'bullish' and price > mid:
        return None, used_ob, last_signal_idx
    if direction == 'bearish' and price < mid:
        return None, used_ob, last_signal_idx
else:
    if not (ob_low <= price <= ob_high):
        return None, used_ob, last_signal_idx

ob_id = (round(ob_low, 0), round(ob_high, 0))
if ob_id == used_ob:
    return None, used_ob, last_signal_idx

sweep = liquidity_sweep(h5, l5, c5)
zone = premium_discount(h15, l15, price)
structure, struct_str = market_structure(h15, l15)
bos = detect_bos(h15, l15, c15)

score = calculate_score(direction, trend, structure, struct_str, bos,
                        True, sweep, zone, rsi_val)
if score < SCORE_THRESHOLD:
    return None, used_ob, last_signal_idx

if config['entry_confirmation']:
    if direction == 'bullish' and c5[-1] <= o5[-1]:
        return None, used_ob, last_signal_idx
    if direction == 'bearish' and c5[-1] >= o5[-1]:
        return None, used_ob, last_signal_idx

if config['structural_sl_tp']:
    result = calculate_sl_tp_structural(direction, price, h5, l5)
    if result is None:
        return None, used_ob, last_signal_idx
    sl, tp, sl_dist, rr = result
else:
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
```

# ==============================

# BACKTEST ENGINE

# ==============================

def map_htf_index(m5_time, htf_df):
for i in range(len(htf_df)):
if htf_df.iloc[i][‘datetime’] > m5_time:
return max(0, i - 1)
return len(htf_df) - 1

def run_backtest(m5, m15, h1, config):
trades = []
active_trade = None
last_signal_idx = -1000
used_ob = None
last_result = ‘WIN’

```
for i in range(200, len(m5)):
    current_time = m5.iloc[i]['datetime']
    hour = current_time.hour
    if hour < LONDON_OPEN_UTC or hour >= NY_CLOSE_UTC:
        continue

    # Check active trade
    if active_trade is not None:
        high = m5.iloc[i]['high']
        low = m5.iloc[i]['low']
        closed = False

        if active_trade['direction'] == 'BUY':
            if low <= active_trade['sl']:
                pnl = -active_trade['sl_dist']
                trades.append({**active_trade, 'result': 'LOSS', 'pnl': pnl,
                               'duration_candles': i - active_trade['open_idx']})
                last_result = 'LOSS'
                closed = True
            elif high >= active_trade['tp']:
                pnl = active_trade['tp_dist']
                trades.append({**active_trade, 'result': 'WIN', 'pnl': pnl,
                               'duration_candles': i - active_trade['open_idx']})
                last_result = 'WIN'
                closed = True
        else:
            if high >= active_trade['sl']:
                pnl = -active_trade['sl_dist']
                trades.append({**active_trade, 'result': 'LOSS', 'pnl': pnl,
                               'duration_candles': i - active_trade['open_idx']})
                last_result = 'LOSS'
                closed = True
            elif low <= active_trade['tp']:
                pnl = active_trade['tp_dist']
                trades.append({**active_trade, 'result': 'WIN', 'pnl': pnl,
                               'duration_candles': i - active_trade['open_idx']})
                last_result = 'WIN'
                closed = True

        if closed:
            active_trade = None
        elif i - active_trade['open_idx'] > 288:
            active_trade = None

    if active_trade is not None:
        continue

    # Generate signal
    m15_idx = map_htf_index(current_time, m15)
    h1_idx = map_htf_index(current_time, h1)

    if m15_idx < 50 or h1_idx < 200:
        continue

    data_m5 = df_to_dict(m5, i + 1)
    data_m15 = df_to_dict(m15, m15_idx + 1)
    data_h1 = df_to_dict(h1, h1_idx + 1)

    signal, new_used_ob, new_last_signal_idx = generate_signal(
        data_m5, data_m15, data_h1, config, i,
        last_signal_idx, used_ob, last_result
    )

    if signal:
        active_trade = {**signal, 'open_idx': i}
        used_ob = new_used_ob
        last_signal_idx = i

return trades
```

# ==============================

# METRICS

# ==============================

def compute_metrics(trades):
if not trades:
return {
‘total_trades’: 0, ‘wins’: 0, ‘losses’: 0, ‘winrate’: 0,
‘total_pnl’: 0, ‘avg_pnl’: 0, ‘avg_rr’: 0,
‘fast_stop_rate’: 0, ‘max_drawdown’: 0, ‘expectancy’: 0,
}

```
wins = [t for t in trades if t['result'] == 'WIN']
losses = [t for t in trades if t['result'] == 'LOSS']
total_pnl = sum(t['pnl'] for t in trades)
winrate = len(wins) / len(trades) * 100

avg_win = sum(t['pnl'] for t in wins) / len(wins) if wins else 0
avg_loss = sum(t['pnl'] for t in losses) / len(losses) if losses else 0
expectancy = (winrate / 100) * avg_win + (1 - winrate / 100) * avg_loss

fast_stops = [t for t in losses if t['duration_candles'] <= 2]
fast_stop_rate = len(fast_stops) / len(losses) * 100 if losses else 0

equity = [0]
for t in trades:
    equity.append(equity[-1] + t['pnl'])
peak = equity[0]
max_dd = 0
for e in equity:
    if e > peak:
        peak = e
    dd = peak - e
    if dd > max_dd:
        max_dd = dd

avg_rr = sum(t['rr'] for t in trades) / len(trades)

return {
    'total_trades': len(trades),
    'wins': len(wins),
    'losses': len(losses),
    'winrate': round(winrate, 1),
    'total_pnl': round(total_pnl, 2),
    'avg_pnl': round(total_pnl / len(trades), 2),
    'avg_rr': round(avg_rr, 2),
    'fast_stop_rate': round(fast_stop_rate, 1),
    'max_drawdown': round(max_dd, 2),
    'expectancy': round(expectancy, 2),
}
```

# ==============================

# MAIN

# ==============================

def main():
print(’=’ * 70)
print(‘XAUUSD STRATEGY BACKTEST — 8 VARIANTEN’)
print(’=’ * 70)
print()

```
m5, m15, h1 = load_data()

results = {}
for variant_name, config in VARIANTS.items():
    print(f'Running {variant_name}...', flush=True)
    trades = run_backtest(m5, m15, h1, config)
    metrics = compute_metrics(trades)
    results[variant_name] = metrics
    print(f'  Trades: {metrics["total_trades"]} | WR: {metrics["winrate"]}% | '
          f'PnL: ${metrics["total_pnl"]} | Expectancy: ${metrics["expectancy"]}',
          flush=True)
print()

print('=' * 70)
print('FULL COMPARISON TABLE')
print('=' * 70)
df = pd.DataFrame(results).T
df = df[['total_trades', 'wins', 'losses', 'winrate', 'total_pnl',
        'avg_pnl', 'avg_rr', 'fast_stop_rate', 'max_drawdown', 'expectancy']]
print(df.to_string())
print()

print('=' * 70)
print('RANKING BY EXPECTANCY')
print('=' * 70)
ranked = sorted(results.items(), key=lambda x: x[1]['expectancy'], reverse=True)
for rank, (name, m) in enumerate(ranked, 1):
    print(f'{rank}. {name:32s} Exp: ${m["expectancy"]:6.2f} | '
          f'Trades: {m["total_trades"]:3d} | WR: {m["winrate"]:5.1f}% | '
          f'PnL: ${m["total_pnl"]:7.2f}')
print()

print('=' * 70)
print('RANKING BY TOTAL PNL')
print('=' * 70)
ranked_pnl = sorted(results.items(), key=lambda x: x[1]['total_pnl'], reverse=True)
for rank, (name, m) in enumerate(ranked_pnl, 1):
    print(f'{rank}. {name:32s} PnL: ${m["total_pnl"]:7.2f} | '
          f'Exp: ${m["expectancy"]:5.2f} | Trades: {m["total_trades"]}')
print()

print('=' * 70)
print('RECOMMENDATION')
print('=' * 70)
best_exp = ranked[0]
best_pnl = ranked_pnl[0]
if best_exp[0] == best_pnl[0]:
    print(f'WINNER: {best_exp[0]}')
    print(f'  Best in both Expectancy and Total PnL')
else:
    print(f'BEST EXPECTANCY: {best_exp[0]} (${best_exp[1]["expectancy"]})')
    print(f'BEST TOTAL PNL:  {best_pnl[0]} (${best_pnl[1]["total_pnl"]})')
print()
print(f'Data source: TwelveData {SYMBOL}, M5/M15/H1')
```

if **name** == ‘**main**’:
main()