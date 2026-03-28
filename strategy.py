import logging
import time
from indicators import ema, rsi
from data import get_candles

log = logging.getLogger("strategy")

# ==============================
# CONFIG
# ==============================

BACKTEST_MODE = False
SCORE_THRESHOLD = 7.0
COOLDOWN_CANDLES = 12
LONDON_OPEN_UTC = 7
NY_CLOSE_UTC = 21
SL_MIN = 1.50
SL_MAX = 8.00

_last_signal_time = 0
_last_signal_candle = -999
_htf_cache = {"data": None, "ts": 0}
HTF_CACHE_TTL = 300

# ==============================
# SESSION
# ==============================

def is_active_session():
    hour = int(time.strftime("%H", time.gmtime()))
    return LONDON_OPEN_UTC <= hour < NY_CLOSE_UTC

# ==============================
# COOLDOWN
# ==============================

def is_in_cooldown_live():
    global _last_signal_time
    return (time.time() - _last_signal_time) < (COOLDOWN_CANDLES * 300)

def is_in_cooldown_backtest(candle_index):
    global _last_signal_candle
    return (candle_index - _last_signal_candle) < COOLDOWN_CANDLES

def record_signal_live():
    global _last_signal_time
    _last_signal_time = time.time()

def record_signal_backtest(candle_index):
    global _last_signal_candle
    _last_signal_candle = candle_index

# ==============================
# HTF CACHE
# ==============================

def get_htf_data():
    global _htf_cache
    now = time.time()

    if _htf_cache["data"] and (now - _htf_cache["ts"]) < HTF_CACHE_TTL:
        return _htf_cache["data"]

    m15 = get_candles("15min")
    h1 = get_candles("1h")

    if not m15 or not h1:
        return None

    _htf_cache["data"] = (m15, h1)
    _htf_cache["ts"] = now

    return (m15, h1)

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
    if hh or hl:
        return "bullish", 0.5
    if lh or ll:
        return "bearish", 0.5

    return "ranging", 0.0

# ==============================
# TREND
# ==============================

def trend_direction(closes):
    if len(closes) < 200:
        return None

    e50 = ema(closes, 50)
    e200 = ema(closes, 200)

    if e50 > e200:
        return "bullish"
    if e50 < e200:
        return "bearish"

    return None

# ==============================
# BOS
# ==============================

def detect_bos(highs, lows, closes):
    sh = find_swing_highs(highs)
    sl = find_swing_lows(lows)

    if not sh or not sl:
        return None

    if closes[-1] > sh[-1][1]:
        return "bullish"
    if closes[-1] < sl[-1][1]:
        return "bearish"

    return None

# ==============================
# ORDERBLOCK (FIXED: latest)
# ==============================

def detect_orderblock(highs, lows, opens, closes, direction):
    if len(closes) < 22:
        return None, None

    best = None

    for i in range(len(closes) - 20, len(closes) - 2):

        body = abs(opens[i] - closes[i])
        if body < 0.01:
            continue

        if direction == "bullish" and closes[i] < opens[i]:
            future_high = max(highs[i + 1:i + 4])
            displacement = future_high - lows[i]

            if displacement > body * 2:
                mitigated = any(closes[j] < lows[i] for j in range(i + 1, len(closes)))
                if not mitigated:
                    best = (lows[i], highs[i])

        if direction == "bearish" and closes[i] > opens[i]:
            future_low = min(lows[i + 1:i + 4])
            displacement = highs[i] - future_low

            if displacement > body * 2:
                mitigated = any(closes[j] > highs[i] for j in range(i + 1, len(closes)))
                if not mitigated:
                    best = (lows[i], highs[i])

    if best is None:
        return None, None

    return best[0], best[1]

# ==============================
# ATR
# ==============================

def calculate_atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return 3.0

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
# SCORE SYSTEM
# ==============================

def calculate_score(direction, trend, structure, struct_str, bos, at_ob, sweep, zone, rsi_val):
    score = 0.0
    parts = []

    if trend == direction:
        score += 2.0
        parts.append("Trend +2")
    else:
        score -= 1.0
        parts.append("Trend AGAINST -1")

    if structure == direction:
        pts = 1.0 + struct_str
        score += pts
        parts.append("Struct +" + str(pts))
    elif structure != "ranging":
        score -= 1.0
        parts.append("Struct AGAINST -1")

    if bos == direction:
        score += 2.0
        parts.append("BOS +2")

    if at_ob:
        score += 1.5
        parts.append("OB +1.5")

    if sweep == direction:
        score += 0.5
        parts.append("Sweep +0.5")

    good_zone = (
        (direction == "bullish" and zone == "discount") or
        (direction == "bearish" and zone == "premium")
    )
    if good_zone:
        score += 0.5
        parts.append("Zone +0.5")

    if direction == "bullish" and 30 < rsi_val < 55:
        score += 0.5
        parts.append("RSI +0.5")
    elif direction == "bearish" and 45 < rsi_val < 70:
        score += 0.5
        parts.append("RSI +0.5")

    return max(0.0, round(score, 1)), parts

# ==============================
# MAIN SIGNAL (WITH DEBUG)
# ==============================

def generate_signal(data_m5, candle_index=0):

    if not BACKTEST_MODE and not is_active_session():
        log.info("BLOCKED: outside session")
        return None

    if BACKTEST_MODE:
        if is_in_cooldown_backtest(candle_index):
            log.info("BLOCKED: cooldown")
            return None
    else:
        if is_in_cooldown_live():
            log.info("BLOCKED: cooldown")
            return None

    if BACKTEST_MODE:
        m15 = get_candles("15min")
        h1 = get_candles("1h")
        if not m15 or not h1:
            log.info("BLOCKED: no HTF")
            return None
    else:
        htf = get_htf_data()
        if htf is None:
            log.info("BLOCKED: HTF cache")
            return None
        m15, h1 = htf

    c5 = data_m5["close"]
    h5 = data_m5["high"]
    l5 = data_m5["low"]

    c15 = m15["close"]
    h15 = m15["high"]
    l15 = m15["low"]
    o15 = m15["open"]

    c1 = h1["close"]
    price = c5[-1]

    trend = trend_direction(c1)
    if trend is None:
        log.info("BLOCKED: no trend")
        return None

    structure, struct_str = market_structure(h15, l15)
    bos = detect_bos(h15, l15, c15)

    direction = None
    if bos and bos == trend:
        direction = bos
    elif structure == trend and structure != "ranging":
        direction = trend

    if direction is None:
        log.info("BLOCKED: no direction")
        return None

    rsi_val = rsi(c5)

    if direction == "bullish" and rsi_val > 60:
        log.info("BLOCKED: RSI high")
        return None
    if direction == "bearish" and rsi_val < 40:
        log.info("BLOCKED: RSI low")
        return None

    ob_low, ob_high = detect_orderblock(h15, l15, o15, c15, direction)
    if ob_low is None:
        log.info("BLOCKED: no OB")
        return None

    if not (ob_low <= price <= ob_high):
        log.info("BLOCKED: not in OB")
        return None

    sweep = liquidity_sweep(h5, l5, c5)
    zone = premium_discount(h15, l15, price)

    score, parts = calculate_score(
        direction, trend, structure, struct_str, bos,
        True, sweep, zone, rsi_val
    )

    log.info("CHECK: %.2f %s score %.1f | %s", price, direction, score, " | ".join(parts))

    if score < SCORE_THRESHOLD:
        log.info("BLOCKED: score too low")
        return None

    sl, tp1, tp2, sl_dist = calculate_sl_tp(direction, price, h5, l5, c5)

    display = "BUY" if direction == "bullish" else "SELL"

    if BACKTEST_MODE:
        record_signal_backtest(candle_index)
    else:
        record_signal_live()

    log.info("SIGNAL: %s @ %.2f", display, price)

    return {
        "direction": display,
        "entry": round(price, 2),
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "sl_dist": sl_dist,
        "score": score,
        "confidence": "SNIPER" if score >= 8.5 else "HIGH" if score >= 7 else "MODERATE",
        "notes": " | ".join(parts),
    }