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
# TREND
# ==============================
def trend_direction(closes):
    if len(closes) < 200:
        return None, 0.0

    e21 = ema(closes, 21)
    e50 = ema(closes, 50)
    e200 = ema(closes, 200)

    if e21 > e50 > e200:
        return "bullish", 1.0
    if e21 < e50 < e200:
        return "bearish", 1.0
    if e50 > e200:
        return "bullish", 0.5
    if e50 < e200:
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
def detect_orderblock(highs, lows, opens, closes, direction):
    for i in range(len(closes) - 20, len(closes) - 2):
        body = abs(opens[i] - closes[i])
        if body == 0:
            continue

        if direction == "bullish" and closes[i] < opens[i]:
            if max(highs[i+1:i+4]) - lows[i] > body * 2:
                return direction, lows[i], highs[i], 1.0

        if direction == "bearish" and closes[i] > opens[i]:
            if highs[i] - min(lows[i+1:i+4]) > body * 2:
                return direction, lows[i], highs[i], 1.0

    return None, None, None, 0.0


# ==============================
# HELPERS
# ==============================
def in_entry_zone(price, low, high):
    if low is None or high is None:
        return False
    return low <= price <= high


def liquidity_sweep(highs, lows, closes):
    if highs[-1] > max(highs[-10:-1]) and closes[-1] < highs[-2]:
        return "bearish"
    if lows[-1] < min(lows[-10:-1]) and closes[-1] > lows[-2]:
        return "bullish"
    return None


def premium_discount(highs, lows, price):
    hi = max(highs[-50:])
    lo = min(lows[-50:])
    pct = (price - lo) / (hi - lo)

    if pct > 0.65:
        return "premium"
    if pct < 0.35:
        return "discount"
    return "mid"


# ==============================
# SCORE
# ==============================
def calculate_score(direction, trend, structure, bos, ob_dir, zone, rsi_val):
    score = 0.0

    if trend == direction:
        score += 2.0

    if structure == direction:
        score += 2.0
    elif structure == "ranging":
        score += 0.5

    if bos == direction:
        score += 2.0
    elif bos is None:
        score += 0.5

    if ob_dir == direction:
        score += 1.5

    if zone == ("discount" if direction == "bullish" else "premium"):
        score += 0.5

    if direction == "bullish" and 30 < rsi_val < 55:
        score += 0.5
    elif direction == "bearish" and 45 < rsi_val < 70:
        score += 0.5

    return round(score, 1)


# ==============================
# MAIN
# ==============================
def generate_signal(data_m5):

    if not hasattr(generate_signal, "cache"):
        generate_signal.cache = (
            get_candles("15min"),
            get_candles("1h")
        )

    m15, h1 = generate_signal.cache

    if m15 is None or h1 is None:
        return None

    c5, h5, l5, o5 = data_m5["close"], data_m5["high"], data_m5["low"], data_m5["open"]
    c15, h15, l15, o15 = m15["close"], m15["high"], m15["low"], m15["open"]
    c1 = h1["close"]

    price = c5[-1]

    trend, _ = trend_direction(c1)
    structure, _ = market_structure(h15, l15)
    bos, _ = detect_bos(h15, l15, c15)

    # DIRECTION FIX
    if bos:
        direction = bos
    elif structure == trend:
        direction = trend
    else:
        direction = trend  # fallback

    if direction is None:
        return None

    ob_dir, ob_low, ob_high, _ = detect_orderblock(h15, l15, o15, c15, direction)

    at_ob = in_entry_zone(price, ob_low, ob_high)

    sweep = liquidity_sweep(h5, l5, c5)
    zone = premium_discount(h15, l15, price)
    rsi_val = rsi(c5)

    score = calculate_score(direction, trend, structure, bos, ob_dir, zone, rsi_val)

    # ENTRY FIX
    if at_ob:
        if score < 5.0:
            return None
    else:
        if score < 6.0:
            return None

    # SL TP
    if direction == "bullish":
        sl = price - 2
        tp = price + 4
    else:
        sl = price + 2
        tp = price - 4

    return {
        "direction": "BUY" if direction == "bullish" else "SELL",
        "entry": round(price, 2),
        "sl": round(sl, 2),
        "tp": round(tp, 2),
        "score": score,
        "confidence": "HIGH" if score >= 7 else "MODERATE"
    }