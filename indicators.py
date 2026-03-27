import numpy as np


def ema(data, period):
    data = np.array(data)
    if len(data) < period:
        return data[-1]

    weights = np.exp(np.linspace(-1., 0., period))
    weights /= weights.sum()

    a = np.convolve(data, weights, mode='full')[:len(data)]
    a[:period] = a[period]

    return a[-1]


def rsi(data, period=14):
    data = np.array(data)

    if len(data) < period + 1:
        return 50

    deltas = np.diff(data)

    gains = deltas.clip(min=0)
    losses = -deltas.clip(max=0)

    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def atr(highs, lows, closes, period=14):
    highs = np.array(highs)
    lows = np.array(lows)
    closes = np.array(closes)

    if len(closes) < period + 1:
        return 1

    tr = np.maximum(highs[1:] - lows[1:], 
         np.maximum(abs(highs[1:] - closes[:-1]), 
                    abs(lows[1:] - closes[:-1])))

    return np.mean(tr[-period:])