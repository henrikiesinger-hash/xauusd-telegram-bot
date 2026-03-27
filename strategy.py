from indicators import ema, rsi, atr
from config import SIGNAL_SCORE_THRESHOLD
from data import get_candles
import logging

log = logging.getLogger("strategy")
logging.basicConfig(level=logging.INFO)


# ==============================
# TREND
# ==============================
def higher_timeframe_trend(closes):
    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)

    if ema50 > ema200:
        return "bullish"
    if ema50 < ema200:
        return "bearish"
    return "neutral"


# ==============================
# MARKET STRUCTURE
# ==============================
def market_structure(highs, lows):
    if len(highs) < 20:
        return "neutral"

    recent_high = max(highs[-10:])
    prev_high = max(highs[-20:-10])

    recent_low = min(lows[-10:])
    prev_low = min(lows[-20:-10])

    if recent_high > prev_high and recent_low > prev_low:
        return "bullish"

    if recent_high < prev_high and recent_low < prev_low:
        return "bearish"

    return "neutral"


# ==============================
# BOS
# ==============================
def break_of_structure(highs, lows, closes):
    if len(highs) < 20:
        return None, None

    prev_high = max(highs[-20:-2])
    prev_low = min(lows[-20:-2])
    last_close = closes[-1]

    if last_close > prev_high:
        return "bullish", prev_high

    if last_close < prev_low:
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
# ZONE
# ==============================
def premium_discount_zone(highs, lows, price):
    high = max(highs[-40:])
    low = min(lows[-40:])
    eq = (high + low) / 2

    if price > eq:
        return "premium"
    else:
        return "discount"


# ==============================
# RETEST
# ==============================
def retest(closes, level, tolerance):
    return abs(closes[-1] - level) <= tolerance


# ==============================
# DIRECTION (FIX)
# ==============================
def determine_direction(trend, structure, bos):

    if bos is None:
        return None

    # BOS ist primär
    direction = bos

    # wenn Trend dagegen ist → nur erlauben wenn Structure passt
    if trend != "neutral" and trend != bos:
        if structure == bos:
            return direction
        else:
            return None

    return direction


# ==============================
# STRUCTURE TP + SL
# ==============================
def calculate_sl_tp(direction, price, highs_5, lows_5, atr_value):

    MIN_SL_PIPS = 80
    MAX_SL_PIPS = 500

    # SL
    if direction == "bullish":
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

    if direction == "bullish":
        sl = price - sl_distance
    else:
        sl = price + sl_distance

    # STRUCTURE TP
    if direction == "bullish":
        target = max(highs_5[-20:])
        tp_distance = target - price
    else:
        target = min(lows_5[-20:])
        tp_distance = price - target

    # fallback wenn zu nah
    if tp_distance < sl_distance * 1.2:
        rr = 2
        if direction == "bullish":
            tp = price + sl_distance * rr
        else:
            tp = price - sl_distance * rr
    else:
        tp = target

    return {
        "sl": round(sl, 2),
        "tp": round(tp, 2)
    }


# ==============================
# SCORE SYSTEM (FIXED)
# ==============================
def calculate_score(direction, trend, structure, bos, sweep, zone, rsi_value, has_retest):

    score = 0

    if trend == direction:
        score += 2
    elif trend != "neutral":
        score -= 1

    if structure == direction:
        score += 2
    elif structure != "neutral":
        score -= 1

    if bos == direction:
        score += 2

    if has_retest:
        score += 2

    if sweep == direction:
        score += 1

    if (direction == "bullish" and zone == "discount") or \
       (direction == "bearish" and zone == "premium"):
        score += 1

    # RSI logisch
    if direction == "bullish" and 30 < rsi_value < 55:
        score += 1

    if direction == "bearish" and 45 < rsi_value < 70:
        score += 1

    return max(0, score)


# ==============================
# MAIN SIGNAL FUNCTION
# ==============================
def generate_signal(data_m5):

    data_m15 = get_candles("15min", 200)
    data_h1 = get_candles("1h", 200)

    if data_m15 is None or data_h1 is None:
        return None

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
    bos, bos_level = break_of_structure(highs_15, lows_15, closes_15)

    direction = determine_direction(trend, structure, bos)

    if direction is None:
        return None

    sweep = liquidity_sweep(highs_5, lows_5, closes_5)
    zone = premium_discount_zone(highs_15, lows_15, price)
    rsi_value = rsi(closes_5)
    atr_value = atr(highs_5, lows_5, closes_5)

    has_retest = False
    if bos_level:
        has_retest = retest(closes_5, bos_level, atr_value * 0.5)

    score = calculate_score(
        direction, trend, structure, bos,
        sweep, zone, rsi_value, has_retest
    )

    if score < SIGNAL_SCORE_THRESHOLD:
        return None

    display_direction = "BUY" if direction == "bullish" else "SELL"

    risk = calculate_sl_tp(direction, price, highs_5, lows_5, atr_value)

    return {
        "direction": display_direction,
        "entry": round(price, 2),
        "sl": risk["sl"],
        "tp": risk["tp"],
        "score": score,
        "notes": f"Trend: {trend} | BOS: {bos} | Zone: {zone} | Retest: {has_retest}"
    }