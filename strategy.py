import logging
from indicators import ema, rsi

log = logging.getLogger("strategy")


# ==============================
# TREND
# ==============================
def trend_direction(closes):
    if ema(closes, 50) > ema(closes, 200):
        return "bullish"
    elif ema(closes, 50) < ema(closes, 200):
        return "bearish"
    return None


# ==============================
# STRUCTURE
# ==============================
def structure_direction(highs, lows):
    if max(highs[-10:]) > max(highs[-20:-10]):
        return "bullish"
    elif min(lows[-10:]) < min(lows[-20:-10]):
        return "bearish"
    return None


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

    for i in range(-5, -1):

        if closes[i] < opens[i] and closes[i+1] > highs[i]:
            return "bullish", lows[i], highs[i]

        if closes[i] > opens[i] and closes[i+1] < lows[i]:
            return "bearish", lows[i], highs[i]

    return None, None, None


# ==============================
# ENTRY ZONE
# ==============================
def in_entry_zone(price, ob_low, ob_high):

    if ob_low is None or ob_high is None:
        return False

    return ob_low <= price <= ob_high


# ==============================
# SL / TP
# ==============================
def calculate_sl_tp(direction, price, highs, lows):

    if direction == "bullish":
        sl = min(lows[-10:])
        risk = price - sl
        if risk <= 0:
            return None, None
        tp = price + (risk * 2)

    else:
        sl = max(highs[-10:])
        risk = sl - price
        if risk <= 0:
            return None, None
        tp = price - (risk * 2)

    return round(sl, 2), round(tp, 2)


# ==============================
# MAIN
# ==============================
def generate_signal(data):

    closes = data["close"]
    highs = data["high"]
    lows = data["low"]
    opens = data["open"]

    price = closes[-1]

    trend = trend_direction(closes)
    structure = structure_direction(highs, lows)
    sweep = liquidity_sweep(highs, lows, closes)
    ob_dir, ob_low, ob_high = orderblock(highs, lows, opens, closes)

    log.info(f"Trend: {trend} | Structure: {structure} | Sweep: {sweep} | OB: {ob_dir} | Price: {price}")

    # ❌ FILTER 1: Trend = Structure
    if trend is None or structure is None:
        return None

    if trend != structure:
        return None

    direction = trend

    # ❌ FILTER 2: OB muss passen
    if ob_dir != direction:
        return None

    # ❌ FILTER 3: ENTRY ZONE
    if not in_entry_zone(price, ob_low, ob_high):
        return None

    # ==============================
    # CONFLUENCE
    # ==============================
    confluence = 1  # OB zählt

    if sweep == direction:
        confluence += 1

    # ❌ FILTER 4: MIN 2 CONF
    if confluence < 2:
        return None

    log.info(f"🔥 SNIPER SETUP | Conf: {confluence}")

    # ==============================
    # SL / TP
    # ==============================
    sl, tp = calculate_sl_tp(direction, price, highs, lows)

    if sl is None:
        return None

    display_direction = "BUY" if direction == "bullish" else "SELL"

    log.info("✅ SNIPER SIGNAL")

    return {
        "direction": display_direction,
        "entry": round(price, 2),
        "sl": sl,
        "tp": tp,
        "score": confluence,
        "notes": f"Phase 7 Sniper | RR 2.0"
    }