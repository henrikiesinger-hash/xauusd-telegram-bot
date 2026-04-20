import numpy as np


def ema(data, period):
    data = np.array(data, dtype=float)

    if len(data) == 0:
        return 0.0

    if len(data) < period:
        return float(data[-1])

    alpha = 2.0 / (period + 1)
    ema_val = float(np.mean(data[:period]))
    for v in data[period:]:
        ema_val = alpha * float(v) + (1.0 - alpha) * ema_val

    return float(ema_val)


def rsi(data, period=14):
    data = np.array(data, dtype=float)

    if len(data) < period + 1:
        return 50.0

    deltas = np.diff(data)
    gains = np.clip(deltas, 0, None)
    losses = np.clip(-deltas, 0, None)

    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return float(100 - (100 / (1 + rs)))


def atr(highs, lows, closes, period=14):
    highs = np.array(highs, dtype=float)
    lows = np.array(lows, dtype=float)
    closes = np.array(closes, dtype=float)

    if len(closes) < period + 1:
        return 1.0

    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1])
        )
    )

    return float(np.mean(tr[-period:]))