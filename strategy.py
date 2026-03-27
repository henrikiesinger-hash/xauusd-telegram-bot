from indicators import ema, rsi, atr
from config import SIGNAL_SCORE_THRESHOLD
from data import get_candles
import logging

log = logging.getLogger("strategy")


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
# STRUCTURE
# ==============================
def market_structure(highs, lows):
    if len(highs) < 20 or len(lows) < 20:
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
    if len(highs) < 8:
        return None

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
    if len(opens) < 6:
        return None, None, None

    for i in range(-6, -1):
        if closes[i] < opens[i] and closes[i + 1] > highs[i]:
            return "bullish", lows[i], highs[i]

        if closes[i] > opens[i] and closes[i + 1] < lows[i]:
            return "bearish", lows[i], highs[i]

    return None, None, None


# ==============================
# FIBONACCI
# ==============================
def fibonacci_ote(highs, lows, direction):
    swing_high = max(highs[-20:])
    swing_low = min(lows[-20:])

    if direction == "bullish":
        fib_62 = swing_high - (swing_high - swing_low) * 0.62
        fib_79 = swing_high - (swing_high - swing_low) * 0.79
        return min(fib_79, fib_62), max(fib_79, fib_62)

    fib_62 = swing_low + (swing_high - swing_low) * 0.62
    fib_79 = swing_low + (swing_high - swing_low) * 0.79
    return min(fib_62, fib_79), max(fib_62, fib_79)


# ==============================
# ENTRY ZONE
# ==============================
def in_entry_zone(price, ob_low, ob_high, fib_low, fib_high):
    in_ob = ob_low is not None and ob_high is not None and ob_low <= price <= ob_high
    in_fib = fib_low is not None and fib_high is not None and fib_low <= price <= fib_high
    return in_ob or in_fib


# ==============================
# STRUCTURE TARGET
# ==============================
def find_structure_target(direction, highs_15, lows_15, price):
    if direction == "bullish":
        targets = [h for h in highs_15[-40:] if h > price]
        return min(targets) if targets else None

    targets = [l for l in lows_15[-40:] if l < price]
    return max(targets) if targets else None


# ==============================
# SL TP
# ==============================
def calculate_sl_tp(direction, price, highs_5, lows_5, highs_15, lows_15, atr_value):
    if direction == "bullish":
        sl = min(lows_5[-10:]) - atr_value * 0.3
        risk = price - sl
        if risk <= 0:
            return None

        tp = price + risk * 2
        structure_tp = find_structure_target(direction, highs_15, lows_15, price)

        if structure_tp:
            tp = max(tp, structure_tp)

    else:
        sl = max(highs_5[-10:]) + atr_value * 0.3
        risk = sl - price
        if risk <= 0:
            return None

        tp = price - risk * 2
        structure_tp = find_structure_target(direction, highs_15, lows_15, price)

        if structure_tp:
            tp = min(tp, structure_tp)

    rr = abs(tp - price) / risk if risk > 0 else 0

    if rr < 2:
        return None

    return {"sl": round(sl, 2), "tp": round(tp, 2), "rr": round(rr, 2)}


# ==============================
# MAIN
# ==============================
def generate_signal(data_m5):
    if not hasattr(generate_signal, "htf_data"):
        generate_signal.htf_data = (
            get_candles("15min"),
            get_candles("1h")
        )

    data_m15, data_h1 = generate_signal.htf_data

    if not data_m5 or not data_m15 or not data_h1:
        return None

    closes_5 = data_m5["close"]
    highs_5 = data_m5["high"]
    lows_5 = data_m5["low"]
    opens_5 = data_m5["open"]

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

    has_zone = in_entry_zone(price, ob_low, ob_high, fib_low, fib_high)

    # ❌ FINAL FILTERS
    if not has_zone:
        return None

    if ob_dir != direction:
        return None

    confluence = 0
    if bos == direction:
        confluence += 1
    if sweep == direction:
        confluence += 1
    if structure == direction:
        confluence += 1

    if confluence < 2:
        return None

    log.info(f"🔥 FINAL FILTER PASSED | Trend: {trend} | OB: {ob_dir} | Confluence: {confluence}")

    score = 5 + confluence

    atr_value = atr(highs_5, lows_5, closes_5)

    risk = calculate_sl_tp(
        direction,
        price,
        highs_5,
        lows_5,
        highs_15,
        lows_15,
        atr_value
    )

    if risk is None:
        return None

    display_direction = "BUY" if direction == "bullish" else "SELL"

    return {
        "direction": display_direction,
        "entry": round(price, 2),
        "sl": risk["sl"],
        "tp": risk["tp"],
        "score": score,
        "notes": f"FINAL SNIPER | RR: {risk['rr']} | Conf: {confluence}"
    }