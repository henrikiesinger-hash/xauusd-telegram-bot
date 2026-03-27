import logging
import time
from indicators import ema, rsi
from data import get_candles

log = logging.getLogger("strategy")

# ==============================
# MODE
# ==============================
BACKTEST_MODE = False

# ==============================
# CONFIG
# ==============================
SCORE_THRESHOLD = 5.5
COOLDOWN_SECONDS = 3600
LONDON_OPEN_UTC = 7
NY_CLOSE_UTC = 21

_last_signal_time = 0
_htf_cache = {"data": None, "timestamp": 0}
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
def is_in_cooldown():
    global _last_signal_time
    return (time.time() - _last_signal_time) < COOLDOWN_SECONDS

def record_signal():
    global _last_signal_time
    _last_signal_time = time.time()

# ==============================
# HTF CACHE
# ==============================
def get_htf_data():
    global _htf_cache
    now = time.time()

    if _htf_cache["data"] and (now - _htf_cache["timestamp"]) < HTF_CACHE_TTL:
        return _htf_cache["data"]

    m15 = get_candles("15min")
    h1 = get_candles("1h")

    if not m15 or not h1:
        return None

    _htf_cache["data"] = (m15, h1)
    _htf_cache["timestamp"] = now
    return (m15, h1)

# ==============================
# SIMPLE STRUCTURE
# ==============================
def trend_direction(closes):
    if len(closes) < 200:
        return None

    e21 = ema(closes, 21)
    e50 = ema(closes, 50)

    if e21 > e50:
        return "bullish"
    elif e21 < e50:
        return "bearish"

    return None

# ==============================
# MAIN SIGNAL
# ==============================
def generate_signal(data_m5):

    # 🔥 SESSION + COOLDOWN (ONLY LIVE)
    if not BACKTEST_MODE:
        if not is_active_session():
            return None
        if is_in_cooldown():
            return None

    # HTF DATA
    htf = get_htf_data()
    if htf is None:
        return None

    m15, h1 = htf

    c5 = data_m5["close"]
    c15 = m15["close"]
    c1 = h1["close"]

    price = c5[-1]

    trend = trend_direction(c1)
    structure = trend_direction(c15)

    if trend is None or structure is None:
        return None

    if trend != structure:
        return None

    direction = trend

    rsi_val = rsi(c5)

    # SIMPLE SCORE
    score = 0

    if direction == trend:
        score += 2
    if direction == structure:
        score += 2
    if (direction == "bullish" and rsi_val > 50) or (direction == "bearish" and rsi_val < 50):
        score += 2

    if score < SCORE_THRESHOLD:
        return None

    # SL / TP FIX
    sl_dist = 2.0

    if direction == "bullish":
        sl = price - sl_dist
        tp = price + sl_dist * 2
    else:
        sl = price + sl_dist
        tp = price - sl_dist * 2

    if not BACKTEST_MODE:
        record_signal()

    return {
        "direction": "BUY" if direction == "bullish" else "SELL",
        "entry": round(price, 2),
        "sl": round(sl, 2),
        "tp": round(tp, 2),
        "score": score,
        "confidence": "HIGH" if score >= 6 else "MODERATE",
        "notes": "PRO MODE"
    }