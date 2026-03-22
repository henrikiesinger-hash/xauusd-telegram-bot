import numpy as np


def ema(data, period):

    weights = np.exp(np.linspace(-1., 0., period))
    weights /= weights.sum()

    ema = np.convolve(data, weights, mode='valid')

    return ema[-1]


def rsi(closes, period=14):

    deltas = np.diff(closes)
    seed = deltas[:period]

    up = seed[seed >= 0].sum()/period
    down = -seed[seed < 0].sum()/period

    rs = up/down if down != 0 else 0

    rsi = 100 - (100/(1+rs))

    return rsi


def atr(highs, lows, closes, period=14):

    trs = []

    for i in range(1, len(highs)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        trs.append(tr)

    return sum(trs[-period:]) / period
