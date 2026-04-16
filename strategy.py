import logging
import time
from indicators import ema, rsi
from data import get_candles

log = logging.getLogger("strategy")

# ==============================
# CONFIG
# ==============================

BACKTEST_MODE = False
SCORE_THRESHOLD = 6.0

COOLDOWN_AFTER_WIN = 24
COOLDOWN_AFTER_LOSS = 48
_last_trade_result = "WIN"

LONDON_OPEN_UTC = 7
NY_CLOSE_UTC = 21

_last_signal_time = 0
_last_signal_candle = -999
_used_ob = None
_htf_cache = {"data": None, "ts": 0}
HTF_CACHE_TTL = 300

# ==============================
# SESSION
# ==============================

def is_active_session():
    now = time.gmtime()
    weekday = now.tm_wday
    hour = now.tm_hour

    if weekday >= 5:
        return False

    return LONDON_OPEN_UTC <= hour < NY_CLOSE_UTC

# ==============================
# COOLDOWN
# ==============================

def is_in_cooldown_live():
    global _last_signal_time, _last_trade_result

    if _last_trade_result == "LOSS":
        cooldown = COOLDOWN_AFTER_LOSS * 300
    else:
        cooldown = COOLDOWN_AFTER_WIN * 300

    return (time.time() - _last_signal_time) < cooldown

def is_in_cooldown_backtest(candle_index):
    global _last_signal_candle
    return (candle_index - _last_signal_candle) < COOLDOWN_AFTER_WIN

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
# CHOP FILTER
# ==============================

def is_choppy(closes, threshold_pct=0.1):
    if len(closes) < 200:
        return True

    e50 = ema(closes, 50)
    e200 = ema(closes, 200)
    spread_pct = abs(e50 - e200) / closes[-1] * 100

    return spread_pct < threshold_pct

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
# ORDERBLOCK
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
                mitigated = any(
                    closes[j] < lows[i] for j in range(i + 1, len(closes))
                )
                if not mitigated:
                    best = (lows[i], highs[i])

        if direction == "bearish" and closes[i] > opens[i]:
            future_low = min(lows[i + 1:i + 4])
            displacement = highs[i] - future_low

            if displacement > body * 2:
                mitigated = any(
                    closes[j] > highs[i] for j in range(i + 1, len(closes))
                )
                if not mitigated:
                    best = (lows[i], highs[i])

    return best if best else (None, None)

# ==============================
# HELPERS
# ==============================

def liquidity_sweep(highs, lows, closes):
    if len(highs) < 10:
        return None

    prev_high = max(highs[-10:-1])
    prev_low = min(lows[-10:-1])

    if highs[-1] > prev_high and closes[-1] < prev_high:
        return "bearish"

    if lows[-1] < prev_low and closes[-1] > prev_low:
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
# SL/TP
# ==============================

def calculate_sl_tp(direction, price, highs, lows, closes):
    atr_val = calculate_atr(highs, lows, closes)

    if direction == "bullish":
        swing_lows = find_swing_lows(lows, 3, 3)
        structure_sl = swing_lows[-1][1] if swing_lows else min(lows[-15:])
        sl = structure_sl - atr_val * 0.3
        sl_dist = price - sl
    else:
        swing_highs = find_swing_highs(highs, 3, 3)
        structure_sl = swing_highs[-1][1] if swing_highs else max(highs[-15:])
        sl = structure_sl + atr_val * 0.3
        sl_dist = sl - price

    sl_dist = max(8.0, min(12.0, sl_dist))
    sl = price - sl_dist if direction == "bullish" else price + sl_dist

    if direction == "bullish":
        targets = [s[1] for s in find_swing_highs(highs, 3, 3) if s[1] > price]
        tp_dist = min(targets) - price if targets else sl_dist * 3
    else:
        targets = [s[1] for s in find_swing_lows(lows, 3, 3) if s[1] < price]
        tp_dist = price - max(targets) if targets else sl_dist * 3

    if tp_dist < sl_dist * 2:
        tp_dist = sl_dist * 2

    tp = price + tp_dist if direction == "bullish" else price - tp_dist
    rr = round(tp_dist / sl_dist, 1)

    return round(sl, 2), round(tp, 2), round(sl_dist, 2), rr

# ==============================
# SCORE
# ==============================

def calculate_score(direction, trend, structure, struct_str, bos, at_ob, sweep, zone, rsi_val):
    score = 0.0

    if trend == direction:
        score += 2.0
    else:
        score -= 1.0

    if structure == direction:
        score += 1.0 + struct_str

    if bos == direction:
        score += 2.0

    if at_ob:
        score += 1.5

    if sweep == direction:
        score += 0.5

    if direction == "bullish" and zone == "discount":
        score += 0.5
    if direction == "bearish" and zone == "premium":
        score += 0.5

    if direction == "bullish" and 30 < rsi_val < 55:
        score += 0.5
    if direction == "bearish" and 45 < rsi_val < 70:
        score += 0.5

    return round(score, 1)

# ==============================
# REGIME DETECTION (shadow mode — log only, no filtering)
# ==============================

def detect_regime(h1_closes, h1_highs, h1_lows):
    if len(h1_closes) < 200:
        return "UNKNOWN"

    # Check VOLATILE: current ATR vs long-term average
    atr_14 = calculate_atr(h1_highs, h1_lows, h1_closes, 14)
    atr_50 = calculate_atr(h1_highs, h1_lows, h1_closes, 50)
    if atr_50 > 0 and atr_14 > atr_50 * 1.5:
        return "VOLATILE"

    # Check TRENDING: strong EMA spread + clear structure
    e50 = ema(h1_closes, 50)
    e200 = ema(h1_closes, 200)
    spread_pct = abs(e50 - e200) / h1_closes[-1] * 100
    structure, strength = market_structure(h1_highs, h1_lows)

    if spread_pct > 0.3 and strength >= 1.0 and structure in ("bullish", "bearish"):
        return "TRENDING"

    return "RANGING"


# ==============================
# MAIN
# ==============================

def generate_signal(data_m5, candle_index=0):

    if not BACKTEST_MODE and not is_active_session():
        return None

    if BACKTEST_MODE:
        if is_in_cooldown_backtest(candle_index):
            return None
    else:
        if is_in_cooldown_live():
            return None

    if BACKTEST_MODE:
        m15 = get_candles("15min")
        h1 = get_candles("1h")
    else:
        htf = get_htf_data()
        if htf is None:
            return None
        m15, h1 = htf

    if not m15 or not h1:
        return None

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
        return None

    direction = trend

    rsi_val = rsi(c5)

    if direction == "bullish" and rsi_val > 60:
        return None
    if direction == "bearish" and rsi_val < 40:
        return None

    ob_low, ob_high = detect_orderblock(h15, l15, o15, c15, direction)
    if ob_low is None:
        return None

    ob_mid = (ob_low + ob_high) / 2
    if direction == "bullish" and price > ob_mid:
        return None
    if direction == "bearish" and price < ob_mid:
        return None

    global _used_ob
    ob_id = (round(ob_low, 0), round(ob_high, 0))

    if ob_id == _used_ob:
        return None

    sweep = liquidity_sweep(h5, l5, c5)
    zone = premium_discount(h15, l15, price)

    structure, struct_str = market_structure(h15, l15)
    bos = detect_bos(h15, l15, c15)

    score = calculate_score(
        direction, trend, structure, struct_str, bos,
        True, sweep, zone, rsi_val
    )

    if score < SCORE_THRESHOLD:
        return None

    sl, tp, sl_dist, rr = calculate_sl_tp(direction, price, h5, l5, c5)

    if BACKTEST_MODE:
        record_signal_backtest(candle_index)
    else:
        record_signal_live()

    _used_ob = ob_id

    if score >= 8.5:
        confidence = "SNIPER"
    elif score >= 7.0:
        confidence = "HIGH"
    else:
        confidence = "MODERATE"

    regime = detect_regime(c1, h1["high"], h1["low"])
    log.info("Regime: %s (shadow mode)", regime)

    return {
        "direction": "BUY" if direction == "bullish" else "SELL",
        "entry": round(price, 2),
        "sl": sl,
        "tp": tp,
        "rr": rr,
        "sl_dist": sl_dist,
        "score": score,
        "confidence": confidence,
        "regime": regime,
    }