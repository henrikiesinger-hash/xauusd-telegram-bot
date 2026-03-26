import pandas as pd

def compute_atr(df, period=14):
    high = df["high"]
    low = df["low"]
    close = df["close"]

    prev_close = close.shift(1)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)

    return tr.rolling(period).mean()


def build_trade(df, direction, entry):
    df["atr"] = compute_atr(df)

    atr = df["atr"].iloc[-1]

    if pd.isna(atr):
        return {"valid": False, "reason": "ATR fehlt"}

    buffer = atr * 0.4

    if direction == "SELL":
        swing_high = df["high"].iloc[-6:-1].max()
        sl = swing_high + buffer
        risk = sl - entry

        if risk < 8:
            return {"valid": False, "reason": f"SL zu klein ({risk:.2f}$)"}

        tp = entry - (risk * 2)

    elif direction == "BUY":
        swing_low = df["low"].iloc[-6:-1].min()
        sl = swing_low - buffer
        risk = entry - sl

        if risk < 8:
            return {"valid": False, "reason": f"SL zu klein ({risk:.2f}$)"}

        tp = entry + (risk * 2)

    else:
        return {"valid": False, "reason": "Keine Richtung"}

    return {
        "valid": True,
        "entry": round(entry, 2),
        "sl": round(sl, 2),
        "tp": round(tp, 2),
        "risk": round(risk, 2)
    }