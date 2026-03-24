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
    if len(highs) < 30 or len(lows) < 30:
        return "neutral"

    recent_high = max(highs[-10:])
    prev_high = max(highs[-20:-10])

    recent_low = min(lows[-10:])
    prev_low = min(lows[-20:-10])

    if recent_high > prev_high and recent_low > prev_low:
        return "bullish"

    if recent_high < prev_high and recent_low < prev_low:
        return "bearish"

    return "neutral"


def break_of_structure(highs, lows, closes, lookback=15):
    if len(highs) < lookback + 3:
        return None, None

    prev_swing_high = max(highs[-(lookback + 2):-2])
    prev_swing_low = min(lows[-(lookback + 2):-2])

    last_close = closes[-1]
    prev_close = closes[-2]

    # Bullish BOS only if current or previous candle closed above structure
    if prev_close > prev_swing_high or last_close > prev_swing_high:
        return "bullish", prev_swing_high

    # Bearish BOS only if current or previous candle closed below structure
    if prev_close < prev_swing_low or last_close < prev_swing_low:
        return "bearish", prev_swing_low

    return None, None


def choch_signal(highs, lows, closes):
    if len(highs) < 25:
        return None

    structure = market_structure(highs[:-1], lows[:-1])
    bos, _ = break_of_structure(highs, lows, closes, lookback=10)

    if structure == "bearish" and bos == "bullish":
        return "bullish"

    if structure == "bullish" and bos == "bearish":
        return "bearish"

    return None


def liquidity_sweep(highs, lows, closes, lookback=8):
    if len(highs) < lookback + 2:
        return None

    prev_high = max(highs[-(lookback + 1):-1])
    prev_low = min(lows[-(lookback + 1):-1])

    last_high = highs[-1]
    last_low = lows[-1]
    last_close = closes[-1]

    # bearish sweep: takes highs, closes back below
    if last_high > prev_high and last_close < prev_high:
        return "bearish"

    # bullish sweep: takes lows, closes back above
    if last_low < prev_low and last_close > prev_low:
        return "bullish"

    return None


def orderblock_signal(opens, highs, lows, closes):
    if len(opens) < 3:
        return None, None, None

    prev_open = opens[-2]
    prev_close = closes[-2]
    prev_high = highs[-2]
    prev_low = lows[-2]
    last_close = closes[-1]

    # bullish orderblock confirmation
    if prev_close < prev_open and last_close > prev_high:
        return "bullish", prev_low, prev_high

    # bearish orderblock confirmation
    if prev_close > prev_open and last_close < prev_low:
        return "bearish", prev_low, prev_high

    return None, None, None


def premium_discount_zone(highs, lows, price):
    if len(highs) < 40 or len(lows) < 40:
        return "neutral", None, None, None

    range_high = max(highs[-40:])
    range_low = min(lows[-40:])
    equilibrium = (range_high + range_low) / 2

    if price < equilibrium:
        return "discount", range_high, range_low, equilibrium

    if price > equilibrium:
        return "premium", range_high, range_low, equilibrium

    return "neutral", range_high, range_low, equilibrium


def fibonacci_entry_zone(highs, lows, price, direction):
    if len(highs) < 40 or len(lows) < 40:
        return False, None, None

    swing_high = max(highs[-40:])
    swing_low = min(lows[-40:])
    rng = swing_high - swing_low

    if rng <= 0:
        return False, None, None

    if direction == "bullish":
        fib50 = swing_high - (rng * 0.5)
        fib618 = swing_high - (rng * 0.618)
        low_zone = min(fib50, fib618)
        high_zone = max(fib50, fib618)
        return low_zone <= price <= high_zone, round(low_zone, 2), round(high_zone, 2)

    if direction == "bearish":
        fib50 = swing_low + (rng * 0.5)
        fib618 = swing_low + (rng * 0.618)
        low_zone = min(fib50, fib618)
        high_zone = max(fib50, fib618)
        return low_zone <= price <= high_zone, round(low_zone, 2), round(high_zone, 2)

    return False, None, None


def momentum_bias(closes):
    value = rsi(closes)

    if value > 55:
        return "bullish", value
    if value < 45:
        return "bearish", value

    return "neutral", value


def volatility_ok(highs, lows, closes):
    atr_value = atr(highs, lows, closes)
    price = closes[-1]

    min_required = max(price * 0.0006, 0.8)

    return atr_value >= min_required, atr_value


def retest_after_bos(closes, bos_level, direction, tolerance):
    if bos_level is None or len(closes) < 4:
        return False

    recent_prices = closes[-4:]

    if direction == "bullish":
        # after bullish BOS, price should retest near the broken level and hold above
        touched = any(abs(price - bos_level) <= tolerance for price in recent_prices[:-1])
        held = closes[-1] > bos_level
        return touched and held

    if direction == "bearish":
        # after bearish BOS, price should retest near the broken level and hold below
        touched = any(abs(price - bos_level) <= tolerance for price in recent_prices[:-1])
        held = closes[-1] < bos_level
        return touched and held

    return False


def entry_not_too_extended(price, bos_level, atr_value):
    if bos_level is None or atr_value <= 0:
        return False

    distance = abs(price - bos_level)

    # avoid chasing late entries
    return distance <= (atr_value * 1.2)


def candle_confirmation(opens, closes, direction):
    if len(opens) < 2 or len(closes) < 2:
        return False

    last_open = opens[-1]
    last_close = closes[-1]

    if direction == "bullish":
        return last_close > last_open

    if direction == "bearish":
        return last_close < last_open

    return False


def fakeout_filter(highs, lows, closes, bos_direction, bos_level, atr_value):
    if bos_direction is None or bos_level is None:
        return False

    if len(closes) < 3:
        return False

    last_close = closes[-1]

    # reject fake bullish BOS if price snaps back too far below level
    if bos_direction == "bullish":
        return last_close >= (bos_level - atr_value * 0.25)

    # reject fake bearish BOS if price snaps back too far above level
    if bos_direction == "bearish":
        return last_close <= (bos_level + atr_value * 0.25)

    return False


def calculate_trade(entry, direction, highs, lows, atr_value):
    recent_high = max(highs[-12:])
    recent_low = min(lows[-12:])

    if direction == "BUY":
        sl = recent_low - (atr_value * 0.2)
        risk = entry - sl
        tp = entry + (risk * 2.2)
    else:
        sl = recent_high + (atr_value * 0.2)
        risk = sl - entry
        tp = entry - (risk * 2.2)

    return round(sl, 2), round(tp, 2), round(risk, 2)


def build_reasons(direction, h1_trend, m15_structure, bos, choch, sweep, ob, zone, fib_ok, rsi_value, retest_ok):
    reasons = []

    reasons.append(f"H1 Trend: {h1_trend}")
    reasons.append(f"M15 Structure: {m15_structure}")

    if bos:
        reasons.append(f"BOS: {bos}")

    if choch:
        reasons.append(f"CHOCH: {choch}")

    if sweep:
        reasons.append(f"Sweep: {sweep}")

    if ob:
        reasons.append(f"Orderblock: {ob}")

    reasons.append(f"Zone: {zone}")
    reasons.append(f"Retest: {'yes' if retest_ok else 'no'}")

    if fib_ok:
        reasons.append("Fib Entry Zone: yes")

    reasons.append(f"RSI: {round(rsi_value, 2)}")
    reasons.append(f"Direction: {direction}")

    return " | ".join(reasons)


def generate_signal(data_m5):
    if data_m5 is None:
        return None

    data_m15 = get_candles("15min", 200)
    data_h1 = get_candles("1h", 200)

    if data_m15 is None or data_h1 is None:
        return None

    # M5
    opens_5 = data_m5["open"]
    highs_5 = data_m5["high"]
    lows_5 = data_m5["low"]
    closes_5 = data_m5["close"]

    # M15
    highs_15 = data_m15["high"]
    lows_15 = data_m15["low"]
    closes_15 = data_m15["close"]

    # H1
    closes_h1 = data_h1["close"]

    price = closes_5[-1]

    # Higher timeframe trend
    h1_trend = higher_timeframe_trend(closes_h1)

    # M15 bias
    m15_structure = market_structure(highs_15, lows_15)
    bos, bos_level = break_of_structure(highs_15, lows_15, closes_15, lookback=15)
    choch = choch_signal(highs_15, lows_15, closes_15)

    # M5 entry confirmations
    sweep = liquidity_sweep(highs_5, lows_5, closes_5, lookback=8)
    ob, ob_low, ob_high = orderblock_signal(opens_5, highs_5, lows_5, closes_5)
    zone, _, _, _ = premium_discount_zone(highs_15, lows_15, price)
    momentum, rsi_value = momentum_bias(closes_5)
    fib_bull_ok, fib_bull_low, fib_bull_high = fibonacci_entry_zone(highs_15, lows_15, price, "bullish")
    fib_bear_ok, fib_bear_low, fib_bear_high = fibonacci_entry_zone(highs_15, lows_15, price, "bearish")
    vol_ok, atr_value = volatility_ok(highs_5, lows_5, closes_5)

    buy_score = 0
    sell_score = 0

    # H1 trend
    if h1_trend == "bullish":
        buy_score += 2
    if h1_trend == "bearish":
        sell_score += 2

    # M15 structure
    if m15_structure == "bullish":
        buy_score += 2
    if m15_structure == "bearish":
        sell_score += 2

    # BOS
    if bos == "bullish":
        buy_score += 2
    if bos == "bearish":
        sell_score += 2

    # CHOCH
    if choch == "bullish":
        buy_score += 1
    if choch == "bearish":
        sell_score += 1

    # Sweep
    if sweep == "bullish":
        buy_score += 1
    if sweep == "bearish":
        sell_score += 1

    # Orderblock
    if ob == "bullish":
        buy_score += 1
    if ob == "bearish":
        sell_score += 1

    # Strict zone validation
    if zone == "discount":
        buy_score += 1
    if zone == "premium":
        sell_score += 1

    # Fibonacci
    if fib_bull_ok:
        buy_score += 1
    if fib_bear_ok:
        sell_score += 1

    # Momentum
    if momentum == "bullish":
        buy_score += 1
    if momentum == "bearish":
        sell_score += 1

    # Volatility
    if vol_ok:
        buy_score += 1
        sell_score += 1

    # Retest + fakeout + delay filters
    bullish_retest_ok = retest_after_bos(closes_5, bos_level, "bullish", atr_value * 0.35)
    bearish_retest_ok = retest_after_bos(closes_5, bos_level, "bearish", atr_value * 0.35)

    bullish_not_extended = entry_not_too_extended(price, bos_level, atr_value)
    bearish_not_extended = entry_not_too_extended(price, bos_level, atr_value)

    bullish_candle_ok = candle_confirmation(opens_5, closes_5, "bullish")
    bearish_candle_ok = candle_confirmation(opens_5, closes_5, "bearish")

    bullish_fakeout_ok = fakeout_filter(highs_5, lows_5, closes_5, "bullish", bos_level, atr_value)
    bearish_fakeout_ok = fakeout_filter(highs_5, lows_5, closes_5, "bearish", bos_level, atr_value)

    direction = None
    score = 0
    fib_text = ""

    # BUY decision
    if buy_score >= SIGNAL_SCORE_THRESHOLD and buy_score > sell_score:
        if h1_trend != "bullish":
            return None
        if zone != "discount":
            return None
        if rsi_value >= 70:
            return None
        if not bullish_retest_ok:
            return None
        if not bullish_not_extended:
            return None
        if not bullish_candle_ok:
            return None
        if not bullish_fakeout_ok:
            return None

        direction = "BUY"
        score = buy_score
        if fib_bull_ok:
            fib_text = f"Fib Zone: {fib_bull_low}-{fib_bull_high}"

    # SELL decision
    elif sell_score >= SIGNAL_SCORE_THRESHOLD and sell_score > buy_score:
        if h1_trend != "bearish":
            return None
        if zone != "premium":
            return None
        if rsi_value <= 30:
            return None
        if not bearish_retest_ok:
            return None
        if not bearish_not_extended:
            return None
        if not bearish_candle_ok:
            return None
        if not bearish_fakeout_ok:
            return None

        direction = "SELL"
        score = sell_score
        if fib_bear_ok:
            fib_text = f"Fib Zone: {fib_bear_low}-{fib_bear_high}"

    if direction is None:
        return None

    sl, tp, risk = calculate_trade(price, direction, highs_5, lows_5, atr_value)

    if risk <= 0:
        return None

    reasons = build_reasons(
        direction=direction,
        h1_trend=h1_trend,
        m15_structure=m15_structure,
        bos=bos,
        choch=choch,
        sweep=sweep,
        ob=ob,
        zone=zone,
        fib_ok=(fib_bull_ok if direction == "BUY" else fib_bear_ok),
        rsi_value=rsi_value,
        retest_ok=(bullish_retest_ok if direction == "BUY" else bearish_retest_ok)
    )

    extra = fib_text if fib_text else "Fib Zone: no"

    return {
        "direction": direction,
        "entry": round(price, 2),
        "sl": sl,
        "tp": tp,
        "score": score,
        "notes": f"{reasons} | {extra}"
    }