from indicators import ema, rsi, atr
from config import SIGNAL_SCORE_THRESHOLD, COOLDOWN_MINUTES
from data import get_candles
import logging

log = logging.getLogger(‘strategy’)
logging.basicConfig(level=logging.INFO, format=’%(asctime)s | %(name)s | %(message)s’)

def higher_timeframe_trend(closes):
ema50 = ema(closes, 50)
ema200 = ema(closes, 200)
if ema50 > ema200:
return ‘bullish’
if ema50 < ema200:
return ‘bearish’
return ‘neutral’

def market_structure(highs, lows):
if len(highs) < 20 or len(lows) < 20:
return ‘neutral’
recent_high = max(highs[-10:])
prev_high = max(highs[-20:-10])
recent_low = min(lows[-10:])
prev_low = min(lows[-20:-10])
if recent_high > prev_high and recent_low > prev_low:
return ‘bullish’
if recent_high < prev_high and recent_low < prev_low:
return ‘bearish’
return ‘neutral’

def break_of_structure(highs, lows, closes):
if len(highs) < 20 or len(lows) < 20:
return None, None
prev_high = max(highs[-20:-2])
prev_low = min(lows[-20:-2])
last_close = closes[-1]
if last_close > prev_high:
return ‘bullish’, prev_high
if last_close < prev_low:
return ‘bearish’, prev_low
return None, None

def liquidity_sweep(highs, lows, closes):
if len(highs) < 8:
return None
prev_high = max(highs[-8:-1])
prev_low = min(lows[-8:-1])
if highs[-1] > prev_high and closes[-1] < prev_high:
return ‘bearish’
if lows[-1] < prev_low and closes[-1] > prev_low:
return ‘bullish’
return None

def premium_discount_zone(highs, lows, price):
high = max(highs[-40:])
low = min(lows[-40:])
if high == low:
return ‘equilibrium’
pct = (price - low) / (high - low)
if pct > 0.65:
return ‘premium’
elif pct < 0.35:
return ‘discount’
return ‘equilibrium’

def retest(closes, level, tolerance):
return abs(closes[-1] - level) <= tolerance

def calculate_score(direction, trend, structure, bos, sweep, zone, rsi_value, has_retest):
score = 0
breakdown = []

```
if trend == direction:
    score += 2
    breakdown.append('Trend: ' + trend + ' +2')
elif trend == 'neutral':
    score += 0.5
    breakdown.append('Trend: neutral +0.5')
else:
    score -= 1
    breakdown.append('Trend: ' + trend + ' -1')

if structure == direction:
    score += 2
    breakdown.append('Structure: ' + structure + ' +2')
elif structure == 'neutral':
    score += 0.5
    breakdown.append('Structure: neutral +0.5')
else:
    score -= 1
    breakdown.append('Structure: ' + structure + ' -1')

if bos == direction:
    score += 2
    breakdown.append('BOS: ' + bos + ' +2')
else:
    breakdown.append('BOS: ' + str(bos) + ' 0')

if has_retest:
    score += 2
    breakdown.append('Retest: confirmed +2')
else:
    breakdown.append('Retest: no 0')

if sweep == direction:
    score += 1
    breakdown.append('Sweep: ' + str(sweep) + ' +1')
else:
    breakdown.append('Sweep: ' + str(sweep) + ' 0')

zone_match = (
    (direction == 'bullish' and zone == 'discount') or
    (direction == 'bearish' and zone == 'premium')
)
if zone_match:
    score += 1
    breakdown.append('Zone: ' + zone + ' +1')
elif zone == 'equilibrium':
    breakdown.append('Zone: equilibrium 0')
else:
    score -= 0.5
    breakdown.append('Zone: ' + zone + ' -0.5')

if direction == 'bullish' and 30 < rsi_value < 55:
    score += 1
    breakdown.append('RSI: ' + str(round(rsi_value, 1)) + ' +1')
elif direction == 'bearish' and 45 < rsi_value < 70:
    score += 1
    breakdown.append('RSI: ' + str(round(rsi_value, 1)) + ' +1')
else:
    breakdown.append('RSI: ' + str(round(rsi_value, 1)) + ' 0')

return max(0, score), breakdown
```

def determine_direction(trend, structure, bos):
if bos is None:
return None
direction = bos
if trend != ‘neutral’ and trend != bos:
if structure == bos:
log.info(‘Direction: %s (BOS + Structure override trend)’, bos)
return direction
else:
log.info(‘No direction: BOS=%s conflicts with trend=%s’, bos, trend)
return None
return direction

def calculate_sl_tp(direction, price, highs_5, lows_5, atr_value):
MIN_SL_PIPS = 80
MAX_SL_PIPS = 500

```
if direction == 'bullish':
    raw_sl = min(lows_5[-10:]) - atr_value * 0.3
    sl_distance = price - raw_sl
else:
    raw_sl = max(highs_5[-10:]) + atr_value * 0.3
    sl_distance = raw_sl - price

sl_pips = sl_distance / 0.01
if sl_pips < MIN_SL_PIPS:
    sl_distance = MIN_SL_PIPS * 0.01
elif sl_pips > MAX_SL_PIPS:
    sl_distance = MAX_SL_PIPS * 0.01

sl_pips = sl_distance / 0.01

if direction == 'bullish':
    sl = price - sl_distance
    tp1 = price + sl_distance * 1.5
    tp2 = price + sl_distance * 2.5
else:
    sl = price + sl_distance
    tp1 = price - sl_distance * 1.5
    tp2 = price - sl_distance * 2.5

return {
    'sl': round(sl, 2),
    'tp1': round(tp1, 2),
    'tp2': round(tp2, 2),
    'sl_pips': round(sl_pips),
    'tp1_rr': '1:1.5',
    'tp2_rr': '1:2.5',
}
```

def generate_signal(data_m5):
data_m15 = get_candles(‘15min’, 200)
data_h1 = get_candles(‘1h’, 200)

```
if data_m15 is None or data_h1 is None:
    log.warning('Missing M15 or H1 data')
    return None

closes_5 = data_m5['close']
highs_5 = data_m5['high']
lows_5 = data_m5['low']
closes_15 = data_m15['close']
highs_15 = data_m15['high']
lows_15 = data_m15['low']
closes_h1 = data_h1['close']
price = closes_5[-1]

trend = higher_timeframe_trend(closes_h1)
structure = market_structure(highs_15, lows_15)
bos, bos_level = break_of_structure(highs_15, lows_15, closes_15)

log.info('H1 Trend: %s | M15 Structure: %s | BOS: %s', trend, structure, bos)

direction = determine_direction(trend, structure, bos)
if direction is None:
    log.info('No clear direction - skipping')
    return None

sweep = liquidity_sweep(highs_5, lows_5, closes_5)
zone = premium_discount_zone(highs_15, lows_15, price)
rsi_value = rsi(closes_5)
atr_value = atr(highs_5, lows_5, closes_5)

has_retest = False
if bos_level:
    has_retest = retest(closes_5, bos_level, atr_value * 0.5)

log.info('Sweep: %s | Zone: %s | RSI: %.1f | Retest: %s', sweep, zone, rsi_value, has_retest)

score, breakdown = calculate_score(
    direction, trend, structure, bos, sweep, zone, rsi_value, has_retest
)

log.info('Score: %s/11 (threshold: %s)', score, SIGNAL_SCORE_THRESHOLD)
for line in breakdown:
    log.info('  %s', line)

if score < SIGNAL_SCORE_THRESHOLD:
    log.info('Score %s below threshold - skipping', score)
    return None

display_direction = 'BUY' if direction == 'bullish' else 'SELL'
risk = calculate_sl_tp(direction, price, highs_5, lows_5, atr_value)

if score >= 9:
    confidence = 'High Confidence'
elif score >= 7:
    confidence = 'Good Setup'
else:
    confidence = 'Moderate'

return {
    'direction': display_direction,
    'entry': round(price, 2),
    'sl': risk['sl'],
    'tp1': risk['tp1'],
    'tp2': risk['tp2'],
    'sl_pips': risk['sl_pips'],
    'tp1_rr': risk['tp1_rr'],
    'tp2_rr': risk['tp2_rr'],
    'score': score,
    'confidence': confidence,
    'notes': ' | '.join(breakdown),
}
```
