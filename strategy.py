from indicators import ema, rsi, atr
from config import SIGNAL_SCORE_THRESHOLD
from data import get_candles
import logging

log = logging.getLogger("strategy")


def higher_timeframe_trend(closes):
    if ema(closes, 50) > ema(closes, 200):
        return "bullish"
    elif ema(closes, 50) < ema(closes, 200):
        return "bearish"
    return "neutral"


def market_structure(highs, lows):
    if max(highs[-10:]) > max(highs[-20:-10]) and min(lows[-10:]) > min(lows[-20:-10]):
        return "bullish"
    elif max(highs[-10:]) < max(highs[-20:-10]) and min(lows[-10:]) < min(lows[-20:-10]):
        return "bearish"
    return "neutral"


def break_of_structure(highs, lows, closes):
    prev_high = max(highs[-20:-2])
    prev_low = min(lows[-20:-2])

    if closes[-1] > prev_high:
        return "bullish", prev_high
    elif closes[-1] < prev_low:
        return "bearish", prev_low

    return None, None


def liquidity_sweep(highs, lows, closes):
    prev_high = max(highs[-8:-1])
    prev_low = min(lows[-8:-1])

    if highs[-1] > prev_high and closes[-1] < prev_high:
        return "bearish"

    if lows[-1] < prev_low and closes[-1] > prev_low:
        return "bullish"

    return None


def orderblock(highs, lows, opens, closes):
    for i in range(-5, -1):
        if closes[i] < opens[i] and closes[i+1] > highs[i]:
            return "bullish", lows[i], highs[i]

        if closes[i] > opens[i] and closes[i+1] < lows[i]:
            return "bearish", lows[i], highs[i]

    return None, None, None


def price_in_ob(price, ob_low, ob_high):
    if ob_low is None:
        return False
    return ob_low <= price <= ob_high


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

    # 🔥 FIX: HTF DATA CACHE (RICHTIG EINGERÜCKT!)
    if not hasattr(generate_signal, "htf_data"):
        data_m15 = get_candles("15min")
        data_h1 = get_candles("1h")
        generate_signal.htf_data = (data_m15, data_h1)
    else:
        data_m15, data_h1 = generate_signal.htf_data

    if not data_m15 or not data_h1:
        log.info("❌ No HTF data")
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
    bos, level = break_of_structure(highs_15, lows_15, closes_15)

    log.info(f"Trend: {trend} | Structure: {structure} | BOS: {bos}")

    if bos is None:
        log.info("❌ No BOS")
        return None

    direction = bos

    sweep = liquidity_sweep(highs_5, lows_5, closes_5)
    ob_dir, ob_low, ob_high = orderblock(highs_5, lows_5, opens_5, closes_5)

    if sweep != direction:
        log.info("❌ Sweep mismatch")
        return None

    if ob_dir != direction:
        log.info("❌ OB mismatch")
        return None

    if not price_in_ob(price, ob_low, ob_high):
        log.info("❌ Price not in OB")
        return None

    rsi_value = rsi(closes_5)
    atr_value = atr(highs_5, lows_5, closes_5)

    score = 0

    if trend == direction:
        score += 2

    if structure == direction:
        score += 2

    if bos == direction:
        score += 2

    score += 2

    if 40 < rsi_value < 60:
        score += 1

    log.info(f"Score: {score}")

    if score < SIGNAL_SCORE_THRESHOLD:
        log.info("❌ Score too low")
        return None

    display_direction = "BUY" if direction == "bullish" else "SELL"

    sl, tp = calculate_sl_tp(direction, price, highs_5, lows_5, atr_value)

    log.info("✅ SIGNAL GENERATED")

    return {
        "direction": display_direction,
        "entry": round(price, 2),
        "sl": sl,
        "tp": tp,
        "score": score,
        "notes": "Sweep + OB"
    }