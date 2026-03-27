import logging
from indicators import ema, rsi, atr
from config import SIGNAL_SCORE_THRESHOLD

log = logging.getLogger("strategy")


# ==============================
# TREND
# ==============================
def higher_timeframe_trend(closes):
    if ema(closes, 50) > ema(closes, 200):
        return "bullish"
    elif ema(closes, 50) < ema(closes, 200):
        return "bearish"
    return "neutral"


# ==============================
# STRUCTURE
# ==============================
def market_structure(highs, lows):
    if max(highs[-10:]) > max(highs[-20:-10]) and min(lows[-10:]) > min(lows[-20:-10]):
        return "bullish"
    elif max(highs[-10:]) < max(highs[-20:-10]) and min(lows[-10:]) < min(lows[-20:-10]):
        return "bearish"
    return "neutral"


# ==============================
# BOS
# ==============================
def break_of_structure(highs, lows, closes):
    prev_high = max(highs[-20:-2])
    prev_low = min(lows[-20:-2])

    if closes[-1] > prev_high:
        return "bullish"
    elif closes[-1] < prev_low:
        return "bearish"

    return None


# ==============================
# LIQUIDITY SWEEP
# ==============================
def liquidity_sweep(highs, lows, closes):
    prev_high = max(highs[-8:-1])
    prev_low = min(lows[-8:-1])

    if highs[-1] > prev_high and closes[-1] < prev_high:
        return "bearish"

    if lows[-1] < prev_low and closes[-1] > prev_low:
        return "bullish"

    return None


# ==============================
# ORDERBLOCK
# ==============================
def orderblock(highs, lows, opens, closes):

    for i in range(-5, -1):

        if closes[i] < opens[i] and closes[i+1] > highs[i]:
            return "bullish", lows[i], highs[i]

        if closes[i] > opens[i] and closes[i+1] < lows[i]:
            return "bearish", lows[i], highs[i]

    return None, None, None


# ==============================
# FIB ZONE
# ==============================
def fib_zone(highs, lows):

    high = max(highs[-20:])
    low = min(lows[-20:])

    fib_50 = low + (high - low) * 0.5
    fib_786 = low + (high - low) * 0.786

    return min(fib_50, fib_786), max(fib_50, fib_786)


# ==============================
# ENTRY ZONE (STRICT)
# ==============================
def in_entry_zone(price, ob_low, ob_high, fib_low, fib_high):

    in_ob = ob_low and ob_high and ob_low <= price <= ob_high
    in_fib = fib_low <= price <= fib_high

    return in_ob or in_fib


# ==============================
# SL / TP (RR 2.0 FIXED)
# ==============================
def calculate_sl_tp(direction, price, highs, lows):

    if direction == "bullish":
        sl = min(lows[-10:])
        risk = price - sl
        tp = price + (risk * 2)

    else:
        sl = max(highs[-10:])
        risk = sl - price
        tp = price - (risk * 2)

    return round(sl, 2), round(tp, 2)


# ==============================
# MAIN SIGNAL
# ==============================
def generate_signal(data):

    closes = data["close"]
    highs = data["high"]
    lows = data["low"]
    opens = data["open"]

    price = closes[-1]

    trend = higher_timeframe_trend(closes)
    structure = market_structure(highs, lows)
    bos = break_of_structure(highs, lows, closes)
    sweep = liquidity_sweep(highs, lows, closes)
    ob_dir, ob_low, ob_high = orderblock(highs, lows, opens, closes)
    fib_low, fib_high = fib_zone(highs, lows)

    log.info(f"Trend: {trend} | Structure: {structure} | BOS: {bos} | Sweep: {sweep} | OB: {ob_dir} | Price: {price}")

    # ==============================
    # DIRECTION
    # ==============================
    direction = trend

    if direction == "neutral":
        return None

    # ==============================
    # ENTRY ZONE (HARD FILTER)
    # ==============================
    has_zone = in_entry_zone(price, ob_low, ob_high, fib_low, fib_high)

    if not has_zone:
        log.info("❌ No valid entry zone")
        return None

    # ==============================
    # CONFLUENCE
    # ==============================
    confluence = 0

    if bos == direction:
        confluence += 1

    if sweep == direction:
        confluence += 1

    if structure == direction:
        confluence += 1

    if confluence == 0:
        return None

    log.info(f"🔥 STRONG SETUP | Conf: {confluence}")

    # ==============================
    # SCORE
    # ==============================
    score = 0

    score += 2  # Trend
    score += 2  # Zone

    if bos == direction:
        score += 2

    if sweep == direction:
        score += 2

    if structure == direction:
        score += 1

    rsi_value = rsi(closes)

    if 40 < rsi_value < 60:
        score += 1

    log.info(f"Score: {score}")

    if score < SIGNAL_SCORE_THRESHOLD:
        return None

    # ==============================
    # SL / TP
    # ==============================
    sl, tp = calculate_sl_tp(direction, price, highs, lows)

    display_direction = "BUY" if direction == "bullish" else "SELL"

    log.info("✅ PHASE 6.6 SIGNAL")

    return {
        "direction": display_direction,
        "entry": round(price, 2),
        "sl": sl,
        "tp": tp,
        "score": score,
        "notes": f"Phase 6.6 | RR: 2.0 | Conf: {confluence}"
    }