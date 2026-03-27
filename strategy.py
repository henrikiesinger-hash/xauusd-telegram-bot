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
        if highs[i] == max(highs[i-left:i+right+1]):
            swings.append(highs[i])
    return swings


def find_swing_lows(lows, left=5, right=5):
    swings = []
    for i in range(left, len(lows) - right):
        if lows[i] == min(lows[i-left:i+right+1]):
            swings.append(lows[i])
    return swings


# ==============================
# STRUCTURE
# ==============================
def market_structure(highs, lows):
    sh = find_swing_highs(highs)
    sl = find_swing_lows(lows)

    if len(sh) < 2 or len(sl) < 2:
        return "ranging", 0.0

    if sh[-1] > sh[-2] and sl[-1] > sl[-2]:
        return "bullish", 1.0

    if sh[-1] < sh[-2] and sl[-1] < sl[-2]:
        return "bearish", 1.0

    return "ranging", 0.3


# ==============================
# TREND
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

    return None, 0.0


# ==============================
# BOS
# ==============================
def detect_bos(highs, lows, closes):
    if len(highs) < 10:
        return None, None

    if closes[-1] > max(highs[-10:-1]):
        return "bullish", max(highs[-10:-1])

    if closes[-1] < min(lows[-10:-1]):
        return "bearish", min(lows[-10:-1])

    return None, None


# ==============================
# ORDERBLOCK
# ==============================
def detect_orderblock(highs, lows, opens, closes, direction):
    for i in range(-20, -2):
        if direction == "bullish" and closes[i] < opens[i]:
            return direction, lows[i], highs[i], 1.0

        if direction == "bearish" and closes[i] > opens[i]:
            return direction, lows[i], highs[i], 1.0

    return None, None, None, 0.0


# ==============================
# SWEEP
# ==============================
def liquidity_sweep(highs, lows, closes):
    if highs[-1] > max(highs[-10:-1]) and closes[-1] < highs[-2]:
        return "bearish"

    if lows[-1] < min(lows[-10:-1]) and closes[-1] > lows[-2]:
        return "bullish"

    return None


# ==============================
# ZONE
# ==============================
def premium_discount(highs, lows, price):
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
    trs = []
    for i in range(-period, 0):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        trs.append(tr)

    return sum(trs) / len(trs)


# ==============================
# SL TP
# ==============================
def calculate_sl_tp(direction, price, highs, lows, closes):
    atr = calculate_atr(highs, lows, closes)

    sl_dist = max(1.0, atr * 1.2)

    if direction == "bullish":
        sl = price - sl_dist
        tp = price + sl_dist * 3   # 🔥 höheres CRV
    else:
        sl = price + sl_dist
        tp = price - sl_dist * 3

    return round(sl, 2), round(tp, 2)


# ==============================
# MAIN SIGNAL
# ==============================
def generate_signal(data_m5):

    if not hasattr(generate_signal, "cache"):
        generate_signal.cache = (
            get_candles("15min"),
            get_candles("1h")
        )

    data_m15, data_h1 = generate_signal.cache

    if data_m15 is None or data_h1 is None:
        return None

    c5 = data_m5["close"]
    h5 = data_m5["high"]
    l5 = data_m5["low"]
    o5 = data_m5["open"]

    c15 = data_m15["close"]
    h15 = data_m15["high"]
    l15 = data_m15["low"]
    o15 = data_m15["open"]

    c_h1 = data_h1["close"]

    price = c5[-1]

    trend, _ = trend_direction(c_h1)
    structure, _ = market_structure(h15, l15)
    bos, bos_level = detect_bos(h15, l15, c15)

    if trend is None:
        return None

    direction = trend

    ob_dir, ob_low, ob_high, _ = detect_orderblock(h15, l15, o15, c15, direction)

    if ob_low is None:
        return None

    at_ob = ob_low <= price <= ob_high

    sweep = liquidity_sweep(h5, l5, c5)
    zone = premium_discount(h15, l15, price)
    rsi_val = rsi(c5)

    # ==============================
    # 🔥 SNIPER ENTRY LOGIC
    # ==============================

    # OB Pflicht
    if not at_ob:
        return None

    # Retest Pflicht
    has_retest = False
    if bos_level:
        atr = calculate_atr(h5, l5, c5)
        if abs(price - bos_level) < atr:
            has_retest = True

    if not has_retest:
        return None

    # RSI Filter
    if direction == "bullish" and not (35 < rsi_val < 55):
        return None

    if direction == "bearish" and not (45 < rsi_val < 65):
        return None

    # Sweep für High Quality
    if sweep != direction:
        return None

    # Zone Filter
    if direction == "bullish" and zone != "discount":
        return None

    if direction == "bearish" and zone != "premium":
        return None

    # ==============================
    # EXECUTION
    # ==============================

    sl, tp = calculate_sl_tp(direction, price, h5, l5, c5)

    return {
        "direction": "BUY" if direction == "bullish" else "SELL",
        "entry": round(price, 2),
        "sl": sl,
        "tp": tp,
        "score": 8.0,
        "confidence": "SNIPER",
        "notes": "Sniper Setup"
    }