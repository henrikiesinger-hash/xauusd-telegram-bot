import logging
from indicators import ema, rsi
from data import get_candles

log = logging.getLogger("strategy")


# ==============================
# SWING POINT DETECTION
# ==============================
def find_swing_highs(highs, left=5, right=5):
    swings = []
    for i in range(left, len(highs) - right):
        window = highs[i - left:i + right + 1]
        if highs[i] == max(window) and len(set(window)) > 1:
            swings.append((i, highs[i]))
    return swings


def find_swing_lows(lows, left=5, right=5):
    swings = []
    for i in range(left, len(lows) - right):
        window = lows[i - left:i + right + 1]
        if lows[i] == min(window) and len(set(window)) > 1:
            swings.append((i, lows[i]))
    return swings


# ==============================
# MARKET STRUCTURE
# ==============================
def market_structure(highs, lows, left=5, right=5):
    swing_highs = find_swing_highs(highs, left, right)
    swing_lows = find_swing_lows(lows, left, right)

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return "ranging", 0.0

    sh1 = swing_highs[-2][1]
    sh2 = swing_highs[-1][1]
    sl1 = swing_lows[-2][1]
    sl2 = swing_lows[-1][1]

    hh = sh2 > sh1
    hl = sl2 > sl1
    lh = sh2 < sh1
    ll = sl2 < sl1

    if hh and hl:
        if len(swing_highs) >= 3 and swing_highs[-2][1] > swing_highs[-3][1]:
            return "bullish", 1.0
        return "bullish", 0.7

    if lh and ll:
        if len(swing_lows) >= 3 and swing_lows[-2][1] < swing_lows[-3][1]:
            return "bearish", 1.0
        return "bearish", 0.7

    if hh and ll:
        return "ranging", 0.3

    if lh and hl:
        return "ranging", 0.3

    return "ranging", 0.2


# ==============================
# H1 TREND
# ==============================
def trend_direction(closes):
    if len(closes) < 200:
        return None, 0.0

    ema21 = ema(closes, 21)
    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)

    if ema21 > ema50 > ema200:
        return "bullish", 1.0
    if ema21 < ema50 < ema200:
        return "bearish", 1.0
    if ema50 > ema200:
        return "bullish", 0.5
    if ema50 < ema200:
        return "bearish", 0.5

    return None, 0.0


# ==============================
# BREAK OF STRUCTURE
# ==============================
def detect_bos(highs, lows, closes, left=5, right=5):
    swing_highs = find_swing_highs(highs, left, right)
    swing_lows = find_swing_lows(lows, left, right)

    if len(swing_highs) < 1 or len(swing_lows) < 1:
        return None, None

    last_close = closes[-1]
    last_sh = swing_highs[-1][1]
    last_sl = swing_lows[-1][1]

    if last_close > last_sh:
        return "bullish", last_sh

    if last_close < last_sl:
        return "bearish", last_sl

    return None, None


# ==============================
# ORDERBLOCK
# ==============================
def detect_orderblock(highs, lows, opens, closes, direction, lookback=20):
    if len(closes) < lookback + 3:
        return None, None, None, 0.0

    start = len(closes) - lookback
    best_ob = None

    for i in range(start, len(closes) - 2):
        is_bearish_candle = closes[i] < opens[i]
        is_bullish_candle = closes[i] > opens[i]

        if direction == "bullish" and is_bearish_candle:
            future_end = min(i + 4, len(highs))
            future_max = max(highs[i + 1:future_end])
            displacement = future_max - lows[i]
            body_size = abs(opens[i] - closes[i])

            if body_size <= 0:
                continue

            if displacement > body_size * 2:
                mitigated = False
                for j in range(i + 1, len(closes)):
                    if closes[j] < lows[i]:
                        mitigated = True
                        break

                if not mitigated:
                    strength = min(1.0, displacement / (body_size * 4))
                    best_ob = (lows[i], highs[i], strength, i)

        if direction == "bearish" and is_bullish_candle:
            future_end = min(i + 4, len(lows))
            future_min = min(lows[i + 1:future_end])
            displacement = highs[i] - future_min
            body_size = abs(opens[i] - closes[i])

            if body_size <= 0:
                continue

            if displacement > body_size * 2:
                mitigated = False
                for j in range(i + 1, len(closes)):
                    if closes[j] > highs[i]:
                        mitigated = True
                        break

                if not mitigated:
                    strength = min(1.0, displacement / (body_size * 4))
                    best_ob = (lows[i], highs[i], strength, i)

    if best_ob is None:
        return None, None, None, 0.0

    return direction, best_ob[0], best_ob[1], best_ob[2]


# ==============================
# LIQUIDITY SWEEP
# ==============================
def liquidity_sweep(highs, lows, closes):
    if len(highs) < 10:
        return None

    prev_high = max(highs[-10:-1])
    prev_low = min(lows[-10:-1])

    if highs[-1] > prev_high and closes[-1] < prev_high:
        return "bearish"

    if lows[-1] < prev_low and closes[-1] > prev_low:
        return "bullish"

    return None


# ==============================
# PREMIUM / DISCOUNT
# ==============================
def premium_discount(highs, lows, price):
    high = max(highs[-50:])
    low = min(lows[-50:])

    if high == low:
        return "equilibrium"

    pct = (price - low) / (high - low)

    if pct > 0.65:
        return "premium"
    if pct < 0.35:
        return "discount"
    return "equilibrium"


# ==============================
# RANGE FILTER
# ==============================
def is_ranging(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return True

    total_range = max(highs[-period:]) - min(lows[-period:])
    if total_range == 0:
        return True

    body_sum = 0.0
    for i in range(-period, 0):
        body_sum += abs(closes[i] - closes[i - 1])

    directional_ratio = body_sum / total_range

    if directional_ratio > 5.0:
        return True

    avg_body = body_sum / period
    avg_range = total_range / period

    if avg_body < avg_range * 0.3:
        return True

    return False


# ==============================
# ENTRY ZONE CHECK
# ==============================
def in_entry_zone(price, ob_low, ob_high):
    if ob_low is None or ob_high is None:
        return False
    return ob_low <= price <= ob_high


# ==============================
# ATR
# ==============================
def calculate_atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return 0.0

    tr_values = []
    for i in range(-period, 0):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )
        tr_values.append(tr)

    return sum(tr_values) / len(tr_values)


# ==============================
# SL / TP
# ==============================
def calculate_sl_tp(direction, price, highs, lows, closes):
    atr_val = calculate_atr(highs, lows, closes)

    min_sl = 0.80
    max_sl = 5.00

    if direction == "bullish":
        raw_sl = min(lows[-10:]) - atr_val * 0.3
        sl_dist = price - raw_sl
    else:
        raw_sl = max(highs[-10:]) + atr_val * 0.3
        sl_dist = raw_sl - price

    if sl_dist < min_sl:
        sl_dist = min_sl
    if sl_dist > max_sl:
        sl_dist = max_sl

    if direction == "bullish":
        sl = price - sl_dist
        tp = price + sl_dist * 2.0
    else:
        sl = price + sl_dist
        tp = price - sl_dist * 2.0

    return round(sl, 2), round(tp, 2)


# ==============================
# SCORE SYSTEM
# ==============================
def calculate_score(
    direction,
    trend,
    trend_str,
    structure,
    struct_str,
    bos,
    sweep,
    zone,
    ob_dir,
    ob_strength,
    rsi_val,
    has_retest
):
    score = 0.0
    parts = []

    # H1 Trend (max 2.0)
    if trend == direction:
        pts = 1.0 + trend_str
        score += pts
        parts.append(f"Trend +{pts}")
    else:
        parts.append("Trend 0")

    # M15 Structure (max 2.0)
    if structure == direction:
        pts = 1.0 + struct_str
        score += pts
        parts.append(f"Structure +{pts}")
    elif structure == "ranging":
        parts.append("Structure ranging 0")
    else:
        parts.append("Structure conflict 0")

    # BOS (max 2.0)
    if bos == direction:
        score += 2.0
        parts.append("BOS +2")
    else:
        parts.append(f"BOS {bos} 0")

    # Orderblock quality (max 1.5)
    if ob_dir == direction and ob_strength > 0:
        pts = round(1.5 * ob_strength, 1)
        score += pts
        parts.append(f"OB +{pts}")
    else:
        parts.append("OB 0")

    # Retest (max 1.0)
    if has_retest:
        score += 1.0
        parts.append("Retest +1")
    else:
        parts.append("Retest 0")

    # Sweep (max 0.5)
    if sweep == direction:
        score += 0.5
        parts.append("Sweep +0.5")
    else:
        parts.append(f"Sweep {sweep} 0")

    # Zone (max 0.5)
    zone_ok = (
        (direction == "bullish" and zone == "discount") or
        (direction == "bearish" and zone == "premium")
    )
    if zone_ok:
        score += 0.5
        parts.append("Zone +0.5")
    else:
        parts.append(f"Zone {zone} 0")

    # RSI (max 0.5)
    if direction == "bullish" and 30 < rsi_val < 55:
        score += 0.5
        parts.append("RSI +0.5")
    elif direction == "bearish" and 45 < rsi_val < 70:
        score += 0.5
        parts.append("RSI +0.5")
    else:
        parts.append(f"RSI {round(rsi_val, 1)} 0")

    total = max(0.0, round(score, 1))
    return total, parts


# ==============================
# MAIN SIGNAL GENERATOR
# ==============================
def generate_signal(data_m5):

    if not hasattr(generate_signal, "htf_cache"):
        generate_signal.htf_cache = (
            get_candles("15min"),
            get_candles("1h")
        )

    data_m15, data_h1 = generate_signal.htf_cache

    if data_m15 is None or data_h1 is None:
        log.info("Missing HTF data")
        return None

    # M5
    c5 = data_m5["close"]
    h5 = data_m5["high"]
    l5 = data_m5["low"]
    o5 = data_m5["open"]

    # M15
    c15 = data_m15["close"]
    h15 = data_m15["high"]
    l15 = data_m15["low"]
    o15 = data_m15["open"]

    # H1
    c_h1 = data_h1["close"]

    price = c5[-1]

    # 🔥 RANGE FILTER (LESS STRICT)
    if is_ranging(h15, l15, c15):
        log.info("Market slightly ranging - continue with caution")

    # H1 TREND
    trend, trend_str = trend_direction(c_h1)
    if trend is None:
        log.info("No H1 trend - skip")
        return None

    # M15 STRUCTURE
    structure, struct_str = market_structure(h15, l15)

    # BOS
    bos, bos_level = detect_bos(h15, l15, c15)

    log.info(
        "Trend: %s (%.1f) | Structure: %s (%.1f) | BOS: %s",
        trend, trend_str, structure, struct_str, bos
    )

    # 🔥 FIXED DIRECTION LOGIC
    direction = None

    if bos is not None:
        if bos == trend:
            direction = bos
        elif structure == bos:
            direction = bos

    elif trend == structure and structure != "ranging":
        direction = trend

    # 🔥 NEW FALLBACK (WICHTIGSTER FIX)
    elif structure == "ranging" and trend is not None:
        direction = trend
        log.info("Fallback to trend direction")

    if direction is None:
        log.info("No aligned direction - skip")
        return None

    # ORDERBLOCK
    ob_dir, ob_low, ob_high, ob_strength = detect_orderblock(
        h15, l15, o15, c15, direction
    )

    at_ob = in_entry_zone(price, ob_low, ob_high)

    # CONFIRMATIONS
    sweep = liquidity_sweep(h5, l5, c5)
    zone = premium_discount(h15, l15, price)
    rsi_val = rsi(c5)

    has_retest = False
    if bos_level is not None:
        atr_val = calculate_atr(h5, l5, c5)
        if atr_val > 0:
            has_retest = abs(price - bos_level) <= atr_val * 0.5

    log.info(
        "OB: %s (str:%.1f) at_OB:%s | Sweep: %s | Zone: %s | RSI: %.1f",
        ob_dir, ob_strength, at_ob, sweep, zone, rsi_val
    )

    # SCORE
    score, parts = calculate_score(
        direction,
        trend,
        trend_str,
        structure,
        struct_str,
        bos,
        sweep,
        zone,
        ob_dir,
        ob_strength,
        rsi_val,
        has_retest
    )

    log.info("Score: %s/10 | %s", score, " | ".join(parts))

    # 🔥 ENTRY GATE FIX
    if score < 5.5:
        log.info("Score too low - skip")
        return None

    if not at_ob and score < 7.0:
        log.info("Not at OB and score < 7 - skip")
        return None

    # SL TP
    sl, tp = calculate_sl_tp(direction, price, h5, l5, c5)

    # CONFIDENCE
    if score >= 8.5:
        conf = "SNIPER"
    elif score >= 7.0:
        conf = "HIGH"
    elif score >= 5.5:
        conf = "MODERATE"
    else:
        conf = "LOW"

    display = "BUY" if direction == "bullish" else "SELL"

    log.info("SIGNAL: %s | Score: %s | Conf: %s", display, score, conf)

    return {
        "direction": display,
        "entry": round(price, 2),
        "sl": sl,
        "tp": tp,
        "score": score,
        "confidence": conf,
        "notes": " | ".join(parts)
    }
    return {
        "direction": display,
        "entry": round(price, 2),
        "sl": sl,
        "tp": tp,
        "score": score,
        "confidence": conf,
        "notes": " | ".join(parts)
    }