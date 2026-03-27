import logging
import time
from indicators import ema, rsi
from data import get_candles

log = logging.getLogger("strategy")

# ==============================
# CONFIG
# ==============================
SCORE_THRESHOLD = 6.5
COOLDOWN_SECONDS = 3600
LONDON_OPEN_UTC = 7
NY_CLOSE_UTC = 21
MIN_SL = 0.80
MAX_SL = 5.00

_last_signal_time = 0
_htf_cache = {"data": None, "timestamp": 0}
HTF_CACHE_TTL = 300

# ==============================
# SESSION FILTER
# ==============================
def is_active_session():
    hour = int(time.strftime("%H", time.gmtime()))
    return LONDON_OPEN_UTC <= hour < NY_CLOSE_UTC

# ==============================
# COOLDOWN
# ==============================
def is_in_cooldown():
    global _last_signal_time
    return (time.time() - _last_signal_time) < COOLDOWN_SECONDS

def record_signal():
    global _last_signal_time
    _last_signal_time = time.time()

# ==============================
# HTF DATA (CACHE)
# ==============================
def get_htf_data():
    global _htf_cache
    now = time.time()

    if _htf_cache["data"] is not None and (now - _htf_cache["timestamp"]) < HTF_CACHE_TTL:
        return _htf_cache["data"]

    m15 = get_candles("15min")
    h1 = get_candles("1h")

    if m15 is None or h1 is None:
        return None

    _htf_cache["data"] = (m15, h1)
    _htf_cache["timestamp"] = now
    return (m15, h1)

# ==============================
# SWINGS
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
# STRUCTURE
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
    if len(closes) < 22:
        return None, None, None, 0.0

    best = None

    for i in range(len(closes) - 20, len(closes) - 2):
        body = abs(opens[i] - closes[i])
        if body < 0.01:
            continue

        if direction == "bullish" and closes[i] < opens[i]:
            future_high = max(highs[i + 1:i + 4])
            if (future_high - lows[i]) > body * 2:
                best = (lows[i], highs[i], 1.0, i)

        if direction == "bearish" and closes[i] > opens[i]:
            future_low = min(lows[i + 1:i + 4])
            if (highs[i] - future_low) > body * 2:
                best = (lows[i], highs[i], 1.0, i)

    if best is None:
        return None, None, None, 0.0

    return direction, best[0], best[1], best[2]

# ==============================
# HELPERS
# ==============================
def in_entry_zone(price, low, high):
    if low is None or high is None:
        return False
    return low <= price <= high

def liquidity_sweep(highs, lows, closes):
    if len(highs) < 10:
        return None
    if highs[-1] > max(highs[-10:-1]) and closes[-1] < highs[-2]:
        return "bearish"
    if lows[-1] < min(lows[-10:-1]) and closes[-1] > lows[-2]:
        return "bullish"
    return None

def premium_discount(highs, lows, price):
    hi = max(highs[-50:])
    lo = min(lows[-50:])
    if hi == lo:
        return "mid"
    pct = (price - lo) / (hi - lo)
    if pct > 0.65:
        return "premium"
    if pct < 0.35:
        return "discount"
    return "mid"

# ==============================
# ATR
# ==============================
def calculate_atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return 2.0
    tr_list = []
    for i in range(-period, 0):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )
        tr_list.append(tr)
    return sum(tr_list) / len(tr_list)

# ==============================
# SL TP
# ==============================
def calculate_sl_tp(direction, price, highs, lows, closes):
    atr_val = calculate_atr(highs, lows, closes)

    if direction == "bullish":
        raw_sl = min(lows[-10:]) - atr_val * 0.3
        sl_dist = price - raw_sl
    else:
        raw_sl = max(highs[-10:]) + atr_val * 0.3
        sl_dist = raw_sl - price

    sl_dist = max(MIN_SL, min(MAX_SL, sl_dist))

    if direction == "bullish":
        sl = price - sl_dist
        tp1 = price + sl_dist * 2
        tp2 = price + sl_dist * 3
    else:
        sl = price + sl_dist
        tp1 = price - sl_dist * 2
        tp2 = price - sl_dist * 3

    return round(sl, 2), round(tp1, 2), round(tp2, 2), round(sl_dist * 100)

# ==============================
# SCORE
# ==============================
def calculate_score(direction, trend, structure, bos, ob_dir, ob_str, sweep, zone, rsi_val):
    score = 0.0

    if trend == direction:
        score += 2
    if structure == direction:
        score += 2
    if bos == direction:
        score += 2
    if ob_dir == direction:
        score += 1.5
    if sweep == direction:
        score += 0.5

    return round(score, 1), ["Weighted Sniper Setup"]

# ==============================
# MAIN
# ==============================
def generate_signal(data_m5):

    if not is_active_session():
        return None

    if is_in_cooldown():
        return None

    htf = get_htf_data()
    if htf is None:
        return None

    m15, h1 = htf

    c5 = data_m5["close"]
    h5 = data_m5["high"]
    l5 = data_m5["low"]
    o5 = data_m5["open"]

    c15 = m15["close"]
    h15 = m15["high"]
    l15 = m15["low"]
    o15 = m15["open"]

    c1 = h1["close"]

    price = c5[-1]

    trend, _ = trend_direction(c1)
    structure, _ = market_structure(h15, l15)
    bos, _ = detect_bos(h15, l15, c15)

    direction = trend if trend == structure else None
    if direction is None:
        return None

    ob_dir, ob_low, ob_high, ob_str = detect_orderblock(h15, l15, o15, c15, direction)

    if ob_dir is None:
        return None

    if not in_entry_zone(price, ob_low, ob_high):
        return None

    sweep = liquidity_sweep(h5, l5, c5)
    zone = premium_discount(h15, l15, price)
    rsi_val = rsi(c5)

    score, parts = calculate_score(
        direction, trend, structure, bos, ob_dir, ob_str, sweep, zone, rsi_val
    )

    if score < SCORE_THRESHOLD:
        return None

    sl, tp1, tp2, sl_pips = calculate_sl_tp(direction, price, h5, l5, c5)

    record_signal()

    return {
        "direction": "BUY" if direction == "bullish" else "SELL",
        "entry": round(price, 2),
        "sl": sl,
        "tp": tp1,
        "tp2": tp2,
        "sl_pips": sl_pips,
        "score": score,
        "confidence": "HIGH" if score >= 7 else "MODERATE",
        "notes": " | ".join(parts),
    }