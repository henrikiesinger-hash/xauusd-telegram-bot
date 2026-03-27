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
# ENTRY ZONE (NEU)
# ==============================
def entry_zone(direction, price, highs, lows):

    high = max(highs[-20:])
    low = min(lows[-20:])
    range_size = high - low

    if direction == "bullish":
        # Discount Bereich
        entry_low = high - (range_size * 0.618)
        entry_high = high - (range_size * 0.5)
    else:
        # Premium Bereich
        entry_low = low + (range_size * 0.5)
        entry_high = low + (range_size * 0.618)

    return entry_low, entry_high


# ==============================
# ENTRY CHECK
# ==============================
def price_in_zone(price, zone_low, zone_high):
    return zone_low <= price <= zone_high


# ==============================
# SL / TP (Structure TP bleibt)
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
# MAIN
# ==============================
def generate_signal(data_m5):

    data_m15 = get_candles("15min", 200)
    data_h1 = get_candles("1h", 200)

    if not data_m15 or not data_h1:
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
    bos, level = break_of_structure(highs_15, lows_15, closes_15)

    if bos is None:
        return None

    direction = bos

    # ENTRY ZONE
    zone_low, zone_high = entry_zone(direction, price, highs_15, lows_15)

    if not price_in_zone(price, zone_low, zone_high):
        return None  # wartet auf besseren Entry

    rsi_value = rsi(closes_5)
    atr_value = atr(highs_5, lows_5, closes_5)

    score = 0

    if trend == direction:
        score += 2

    if structure == direction:
        score += 2

    if bos == direction:
        score += 2

    if 40 < rsi_value < 60:
        score += 1

    score += 1  # Entry Zone Bonus

    if score < SIGNAL_SCORE_THRESHOLD:
        return None

    display_direction = "BUY" if direction == "bullish" else "SELL"

    sl, tp = calculate_sl_tp(direction, price, highs_5, lows_5, atr_value)

    return {
        "direction": display_direction,
        "entry": round(price, 2),
        "sl": sl,
        "tp": tp,
        "score": score,
        "notes": f"Zone Entry | Trend: {trend} | BOS: {bos}"
    }