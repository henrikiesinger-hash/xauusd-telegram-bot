import logging
from indicators import ema, rsi
from data import get_candles

log = logging.getLogger("strategy")


# ==============================
# SWING POINTS
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
def market_structure(highs, lows):
    sh = find_swing_highs(highs)
    sl = find_swing_lows(lows)

    if len(sh) < 2 or len(sl) < 2:
        return "ranging", 0.0

    hh = sh[-1][1] > sh[-2][1]
    hl = sl[-1][1] > sl[-2][1]
    lh = sh[-1][1] < sh[-2][1]
    ll = sl[-1][1] < sl[-2][1]

    if hh and hl:
        return "bullish", 1.0
    if lh and ll:
        return "bearish", 1.0

    return "ranging", 0.3


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
# BOS
# ==============================
def detect_bos(highs, lows, closes):
    sh = find_swing_highs(highs)
    sl = find_swing_lows(lows)

    if not sh or not sl:
        return None, None

    if closes[-1] > sh[-1][1]:
        return "bullish", sh[-1][1]

    if closes[-1] < sl[-1][1]:
        return "bearish", sl[-1][1]

    return None, None


# ==============================
# ORDERBLOCK
# ==============================
def detect_orderblock(highs, lows, opens, closes, direction, lookback=20):
    if len(closes) < lookback + 4:
        return None, None, None, 0.0

    start = max(0, len(closes) - lookback)
    best = None

    for i in range(start, len(closes) - 3):
        body = abs(opens[i] - closes[i])
        if body == 0:
            continue

        # Bullish OB = letzte rote Kerze vor impulsivem Upmove
        if direction == "bullish" and closes[i] < opens[i]:
            future_high = max(highs[i + 1:i + 4])
            displacement = future_high - highs[i]
            if displacement > body * 1.5:
                strength = min(1.0, displacement / (body * 3))
                best = (lows[i], highs[i], strength)

        # Bearish OB = letzte grüne Kerze vor impulsivem Downmove
        if direction == "bearish" and closes[i] > opens[i]:
            future_low = min(lows[i + 1:i + 4])
            displacement = lows[i] - future_low
            if displacement > body * 1.5:
                strength = min(1.0, displacement / (body * 3))
                best = (lows[i], highs[i], strength)

    if best is None:
        return None, None, None, 0.0

    return direction, best[0], best[1], best[2]


# ==============================
# LIQUIDITY SWEEP
# ==============================
def liquidity_sweep(highs, lows, closes):
    if len(highs) < 10 or len(lows) < 10 or len(closes) < 10:
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
    if len(highs) < 50 or len(lows) < 50:
        return "equilibrium"

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
# ATR
# ==============================
def calculate_atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return 0.0

    trs = []
    for i in range(-period, 0):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )
        trs.append(tr)

    return sum(trs) / len(trs)


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
        tp = price + sl_dist * 3.0
    else:
        sl = price + sl_dist
        tp = price - sl_dist * 3.0

    return round(sl, 2), round(tp, 2)


# ==============================
# MAIN SIGNAL
# ==============================
def generate_signal(data_m5):
    if not hasattr(generate_signal, "htf_cache"):
        generate_signal.htf_cache = (
            get_candles("15min"),
            get_candles("1h")
        )

    data_m15, data_h1 = generate_signal.htf_cache

    if data_m15 is None or data_h1 is None:
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

    trend, _ = trend_direction(c_h1)
    structure, _ = market_structure(h15, l15)
    bos, bos_level = detect_bos(h15, l15, c15)

    if trend is None:
        return None

    # Direction logic
    direction = None

    if bos is not None:
        if bos == trend:
            direction = bos
        elif structure == bos:
            direction = bos
    elif trend == structure and structure != "ranging":
        direction = trend
    else:
        direction = trend  # fallback

    if direction is None:
        return None

    # Orderblock
    ob_dir, ob_low, ob_high, ob_strength = detect_orderblock(
        h15, l15, o15, c15, direction
    )

    at_ob = in_entry_zone(price, ob_low, ob_high)

    # Confirmations
    sweep = liquidity_sweep(h5, l5, c5)
    zone = premium_discount(h15, l15, price)
    rsi_val = rsi(c5)

    has_retest = False
    if bos_level is not None:
        atr_val = calculate_atr(h5, l5, c5)
        if atr_val > 0 and abs(price - bos_level) <= atr_val:
            has_retest = True

    # ==============================
    # SMART SNIPER SCORING
    # ==============================
    score = 0.0

    if trend == direction:
        score += 1.5

    if structure == direction:
        score += 1.5
    elif structure == "ranging":
        score += 0.5

    if bos == direction:
        score += 1.5
    elif bos is None:
        score += 0.5

    if ob_dir == direction:
        score += 1.5 * ob_strength

    if at_ob:
        score += 2.0
    else:
        score -= 1.0

    if has_retest:
        score += 2.0

    if sweep == direction:
        score += 1.5

    if direction == "bullish" and zone == "discount":
        score += 1.0
    elif direction == "bearish" and zone == "premium":
        score += 1.0

    if direction == "bullish" and 30 < rsi_val < 60:
        score += 1.0
    elif direction == "bearish" and 40 < rsi_val < 70:
        score += 1.0

    score = round(score, 1)

    # ==============================
    # ENTRY THRESHOLD
    # ==============================
    if score < 3.0:
        return None

    sl, tp = calculate_sl_tp(direction, price, h5, l5, c5)

    if score >= 7.5:
        confidence = "SNIPER"
    elif score >= 5.5:
        confidence = "HIGH"
    else:
        confidence = "MODERATE"

    signal = {
        "direction": "BUY" if direction == "bullish" else "SELL",
        "entry": round(price, 2),
        "sl": sl,
        "tp": tp,
        "score": score,
        "confidence": confidence,
        "notes": "Weighted Sniper Setup"
    }

    log.info("SIGNAL: %s", signal)
    return signal