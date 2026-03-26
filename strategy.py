from indicators import ema, rsi, atr
from config import SIGNAL_SCORE_THRESHOLD
from data import get_candles


def higher_timeframe_trend(closes):
    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)

    if ema50 > ema200:
        return "bullish"
    if ema50 < ema200:
        return "bearish"
    return "neutral"


def market_structure(highs, lows):
    recent_high = max(highs[-10:])
    prev_high = max(highs[-20:-10])

    recent_low = min(lows[-10:])
    prev_low = min(lows[-20:-10])

    if recent_high > prev_high and recent_low > prev_low:
        return "bullish"

    if recent_high < prev_high and recent_low < prev_low:
        return "bearish"

    return "neutral"


def break_of_structure(highs, lows, closes):
    prev_high = max(highs[-20:-2])
    prev_low = min(lows[-20:-2])
    last_close = closes[-1]

    if last_close > prev_high:
        return "bullish", prev_high

    if last_close < prev_low:
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


def premium_discount_zone(highs, lows, price):
    high = max(highs[-40:])
    low = min(lows[-40:])
    eq = (high + low) / 2

    if price > eq:
        return "premium"
    else:
        return "discount"


def retest(closes, level, tolerance):
    return abs(closes[-1] - level) <= tolerance


def generate_signal(data_m5):

    data_m15 = get_candles("15min", 200)
    data_h1 = get_candles("1h", 200)

    if data_m15 is None or data_h1 is None:
        return None

    closes_5 = data_m5["close"]
    highs_5 = data_m5["high"]
    lows_5 = data_m5["low"]

    closes_15 = data_m15["close"]
    highs_15 = data_m15["high"]
    lows_15 = data_m15["low"]

    closes_h1 = data_h1["close"]

    price = closes_5[-1]

    # CORE
    trend = higher_timeframe_trend(closes_h1)
    structure = market_structure(highs_15, lows_15)
    bos, bos_level = break_of_structure(highs_15, lows_15, closes_15)

    if bos is None:
        return None  # nur das bleibt hart

    # INDICATORS
    sweep = liquidity_sweep(highs_5, lows_5, closes_5)
    zone = premium_discount_zone(highs_15, lows_15, price)
    rsi_value = rsi(closes_5)
    atr_value = atr(highs_5, lows_5, closes_5)

    score = 0

    # CORE SCORE
    if trend == "bullish":
        score += 2
    if trend == "bearish":
        score += 2

    if structure == "bullish":
        score += 2
    if structure == "bearish":
        score += 2

    if bos == "bullish":
        score += 2
    if bos == "bearish":
        score += 2

    # RETEST (WICHTIGSTER FILTER)
    if bos_level and retest(closes_5, bos_level, atr_value * 0.3):
        score += 2
    else:
        return None  # bleibt hart

    # SOFT FILTERS
    if sweep == "bullish":
        score += 1
    if sweep == "bearish":
        score += 1

    if zone == "discount":
        score += 1
    if zone == "premium":
        score += 1

    # RSI (kein Blocker mehr!)
    if 40 < rsi_value < 60:
        score += 1

    # FINAL DECISION
    if score < SIGNAL_SCORE_THRESHOLD:
        return None

    # DIRECTION
    direction = "BUY" if trend == "bullish" else "SELL"

    # SL / TP
    if direction == "BUY":
        sl = min(lows_5[-10:]) - atr_value * 0.2
        tp = price + (price - sl) * 2
    else:
        sl = max(highs_5[-10:]) + atr_value * 0.2
        tp = price - (sl - price) * 2

    return {
        "direction": direction,
        "entry": round(price, 2),
        "sl": round(sl, 2),
        "tp": round(tp, 2),
        "score": score,
        "notes": f"Trend: {trend} | BOS: {bos} | Zone: {zone} | RSI: {round(rsi_value,2)}"
    }