from indicators import ema, rsi, atr
from config import SIGNAL_SCORE_THRESHOLD, COOLDOWN_MINUTES
from data import get_candles
import logging

log = logging.getLogger(“strategy”)
logging.basicConfig(level=logging.INFO, format=”%(asctime)s | %(name)s | %(message)s”)

# ============================================================

# ANALYSIS FUNCTIONS

# ============================================================

def higher_timeframe_trend(closes):
“”“H1 trend via EMA 50/200. Returns ‘bullish’, ‘bearish’, or ‘neutral’.”””
ema50 = ema(closes, 50)
ema200 = ema(closes, 200)

```
if ema50 > ema200:
    return "bullish"
if ema50 < ema200:
    return "bearish"
return "neutral"
```

def market_structure(highs, lows):
“”“M15 structure: compare recent vs previous swing zone.”””
if len(highs) < 20 or len(lows) < 20:
return “neutral”

```
recent_high = max(highs[-10:])
prev_high = max(highs[-20:-10])
recent_low = min(lows[-10:])
prev_low = min(lows[-20:-10])

if recent_high > prev_high and recent_low > prev_low:
    return "bullish"
if recent_high < prev_high and recent_low < prev_low:
    return "bearish"
return "neutral"
```

def break_of_structure(highs, lows, closes):
“”“Detect BOS using close price (not wicks). Returns (direction, level).”””
if len(highs) < 20 or len(lows) < 20:
return None, None

```
prev_high = max(highs[-20:-2])
prev_low = min(lows[-20:-2])
last_close = closes[-1]

if last_close > prev_high:
    return "bullish", prev_high
if last_close < prev_low:
    return "bearish", prev_low
return None, None
```

def liquidity_sweep(highs, lows, closes):
“”“Detect sweep: wick beyond level, close back inside.”””
if len(highs) < 8:
return None

```
prev_high = max(highs[-8:-1])
prev_low = min(lows[-8:-1])

# Bearish sweep: wick above highs, close back below = sell signal
if highs[-1] > prev_high and closes[-1] < prev_high:
    return "bearish"

# Bullish sweep: wick below lows, close back above = buy signal
if lows[-1] < prev_low and closes[-1] > prev_low:
    return "bullish"

return None
```

def premium_discount_zone(highs, lows, price):
“”“Returns ‘premium’, ‘discount’, or ‘equilibrium’.”””
high = max(highs[-40:])
low = min(lows[-40:])

```
if high == low:
    return "equilibrium"

pct = (price - low) / (high - low)

if pct > 0.65:
    return "premium"
elif pct < 0.35:
    return "discount"
return "equilibrium"
```

def retest(closes, level, tolerance):
“”“Check if current price is near the BOS level.”””
return abs(closes[-1] - level) <= tolerance

# ============================================================

# DIRECTION-BOUND SCORING

# ============================================================

def calculate_score(direction, trend, structure, bos, sweep, zone, rsi_value, has_retest):
“””
Score signal 0–11 with DIRECTION ALIGNMENT.
Each component only scores if it MATCHES the trade direction.
Returns (total_score, breakdown_string).
“””
score = 0
breakdown = []

```
# --- H1 Trend (max 2) ---
if trend == direction:
    score += 2
    breakdown.append(f"Trend: {trend} ✅ +2")
elif trend == "neutral":
    score += 0.5
    breakdown.append(f"Trend: neutral ⚠️ +0.5")
else:
    # Trend is AGAINST direction — penalty
    score -= 1
    breakdown.append(f"Trend: {trend} ❌ -1 (gegen Direction)")

# --- M15 Structure (max 2) ---
if structure == direction:
    score += 2
    breakdown.append(f"Structure: {structure} ✅ +2")
elif structure == "neutral":
    score += 0.5
    breakdown.append(f"Structure: neutral ⚠️ +0.5")
else:
    score -= 1
    breakdown.append(f"Structure: {structure} ❌ -1")

# --- BOS (max 2) ---
if bos == direction:
    score += 2
    breakdown.append(f"BOS: {bos} ✅ +2")
else:
    breakdown.append(f"BOS: {bos} — 0")

# --- Retest (max 2, soft now) ---
if has_retest:
    score += 2
    breakdown.append("Retest: confirmed ✅ +2")
else:
    score += 0
    breakdown.append("Retest: not at level — 0")

# --- Liquidity Sweep (max 1) ---
if sweep == direction:
    score += 1
    breakdown.append(f"Sweep: {sweep} ✅ +1")
else:
    breakdown.append(f"Sweep: {sweep or 'none'} — 0")

# --- Premium/Discount Zone (max 1) ---
zone_match = (
    (direction == "bullish" and zone == "discount") or
    (direction == "bearish" and zone == "premium")
)
if zone_match:
    score += 1
    breakdown.append(f"Zone: {zone} ✅ +1 (korrekt für {direction})")
elif zone == "equilibrium":
    score += 0
    breakdown.append(f"Zone: equilibrium — 0")
else:
    score -= 0.5
    breakdown.append(f"Zone: {zone} ⚠️ -0.5 (falsche Zone für {direction})")

# --- RSI Confirmation (max 1) ---
if direction == "bullish" and 30 < rsi_value < 55:
    score += 1
    breakdown.append(f"RSI: {rsi_value:.1f} ✅ +1 (buy zone)")
elif direction == "bearish" and 45 < rsi_value < 70:
    score += 1
    breakdown.append(f"RSI: {rsi_value:.1f} ✅ +1 (sell zone)")
else:
    breakdown.append(f"RSI: {rsi_value:.1f} — 0")

return max(0, score), breakdown
```

# ============================================================

# DIRECTION DETERMINATION

# ============================================================

def determine_direction(trend, structure, bos):
“””
Determine trade direction. BOS is leading, trend confirms.
Returns ‘bullish’, ‘bearish’, or None.
“””
if bos is None:
return None

```
# BOS sets the direction
direction = bos

# Check for conflict: BOS says one thing, H1 trend says opposite
if trend != "neutral" and trend != bos:
    # Conflict — only trade if structure supports BOS
    if structure == bos:
        log.info(f"Direction: {bos} (BOS + Structure override conflicting H1 trend)")
        return direction
    else:
        log.info(f"No direction: BOS={bos} conflicts with trend={trend}, structure={structure}")
        return None

return direction
```

# ============================================================

# RISK MANAGEMENT

# ============================================================

def calculate_sl_tp(direction, price, highs_5, lows_5, atr_value):
“””
Calculate SL/TP with ATR-based sizing and hard caps.
Returns dict with sl, tp1, tp2, pips, R:R info.
“””
# Gold: 1 pip = 0.01, so $1.00 = 100 pips
MIN_SL_PIPS = 80     # $0.80 minimum — below this, noise stops you out
MAX_SL_PIPS = 500    # $5.00 maximum — risk management cap

```
if direction == "bullish":
    # SL below recent lows + ATR buffer
    raw_sl = min(lows_5[-10:]) - atr_value * 0.3
    sl_distance = price - raw_sl
else:
    # SL above recent highs + ATR buffer
    raw_sl = max(highs_5[-10:]) + atr_value * 0.3
    sl_distance = raw_sl - price

# Convert to pips and apply caps
sl_pips = sl_distance / 0.01

if sl_pips < MIN_SL_PIPS:
    sl_distance = MIN_SL_PIPS * 0.01
    log.info(f"SL too tight ({sl_pips:.0f} pips), adjusted to {MIN_SL_PIPS}")
elif sl_pips > MAX_SL_PIPS:
    sl_distance = MAX_SL_PIPS * 0.01
    log.info(f"SL too wide ({sl_pips:.0f} pips), capped at {MAX_SL_PIPS}")

sl_pips = sl_distance / 0.01

if direction == "bullish":
    sl = price - sl_distance
    tp1 = price + sl_distance * 1.5   # 1:1.5 R:R
    tp2 = price + sl_distance * 2.5   # 1:2.5 R:R
else:
    sl = price + sl_distance
    tp1 = price - sl_distance * 1.5
    tp2 = price - sl_distance * 2.5

return {
    "sl": round(sl, 2),
    "tp1": round(tp1, 2),
    "tp2": round(tp2, 2),
    "sl_pips": round(sl_pips),
    "tp1_rr": "1:1.5",
    "tp2_rr": "1:2.5",
}
```

# ============================================================

# MAIN SIGNAL GENERATOR

# ============================================================

def generate_signal(data_m5):
“”“Generate trading signal with direction-bound scoring.”””

```
# --- Step 1: Fetch higher timeframes ---
data_m15 = get_candles("15min", 200)
data_h1 = get_candles("1h", 200)

if data_m15 is None or data_h1 is None:
    log.warning("Missing M15 or H1 data")
    return None

# --- Step 2: Extract price arrays ---
closes_5 = data_m5["close"]
highs_5 = data_m5["high"]
lows_5 = data_m5["low"]

closes_15 = data_m15["close"]
highs_15 = data_m15["high"]
lows_15 = data_m15["low"]

closes_h1 = data_h1["close"]

price = closes_5[-1]

# --- Step 3: Core analysis ---
trend = higher_timeframe_trend(closes_h1)
structure = market_structure(highs_15, lows_15)
bos, bos_level = break_of_structure(highs_15, lows_15, closes_15)

log.info(f"H1 Trend: {trend} | M15 Structure: {structure} | BOS: {bos}")

# --- Step 4: Determine direction (ONLY hard gate) ---
direction = determine_direction(trend, structure, bos)

if direction is None:
    log.info("No clear direction — skipping")
    return None

# --- Step 5: Additional analysis ---
sweep = liquidity_sweep(highs_5, lows_5, closes_5)
zone = premium_discount_zone(highs_15, lows_15, price)
rsi_value = rsi(closes_5)
atr_value = atr(highs_5, lows_5, closes_5)

# Retest check (soft filter now — contributes to score, doesn't block)
has_retest = False
if bos_level:
    has_retest = retest(closes_5, bos_level, atr_value * 0.5)  # wider tolerance

log.info(f"Sweep: {sweep} | Zone: {zone} | RSI: {rsi_value:.1f} | Retest: {has_retest}")

# --- Step 6: Direction-bound scoring ---
score, breakdown = calculate_score(
    direction, trend, structure, bos, sweep, zone, rsi_value, has_retest
)

log.info(f"Score: {score}/11 (threshold: {SIGNAL_SCORE_THRESHOLD})")
for line in breakdown:
    log.info(f"  {line}")

# --- Step 7: Score gate ---
if score < SIGNAL_SCORE_THRESHOLD:
    log.info(f"Score {score} below threshold {SIGNAL_SCORE_THRESHOLD} — skipping")
    return None

# --- Step 8: Risk management ---
display_direction = "BUY" if direction == "bullish" else "SELL"
risk = calculate_sl_tp(direction, price, highs_5, lows_5, atr_value)

# --- Step 9: Confidence label ---
if score >= 9:
    confidence = "🔥 High Confidence"
elif score >= 7:
    confidence = "✅ Good Setup"
else:
    confidence = "⚠️ Moderate"

return {
    "direction": display_direction,
    "entry": round(price, 2),
    "sl": risk["sl"],
    "tp1": risk["tp1"],
    "tp2": risk["tp2"],
    "sl_pips": risk["sl_pips"],
    "tp1_rr": risk["tp1_rr"],
    "tp2_rr": risk["tp2_rr"],
    "score": score,
    "confidence": confidence,
    "notes": " | ".join(breakdown),
}
```