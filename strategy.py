from indicators import ema, rsi, atr
from config import SIGNAL_SCORE_THRESHOLD


def detect_trend(closes):

    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)

    if ema50 > ema200:
        return "bullish", 2

    if ema50 < ema200:
        return "bearish", 2

    return "neutral", 0


def momentum_score(closes):

    r = rsi(closes)

    if r > 60:
        return "bullish", 2

    if r < 40:
        return "bearish", 2

    return "neutral", 0


def breakout_score(highs, lows, closes):

    recent_high = max(highs[-20:])
    recent_low = min(lows[-20:])

    price = closes[-1]

    if price > recent_high:
        return "bullish", 2

    if price < recent_low:
        return "bearish", 2

    return "none", 0


def liquidity_sweep(highs, lows):

    if highs[-1] > max(highs[-10:-1]):
        return "sell_sweep", 1

    if lows[-1] < min(lows[-10:-1]):
        return "buy_sweep", 1

    return None, 0


def calculate_trade(price, atr_value, direction):

    if direction == "BUY":

        sl = price - atr_value * 1.5
        tp = price + atr_value * 3

    else:

        sl = price + atr_value * 1.5
        tp = price - atr_value * 3

    return round(sl,2), round(tp,2)


def generate_signal(data):

    closes = data["close"]
    highs = data["high"]
    lows = data["low"]

    price = closes[-1]

    score = 0

    trend, tscore = detect_trend(closes)
    score += tscore

    momentum, mscore = momentum_score(closes)
    score += mscore

    breakout, bscore = breakout_score(highs,lows,closes)
    score += bscore

    sweep, sscore = liquidity_sweep(highs,lows)
    score += sscore

    atr_value = atr(highs,lows,closes)

    direction = None

    if trend == "bullish":
        direction = "BUY"

    if trend == "bearish":
        direction = "SELL"

    if direction is None:
        return None

    if score < SIGNAL_SCORE_THRESHOLD:
        return None

    sl,tp = calculate_trade(price,atr_value,direction)

    return {
        "direction": direction,
        "entry": price,
        "sl": sl,
        "tp": tp,
        "score": score
    }
