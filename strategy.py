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
    if len(highs) < 20 or len(lows) < 20 or len(closes) < 20:
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
    if len(highs) < 8 or len(lows) < 8 or len(closes) < 8:
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
    if len(opens) < 6 or len(highs) < 6 or len(lows) < 6 or len(closes) < 6:
        return None, None, None

    for i in range(-6, -1):
        if closes[i] < opens[i] and closes[i + 1] > highs[i]:
            return "bullish", lows[i], highs[i]

        if closes[i] > opens[i] and closes[i + 1] < lows[i]:
            return "bearish", lows[i], highs[i]

    return None, None, None


# ==============================
# FIBONACCI OTE
# ==============================
def fibonacci_ote(highs, lows, direction):
    if len(highs) < 20 or len(lows) < 20:
        return None, None

    swing_high = max(highs[-20:])
    swing_low = min(lows[-20:])

    if swing_high <= swing_low:
        return None, None

    if direction == "bullish":
        fib_62 = swing_high - (swing_high - swing_low) * 0.62
        fib_79 = swing_high - (swing_high - swing_low) * 0.79
        return min(fib_79, fib_62), max(fib_79, fib_62)

    fib_62 = swing_low + (swing_high - swing_low) * 0.62
    fib_79 = swing_low + (swing_high - swing_low) * 0.79
    return min(fib_62, fib_79), max(fib_62, fib_79)


# ==============================
# ENTRY ZONE CHECK
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
        candidates = [h for h in highs_15[-40:] if h > price]
        if not candidates:
            return None
        return min(candidates)

    candidates = [l for l in lows_15[-40:] if l < price]
    if not candidates:
        return None
    return max(candidates)


# ==============================
# RR CHOICE
# ==============================
def choose_rr(score, has_zone, ob_dir_match, sweep_match, bos_match):
    rr = 2.0

    strong_confluence = 0
    if has_zone:
        strong_confluence += 1
    if ob_dir_match:
        strong_confluence += 1
    if sweep_match:
        strong_confluence += 1
    if bos_match:
        strong_confluence += 1

    if score >= 8 and strong_confluence >= 3:
        rr = 3.0
    elif score >= 7 and strong_confluence >= 2:
        rr = 2.5

    return rr


# ==============================
# SL / TP WITH MIN RR 2
# ==============================
def calculate_sl_tp(direction, price, highs_5, lows_5, highs_15, lows_15, atr_value, rr_target):
    if len(highs_5) < 10 or len(lows_5) < 10:
        return None

    if direction == "bullish":
        sl = min(lows_5[-10:]) - atr_value * 0.3
        risk = price - sl

        if risk <= 0:
            return None

        structure_tp = find_structure_target(direction, highs_15, lows_15, price)
        rr_tp = price + (risk * rr_target)

        if structure_tp is not None and structure_tp > price:
            tp = max(structure_tp, rr_tp)
        else:
            tp = rr_tp

    else:
        sl = max(highs_5[-10:]) + atr_value * 0.3
        risk = sl - price

        if risk <= 0:
            return None

        structure_tp = find_structure_target(direction, highs_15, lows_15, price)
        rr_tp = price - (risk * rr_target)

        if structure_tp is not None and structure_tp < price:
            tp = min(structure_tp, rr_tp)
        else:
            tp = rr_tp

    real_rr = abs(tp - price) / risk if risk > 0 else 0

    if real_rr < 2.0:
        return None

    return {
        "sl": round(sl, 2),
        "tp": round(tp, 2),
        "rr": round(real_rr, 2)
    }


# ==============================
# MAIN SIGNAL FUNCTION
# ==============================
def generate_signal(data_m5):
    if not hasattr(generate_signal, "htf_data"):
        data_m15 = get_candles("15min")
        data_h1 = get_candles("1h")
        generate_signal.htf_data = (data_m15, data_h1)
    else:
        data_m15, data_h1 = generate_signal.htf_data

    if not data_m5 or not data_m15 or not data_h1:
        return None

    opens_5 = data_m5["open"]
    closes_5 = data_m5["close"]
    highs_5 = data_m5["high"]
    lows_5 = data_m5["low"]

    closes_15 = data_m15["close"]
    highs_15 = data_m15["high"]
    lows_15 = data_m15["low"]

    closes_h1 = data_h1["close"]

    if len(closes_5) < 20 or len(closes_15) < 20 or len(closes_h1) < 50:
        return None

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
    ob_dir_match = ob_dir == direction
    sweep_match = sweep == direction
    bos_match = bos == direction

    log.info(
        f"Trend: {trend} | Structure: {structure} | BOS: {bos} | "
        f"Sweep: {sweep} | OB: {ob_dir} | Price: {price}"
    )

    score = 0

    # Trend ist Basis
    score += 2

    # Structure
    if structure == direction:
        score += 2
    elif structure == "neutral":
        score += 0
    else:
        score -= 1

    # BOS
    if bos_match:
        score += 1

    # Sweep
    if sweep_match:
        score += 1

    # Orderblock
    if ob_dir_match:
        score += 2
    elif ob_dir is not None and ob_dir != direction:
        score -= 2

    # Entry zone
    if has_zone:
        score += 2
    else:
        log.info("⚠️ No perfect entry zone")
        score -= 2

    # RSI
    rsi_value = rsi(closes_5)

    if direction == "bullish" and 35 < rsi_value < 60:
        score += 1
    elif direction == "bearish" and 40 < rsi_value < 65:
        score += 1

    log.info(f"Score: {score}")

    if score < SIGNAL_SCORE_THRESHOLD:
        return None

    atr_value = atr(highs_5, lows_5, closes_5)
    rr_target = choose_rr(score, has_zone, ob_dir_match, sweep_match, bos_match)

    risk = calculate_sl_tp(
        direction=direction,
        price=price,
        highs_5=highs_5,
        lows_5=lows_5,
        highs_15=highs_15,
        lows_15=lows_15,
        atr_value=atr_value,
        rr_target=rr_target
    )

    if risk is None:
        log.info("❌ Trade rejected: real RR below 2.0")
        return None

    display_direction = "BUY" if direction == "bullish" else "SELL"

    log.info("✅ FINAL RR SIGNAL")

    return {
        "direction": display_direction,
        "entry": round(price, 2),
        "sl": risk["sl"],
        "tp": risk["tp"],
        "score": score,
        "notes": (
            f"Final RR Setup | Trend: {trend} | Structure: {structure} | "
            f"BOS: {bos} | Sweep: {sweep} | OB: {ob_dir} | "
            f"Zone: {has_zone} | RR: {risk['rr']}"
        )
    }