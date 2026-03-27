from indicators import ema, rsi, atr
from config import SIGNAL_SCORE_THRESHOLD
from data import get_candles
import logging

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
        return "bullish", prev_high
    elif closes[-1] < prev_low:
        return "bearish", prev_low

    return None, None


# ==============================
# SWEEP
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
    for i in range(-6, -1):

        if closes[i] < opens[i] and closes[i+1] > highs[i]:
            return "bullish", lows[i], highs[i]

        if closes[i] > opens[i] and closes[i+1] < lows[i]:
            return "bearish", lows[i], highs[i]

    return None, None, None


# ==============================
# FIBONACCI OTE
# ==============================
def fibonacci_ote(highs, lows, direction):

    swing_high = max(highs[-20:])
    swing_low = min(lows[-20:])

    if direction == "bullish":
        fib_62 = swing_high - (swing_high - swing_low) * 0.62
        fib_79 = swing_high - (swing_high - swing_low) * 0.79
        return fib_79, fib_62

    else:
        fib_62 = swing_low + (swing_high - swing_low) * 0.62
        fib_79 = swing_low + (swing_high - swing_low) * 0.79
        return fib_62, fib_79


# ==============================
# ENTRY ZONE CHECK
# ==============================
def in_entry_zone(price, ob_low, ob_high, fib_low, fib_high):

    in_ob = ob_low is not None and ob_low <= price <= ob_high
    in_fib = fib_low <= price <= fib_high

    return in_ob or in_fib


# ==============================
# SL / TP
# ==============================
def calculate_sl_tp(direction, price, highs_5, lows_5, atr_value):

    if direction == "bullish":
        sl = min(lows_5[-10:]) - atr_value * 0.3
        tp = max(highs_5[-20:])
    else:
        sl = max(highs_5[-10:]) + atr_value * 0.3
        tp = min(lows_5[-20:])

    return round(sl, 2), round(tp, 2)


# ==============================
# MAIN SIGNAL FUNCTION
# ==============================
def generate_signal(data_m5):

    # CACHE HTF
    if not hasattr(generate_signal, "htf_data"):
        data_m15 = get_candles("15min")
        data_h1 = get_candles("1h")
        generate_signal.htf_data = (data_m15, data_h1)
    else:
        data_m15, data_h1 = generate_signal.htf_data

    if not data_m15 or not data_h1:
        return None

    opens_5 = data_m5["open"]
    closes_5 = data_m5["close"]
    highs_5 = data_m5["high"]
    lows_5 = data_m5["low"]

    closes_15 = data_m15["close"]
    highs_15 = data_m15["high"]
    lows_15 = data_m15["low"]

    closes_h1 = data_h1["close"]

    price = closes_5[-1]

    trend = higher_timeframe_trend(closes_h1)
    structure = market_structure(highs_15, lows_15)
    bos, _ = break_of_structure(highs_15, lows_15, closes_15)
    sweep = liquidity_sweep(highs_5, lows_5, closes_5)

    if trend == "neutral":
        return None

    direction = trend

    ob_dir, ob_low, ob_high = orderblock(highs_5, lows_5, opens_5, closes_5)

    fib_low, fib_high = fibonacci_ote(highs_15, lows_15, direction)

    log.info(f"Trend: {trend} | OB: {ob_dir} | Price: {price}")

    # ==============================
    # SCORE SYSTEM 🔥
    # ==============================
    score = 0

    if trend == direction:
        score += 2

    if structure == direction:
        score += 2

    if bos == direction:
        score += 1

    if sweep == direction:
        score += 1

    if ob_dir == direction:
        score += 2

    # 🔥 ENTRY ZONE = BONUS (NICHT MEHR BLOCKER)
    if in_entry_zone(price, ob_low, ob_high, fib_low, fib_high):
        score += 2
    else:
        log.info("⚠️ No perfect entry zone")

    rsi_value = rsi(closes_5)

    if 40 < rsi_value < 60:
        score += 1

    log.info(f"Score: {score}")

    if score < SIGNAL_SCORE_THRESHOLD:
        return None

    display_direction = "BUY" if direction == "bullish" else "SELL"

    atr_value = atr(highs_5, lows_5, closes_5)

    sl, tp = calculate_sl_tp(direction, price, highs_5, lows_5, atr_value)

    log.info("✅ PRECISION SIGNAL")

    return {
        "direction": display_direction,
        "entry": round(price, 2),
        "sl": sl,
        "tp": tp,
        "score": score,
        "notes": "Balanced Precision Entry"
    }