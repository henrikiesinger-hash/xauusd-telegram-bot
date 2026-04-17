"""
XAUUSD Non-SMC Strategy Shootout - 5 Alternativ-Strategien
Railway-kompatibel, nutzt TwelveData API.

USAGE (Railway Shell):
python backtest_nonsmc.py

Der TWELVE_DATA_KEY wird aus den Railway Environment Variables gelesen.
Live-Bot wird NICHT beeinflusst - dieses Script laeuft nur einmal on-demand.

Strategien:
  N1 - ORB (Opening Range Breakout)
  N2 - EMA Pullback
  N3 - Bollinger Squeeze Breakout
  N4 - RSI Extreme Reversal
  N5 - Donchian Breakout
"""

import os
import sys
import time
import math
import requests
import pandas as pd

# ==============================
# CONFIG
# ==============================

TWELVE_DATA_KEY = os.environ.get('TWELVE_DATA_KEY')
if not TWELVE_DATA_KEY:
    print('FEHLER: TWELVE_DATA_KEY nicht gesetzt')
    sys.exit(1)

SYMBOL = 'XAU/USD'
BACKTEST_DAYS = 60

LONDON_OPEN_UTC = 7
NY_CLOSE_UTC = 21
FRIDAY_CUTOFF_UTC = 19

COOLDOWN_AFTER_WIN = 6
COOLDOWN_AFTER_LOSS = 12

SL_ATR_MULT = 1.5
RR_TARGET = 2.0
SL_MIN = 6.0
SL_MAX = 12.0

# ORB
ORB_START_UTC = 7
ORB_END_UTC = 8
ORB_ENTRY_CUTOFF_UTC = 12

# Bollinger
BB_PERIOD = 20
BB_STD = 2.0
BB_SQUEEZE_THRESHOLD = 0.005
BB_SQUEEZE_LOOKBACK = 5

# RSI Extreme
RSI_BUY_THRESHOLD = 25
RSI_SELL_THRESHOLD = 75

# Donchian
DONCHIAN_PERIOD = 20
DONCHIAN_ATR_MIN = 2.0

# ==============================
# DATA LOADING (TwelveData)
# ==============================

def fetch_twelvedata(interval, outputsize):
    url = 'https://api.twelvedata.com/time_series'
    params = {
        'symbol': SYMBOL,
        'interval': interval,
        'outputsize': outputsize,
        'apikey': TWELVE_DATA_KEY,
        'format': 'JSON',
        'order': 'ASC',
    }

    resp = requests.get(url, params=params, timeout=30)
    data = resp.json()

    if data.get('status') == 'error':
        print(f'TwelveData Error ({interval}): {data.get("message")}')
        return None

    if 'values' not in data:
        print(f'TwelveData: Keine Values fuer {interval}')
        return None

    df = pd.DataFrame(data['values'])
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.sort_values('datetime').reset_index(drop=True)

    for col in ['open', 'high', 'low', 'close']:
        df[col] = df[col].astype(float)

    return df


def load_data():
    print(f'Lade {SYMBOL} Daten von TwelveData ({BACKTEST_DAYS} Tage)...')

    m5 = fetch_twelvedata('5min', 5000)
    time.sleep(1)
    m15 = fetch_twelvedata('15min', 2000)
    time.sleep(1)
    h1 = fetch_twelvedata('1h', 1000)

    if m5 is None or m15 is None or h1 is None:
        print('Daten konnten nicht geladen werden')
        sys.exit(1)

    print(f'M5:  {len(m5)} candles von {m5.iloc[0]["datetime"]} bis {m5.iloc[-1]["datetime"]}')
    print(f'M15: {len(m15)} candles')
    print(f'H1:  {len(h1)} candles')
    print()

    return m5, m15, h1


def df_to_dict(df, end_idx=None):
    if end_idx is not None:
        df = df.iloc[:end_idx]
    return {
        'open': df['open'].values.tolist(),
        'high': df['high'].values.tolist(),
        'low': df['low'].values.tolist(),
        'close': df['close'].values.tolist(),
    }

# ==============================
# INDICATORS
# ==============================

def ema(values, period):
    if len(values) < period:
        return values[-1] if values else 0
    k = 2 / (period + 1)
    ema_val = sum(values[:period]) / period
    for v in values[period:]:
        ema_val = v * k + ema_val * (1 - k)
    return ema_val


def ema_series(values, period):
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    seed = sum(values[:period]) / period
    out = [seed]
    for v in values[period:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(values, period=14):
    if len(values) < period + 1:
        return 50
    gains, losses = [], []
    for i in range(-period, 0):
        change = values[i] - values[i-1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return 3.0
    tr_list = []
    for i in range(-period, 0):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        tr_list.append(tr)
    return sum(tr_list) / len(tr_list)


def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def stddev(values, period):
    if len(values) < period:
        return None
    window = values[-period:]
    m = sum(window) / period
    var = sum((v - m) ** 2 for v in window) / period
    return math.sqrt(var)


def bollinger_bands(closes, period=20, std_mult=2.0):
    m = sma(closes, period)
    sd = stddev(closes, period)
    if m is None or sd is None:
        return None, None, None
    upper = m + std_mult * sd
    lower = m - std_mult * sd
    return upper, m, lower

# ==============================
# SWING POINTS
# ==============================

def find_swing_highs(highs, left=5, right=5):
    swings = []
    for i in range(left, len(highs) - right):
        window = highs[i-left:i+right+1]
        if highs[i] == max(window) and len(set(window)) > 1:
            swings.append((i, highs[i]))
    return swings


def find_swing_lows(lows, left=5, right=5):
    swings = []
    for i in range(left, len(lows) - right):
        window = lows[i-left:i+right+1]
        if lows[i] == min(window) and len(set(window)) > 1:
            swings.append((i, lows[i]))
    return swings

# ==============================
# HELPERS
# ==============================

def trend_direction_h1(closes):
    if len(closes) < 200:
        return None
    e50 = ema(closes, 50)
    e200 = ema(closes, 200)
    if e50 > e200:
        return 'bullish'
    if e50 < e200:
        return 'bearish'
    return None


def bullish_engulfing(opens, highs, lows, closes):
    if len(closes) < 2:
        return False
    o, c = opens[-1], closes[-1]
    po, pc = opens[-2], closes[-2]
    ph, pl = highs[-2], lows[-2]
    return c > o and c > ph and o < pl


def bearish_engulfing(opens, highs, lows, closes):
    if len(closes) < 2:
        return False
    o, c = opens[-1], closes[-1]
    po, pc = opens[-2], closes[-2]
    ph, pl = highs[-2], lows[-2]
    return c < o and c < pl and o > ph


def map_htf_index(m5_time, htf_df):
    for i in range(len(htf_df)):
        if htf_df.iloc[i]['datetime'] > m5_time:
            return max(0, i - 1)
    return len(htf_df) - 1


def session_allowed(current_time):
    weekday = current_time.weekday()
    if weekday >= 5:
        return False
    hour = current_time.hour
    if hour < LONDON_OPEN_UTC or hour >= NY_CLOSE_UTC:
        return False
    if weekday == 4 and hour >= FRIDAY_CUTOFF_UTC:
        return False
    return True

# ==============================
# SL/TP (einheitlich fuer alle Strategien)
# ==============================

def calculate_sl_tp_atr(direction, price, highs, lows, closes):
    atr_val = calculate_atr(highs, lows, closes, 14)
    sl_dist = SL_ATR_MULT * atr_val
    sl_dist = max(SL_MIN, min(SL_MAX, sl_dist))
    tp_dist = sl_dist * RR_TARGET
    if direction == 'bullish':
        sl = price - sl_dist
        tp = price + tp_dist
    else:
        sl = price + sl_dist
        tp = price - tp_dist
    return sl, tp, sl_dist, tp_dist, RR_TARGET

# ==============================
# STRATEGY N1 - ORB (Opening Range Breakout)
# ==============================

def generate_signal_n1(data_m5, data_m15, data_h1, candle_index,
                       current_time, m5_df, state):
    c5 = data_m5['close']
    h5 = data_m5['high']
    l5 = data_m5['low']
    c1 = data_h1['close']

    hour = current_time.hour
    day_key = current_time.strftime('%Y-%m-%d')

    # Reset state on new day
    if state.get('day_key') != day_key:
        state['day_key'] = day_key
        state['or_high'] = None
        state['or_low'] = None
        state['or_built'] = False
        state['traded_today'] = False

    # Build opening range from M5 candles in [ORB_START_UTC, ORB_END_UTC)
    # We scan the df to collect the OR once after the OR window is complete
    if not state['or_built'] and hour >= ORB_END_UTC:
        or_high = None
        or_low = None
        # Walk backward from current candle to find same-day 07-08 UTC candles
        for j in range(candle_index, -1, -1):
            t = m5_df.iloc[j]['datetime']
            if t.strftime('%Y-%m-%d') != day_key:
                break
            h_j = t.hour
            if h_j < ORB_START_UTC:
                break
            if ORB_START_UTC <= h_j < ORB_END_UTC:
                hv = m5_df.iloc[j]['high']
                lv = m5_df.iloc[j]['low']
                if or_high is None or hv > or_high:
                    or_high = hv
                if or_low is None or lv < or_low:
                    or_low = lv
        state['or_high'] = or_high
        state['or_low'] = or_low
        state['or_built'] = True

    if not state['or_built'] or state['or_high'] is None or state['or_low'] is None:
        return None
    if state['traded_today']:
        return None
    if hour < ORB_END_UTC or hour >= ORB_ENTRY_CUTOFF_UTC:
        return None

    trend = trend_direction_h1(c1)
    if trend is None:
        return None

    price = c5[-1]
    direction = None
    if price > state['or_high'] and trend == 'bullish':
        direction = 'bullish'
    elif price < state['or_low'] and trend == 'bearish':
        direction = 'bearish'

    if direction is None:
        return None

    sl, tp, sl_dist, tp_dist, rr = calculate_sl_tp_atr(direction, price, h5, l5, c5)
    state['traded_today'] = True
    return {
        'direction': 'BUY' if direction == 'bullish' else 'SELL',
        'entry': round(price, 2),
        'sl': round(sl, 2),
        'tp': round(tp, 2),
        'sl_dist': round(sl_dist, 2),
        'tp_dist': round(tp_dist, 2),
        'rr': round(rr, 2),
        'score': 0.0,
    }

# ==============================
# STRATEGY N2 - EMA Pullback
# ==============================

def generate_signal_n2(data_m5, data_m15, data_h1, candle_index,
                       current_time, m5_df, state):
    c5 = data_m5['close']
    h5 = data_m5['high']
    l5 = data_m5['low']
    o5 = data_m5['open']
    c15 = data_m15['close']
    h15 = data_m15['high']
    l15 = data_m15['low']
    c1 = data_h1['close']

    if len(c15) < 55 or len(c5) < 3 or len(c1) < 200:
        return None

    trend = trend_direction_h1(c1)
    if trend is None:
        return None

    # M15 EMA50 values for last 3 candles (need series)
    ema50_series = ema_series(c15, 50)
    if len(ema50_series) < 3:
        return None

    # Align last 3 M15 EMA50 values with last 3 M15 candles
    ema_last3 = ema50_series[-3:]
    low_last3 = l15[-3:]
    high_last3 = h15[-3:]

    direction = None
    if trend == 'bullish':
        touched = any(low_last3[k] <= ema_last3[k] for k in range(3))
        if touched and bullish_engulfing(o5, h5, l5, c5):
            direction = 'bullish'
    else:
        touched = any(high_last3[k] >= ema_last3[k] for k in range(3))
        if touched and bearish_engulfing(o5, h5, l5, c5):
            direction = 'bearish'

    if direction is None:
        return None

    price = c5[-1]
    sl, tp, sl_dist, tp_dist, rr = calculate_sl_tp_atr(direction, price, h5, l5, c5)
    return {
        'direction': 'BUY' if direction == 'bullish' else 'SELL',
        'entry': round(price, 2),
        'sl': round(sl, 2),
        'tp': round(tp, 2),
        'sl_dist': round(sl_dist, 2),
        'tp_dist': round(tp_dist, 2),
        'rr': round(rr, 2),
        'score': 0.0,
    }

# ==============================
# STRATEGY N3 - Bollinger Squeeze Breakout
# ==============================

def generate_signal_n3(data_m5, data_m15, data_h1, candle_index,
                       current_time, m5_df, state):
    c5 = data_m5['close']
    h5 = data_m5['high']
    l5 = data_m5['low']
    c15 = data_m15['close']
    c1 = data_h1['close']

    if len(c15) < BB_PERIOD + BB_SQUEEZE_LOOKBACK or len(c1) < 200:
        return None

    trend = trend_direction_h1(c1)
    if trend is None:
        return None

    upper, middle, lower = bollinger_bands(c15, BB_PERIOD, BB_STD)
    if upper is None or middle is None or middle == 0:
        return None

    # Squeeze check: any of last BB_SQUEEZE_LOOKBACK M15 candles had BB-width below threshold
    squeeze = False
    for k in range(BB_SQUEEZE_LOOKBACK):
        end_idx = len(c15) - k
        if end_idx < BB_PERIOD:
            break
        window = c15[:end_idx]
        u, m, lo = bollinger_bands(window, BB_PERIOD, BB_STD)
        if u is None or m is None or m == 0:
            continue
        bb_width = (u - lo) / m
        if bb_width < BB_SQUEEZE_THRESHOLD:
            squeeze = True
            break

    if not squeeze:
        return None

    price = c5[-1]
    direction = None
    if price > upper and trend == 'bullish':
        direction = 'bullish'
    elif price < lower and trend == 'bearish':
        direction = 'bearish'

    if direction is None:
        return None

    sl, tp, sl_dist, tp_dist, rr = calculate_sl_tp_atr(direction, price, h5, l5, c5)
    return {
        'direction': 'BUY' if direction == 'bullish' else 'SELL',
        'entry': round(price, 2),
        'sl': round(sl, 2),
        'tp': round(tp, 2),
        'sl_dist': round(sl_dist, 2),
        'tp_dist': round(tp_dist, 2),
        'rr': round(rr, 2),
        'score': 0.0,
    }

# ==============================
# STRATEGY N4 - RSI Extreme Reversal
# ==============================

def generate_signal_n4(data_m5, data_m15, data_h1, candle_index,
                       current_time, m5_df, state):
    c5 = data_m5['close']
    h5 = data_m5['high']
    l5 = data_m5['low']
    o5 = data_m5['open']
    c15 = data_m15['close']

    if len(c15) < 15 or len(c5) < 3:
        return None

    rsi_m15 = rsi(c15, 14)

    direction = None
    if rsi_m15 < RSI_BUY_THRESHOLD and bullish_engulfing(o5, h5, l5, c5):
        direction = 'bullish'
    elif rsi_m15 > RSI_SELL_THRESHOLD and bearish_engulfing(o5, h5, l5, c5):
        direction = 'bearish'

    if direction is None:
        return None

    price = c5[-1]
    sl, tp, sl_dist, tp_dist, rr = calculate_sl_tp_atr(direction, price, h5, l5, c5)
    return {
        'direction': 'BUY' if direction == 'bullish' else 'SELL',
        'entry': round(price, 2),
        'sl': round(sl, 2),
        'tp': round(tp, 2),
        'sl_dist': round(sl_dist, 2),
        'tp_dist': round(tp_dist, 2),
        'rr': round(rr, 2),
        'score': 0.0,
    }

# ==============================
# STRATEGY N5 - Donchian Breakout
# ==============================

def generate_signal_n5(data_m5, data_m15, data_h1, candle_index,
                       current_time, m5_df, state):
    c5 = data_m5['close']
    h5 = data_m5['high']
    l5 = data_m5['low']
    c15 = data_m15['close']
    h15 = data_m15['high']
    l15 = data_m15['low']
    c1 = data_h1['close']

    if len(c15) < DONCHIAN_PERIOD + 1 or len(c1) < 200 or len(c5) < 15:
        return None

    trend = trend_direction_h1(c1)
    if trend is None:
        return None

    atr_m5 = calculate_atr(h5, l5, c5, 14)
    if atr_m5 < DONCHIAN_ATR_MIN:
        return None

    # Donchian uses M15 highs/lows excluding current forming candle - use last 20 completed
    donchian_high = max(h15[-DONCHIAN_PERIOD-1:-1]) if len(h15) > DONCHIAN_PERIOD else max(h15[-DONCHIAN_PERIOD:])
    donchian_low = min(l15[-DONCHIAN_PERIOD-1:-1]) if len(l15) > DONCHIAN_PERIOD else min(l15[-DONCHIAN_PERIOD:])

    price = c5[-1]
    direction = None
    if price > donchian_high and trend == 'bullish':
        direction = 'bullish'
    elif price < donchian_low and trend == 'bearish':
        direction = 'bearish'

    if direction is None:
        return None

    sl, tp, sl_dist, tp_dist, rr = calculate_sl_tp_atr(direction, price, h5, l5, c5)
    return {
        'direction': 'BUY' if direction == 'bullish' else 'SELL',
        'entry': round(price, 2),
        'sl': round(sl, 2),
        'tp': round(tp, 2),
        'sl_dist': round(sl_dist, 2),
        'tp_dist': round(tp_dist, 2),
        'rr': round(rr, 2),
        'score': 0.0,
    }

# ==============================
# STRATEGY REGISTRY
# ==============================

STRATEGIES = {
    'N1_ORB': generate_signal_n1,
    'N2_EMA_Pullback': generate_signal_n2,
    'N3_BB_Squeeze': generate_signal_n3,
    'N4_RSI_Extreme': generate_signal_n4,
    'N5_Donchian': generate_signal_n5,
}

# ==============================
# BACKTEST ENGINE
# ==============================

def run_backtest(m5, m15, h1, strategy_fn):
    trades = []
    active_trade = None
    last_signal_idx = -1000
    last_result = 'WIN'
    state = {}

    for i in range(200, len(m5)):
        current_time = m5.iloc[i]['datetime']

        # Active trade management (checked EVERY candle, also outside session)
        if active_trade is not None:
            high = m5.iloc[i]['high']
            low = m5.iloc[i]['low']
            closed = False

            if active_trade['direction'] == 'BUY':
                if low <= active_trade['sl']:
                    pnl = -active_trade['sl_dist']
                    trades.append({**active_trade, 'result': 'LOSS', 'pnl': pnl,
                                   'duration_candles': i - active_trade['open_idx']})
                    last_result = 'LOSS'
                    last_signal_idx = i
                    closed = True
                elif high >= active_trade['tp']:
                    pnl = active_trade['tp_dist']
                    trades.append({**active_trade, 'result': 'WIN', 'pnl': pnl,
                                   'duration_candles': i - active_trade['open_idx']})
                    last_result = 'WIN'
                    last_signal_idx = i
                    closed = True
            else:
                if high >= active_trade['sl']:
                    pnl = -active_trade['sl_dist']
                    trades.append({**active_trade, 'result': 'LOSS', 'pnl': pnl,
                                   'duration_candles': i - active_trade['open_idx']})
                    last_result = 'LOSS'
                    last_signal_idx = i
                    closed = True
                elif low <= active_trade['tp']:
                    pnl = active_trade['tp_dist']
                    trades.append({**active_trade, 'result': 'WIN', 'pnl': pnl,
                                   'duration_candles': i - active_trade['open_idx']})
                    last_result = 'WIN'
                    last_signal_idx = i
                    closed = True

            if closed:
                active_trade = None
            elif i - active_trade['open_idx'] > 288:
                active_trade = None
                last_signal_idx = i
                last_result = 'LOSS'

        if active_trade is not None:
            continue

        if not session_allowed(current_time):
            continue

        # Cooldown
        cooldown = COOLDOWN_AFTER_LOSS if last_result == 'LOSS' else COOLDOWN_AFTER_WIN
        if i - last_signal_idx < cooldown:
            continue

        # HTF indices
        m15_idx = map_htf_index(current_time, m15)
        h1_idx = map_htf_index(current_time, h1)
        if m15_idx < 50 or h1_idx < 200:
            continue

        data_m5 = df_to_dict(m5, i + 1)
        data_m15 = df_to_dict(m15, m15_idx + 1)
        data_h1 = df_to_dict(h1, h1_idx + 1)

        signal = strategy_fn(data_m5, data_m15, data_h1, i,
                             current_time, m5, state)

        if signal:
            active_trade = {**signal, 'open_idx': i}
            last_signal_idx = i

    return trades

# ==============================
# METRICS
# ==============================

def compute_metrics(trades, total_days):
    if not trades:
        return {
            'total_trades': 0, 'wins': 0, 'losses': 0, 'winrate': 0,
            'total_pnl': 0, 'avg_pnl': 0, 'avg_rr': 0,
            'trades_per_day': 0, 'max_drawdown': 0, 'expectancy': 0,
        }

    wins = [t for t in trades if t['result'] == 'WIN']
    losses = [t for t in trades if t['result'] == 'LOSS']
    total_pnl = sum(t['pnl'] for t in trades)
    winrate = len(wins) / len(trades) * 100

    avg_win = sum(t['pnl'] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t['pnl'] for t in losses) / len(losses) if losses else 0
    expectancy = (winrate / 100) * avg_win + (1 - winrate / 100) * avg_loss

    equity = [0]
    for t in trades:
        equity.append(equity[-1] + t['pnl'])
    peak = equity[0]
    max_dd = 0
    for e in equity:
        if e > peak:
            peak = e
        dd = peak - e
        if dd > max_dd:
            max_dd = dd

    avg_rr = sum(t['rr'] for t in trades) / len(trades)
    trades_per_day = len(trades) / total_days if total_days > 0 else 0

    return {
        'total_trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'winrate': round(winrate, 1),
        'total_pnl': round(total_pnl, 2),
        'avg_pnl': round(total_pnl / len(trades), 2),
        'avg_rr': round(avg_rr, 2),
        'trades_per_day': round(trades_per_day, 2),
        'max_drawdown': round(max_dd, 2),
        'expectancy': round(expectancy, 2),
    }

# ==============================
# MAIN
# ==============================

def main():
    print('=' * 70)
    print('XAUUSD NON-SMC STRATEGY SHOOTOUT - 5 STRATEGIEN')
    print('=' * 70)
    print()

    m5, m15, h1 = load_data()

    first_time = m5.iloc[0]['datetime']
    last_time = m5.iloc[-1]['datetime']
    total_days = max(1.0, (last_time - first_time).total_seconds() / 86400.0)
    print(f'Backtest-Range: {first_time} bis {last_time} ({total_days:.1f} Tage)')
    print()

    results = {}
    for name, strat_fn in STRATEGIES.items():
        print(f'Running {name}...', flush=True)
        trades = run_backtest(m5, m15, h1, strat_fn)
        metrics = compute_metrics(trades, total_days)
        results[name] = metrics
        print(f'  Trades: {metrics["total_trades"]} | WR: {metrics["winrate"]}% | '
              f'PnL: ${metrics["total_pnl"]} | Exp: ${metrics["expectancy"]} | '
              f'TpD: {metrics["trades_per_day"]}', flush=True)
    print()

    print('=' * 70)
    print('FULL COMPARISON TABLE')
    print('=' * 70)
    df = pd.DataFrame(results).T
    df = df[['total_trades', 'wins', 'losses', 'winrate', 'total_pnl',
             'avg_pnl', 'avg_rr', 'trades_per_day', 'max_drawdown', 'expectancy']]
    print(df.to_string())
    print()

    print('=' * 70)
    print('RANKING BY WINRATE')
    print('=' * 70)
    ranked_wr = sorted(results.items(), key=lambda x: x[1]['winrate'], reverse=True)
    for rank, (name, m) in enumerate(ranked_wr, 1):
        print(f'{rank}. {name:24s} WR: {m["winrate"]:5.1f}% | '
              f'Trades: {m["total_trades"]:3d} | Exp: ${m["expectancy"]:6.2f} | '
              f'PnL: ${m["total_pnl"]:7.2f}')
    print()

    print('=' * 70)
    print('RANKING BY EXPECTANCY')
    print('=' * 70)
    ranked_exp = sorted(results.items(), key=lambda x: x[1]['expectancy'], reverse=True)
    for rank, (name, m) in enumerate(ranked_exp, 1):
        print(f'{rank}. {name:24s} Exp: ${m["expectancy"]:6.2f} | '
              f'Trades: {m["total_trades"]:3d} | WR: {m["winrate"]:5.1f}% | '
              f'PnL: ${m["total_pnl"]:7.2f}')
    print()

    print('=' * 70)
    print('RANKING BY TOTAL PNL')
    print('=' * 70)
    ranked_pnl = sorted(results.items(), key=lambda x: x[1]['total_pnl'], reverse=True)
    for rank, (name, m) in enumerate(ranked_pnl, 1):
        print(f'{rank}. {name:24s} PnL: ${m["total_pnl"]:7.2f} | '
              f'Exp: ${m["expectancy"]:5.2f} | Trades: {m["total_trades"]} | '
              f'WR: {m["winrate"]:5.1f}%')
    print()

    print('=' * 70)
    print('SNIPER RECOMMENDATION')
    print('=' * 70)
    print('Kriterien: trades_per_day >= 1.0, winrate >= 60%, expectancy > 0')
    print()
    qualifying = [
        (name, m) for name, m in results.items()
        if m['trades_per_day'] >= 1.0 and m['winrate'] >= 60.0 and m['expectancy'] > 0
    ]
    if qualifying:
        print(f'Qualifying strategies: {len(qualifying)}')
        for name, m in qualifying:
            print(f'  {name}: TpD={m["trades_per_day"]}, WR={m["winrate"]}%, '
                  f'Exp=${m["expectancy"]}, PnL=${m["total_pnl"]}')
    else:
        print('Keine Variante erfuellt alle Kriterien. Top 3 nach Expectancy mit Gap-Analyse:')
        for name, m in ranked_exp[:3]:
            gap_tpd = max(0.0, 1.0 - m['trades_per_day'])
            gap_wr = max(0.0, 60.0 - m['winrate'])
            gap_exp = max(0.0, 0.01 - m['expectancy'])
            print(f'  {name}: TpD={m["trades_per_day"]} (Gap {gap_tpd:.2f}), '
                  f'WR={m["winrate"]}% (Gap {gap_wr:.1f}pp), '
                  f'Exp=${m["expectancy"]} (Gap ${gap_exp:.2f})')
    print()

    print('=' * 70)
    print('VOLUMEN-QUALITAET-SCATTER')
    print('=' * 70)
    for name, m in results.items():
        print(f'{name}: Trades/Tag={m["trades_per_day"]:.2f}, '
              f'WR={m["winrate"]:.1f}%, '
              f'Exp=${m["expectancy"]:.2f}, '
              f'MaxDD=${m["max_drawdown"]:.2f}')
    print()

    print('=' * 70)
    print('GESAMT-EMPFEHLUNG')
    print('=' * 70)
    if qualifying:
        best = sorted(qualifying, key=lambda x: x[1]['expectancy'], reverse=True)[0]
        name, m = best
        print(f'DEPLOYMENT CANDIDATE: {name}')
        print(f'  Trades/Tag: {m["trades_per_day"]}')
        print(f'  Winrate:    {m["winrate"]}%')
        print(f'  Expectancy: ${m["expectancy"]}')
        print(f'  Total PnL:  ${m["total_pnl"]}')
        print(f'  MaxDD:      ${m["max_drawdown"]}')
        print()
        print('Empfehlung: Script in Live-Bot migrieren, Paper-Trading-Phase starten.')
    else:
        best_exp = ranked_exp[0]
        best_wr = ranked_wr[0]
        print('KEINE Strategie im Sniper-Fenster (TpD>=1.0, WR>=60%, Exp>0).')
        print()
        print(f'Naehester Kandidat nach Expectancy: {best_exp[0]} '
              f'(Exp=${best_exp[1]["expectancy"]}, WR={best_exp[1]["winrate"]}%, '
              f'TpD={best_exp[1]["trades_per_day"]})')
        print(f'Naehester Kandidat nach Winrate:    {best_wr[0]} '
              f'(WR={best_wr[1]["winrate"]}%, TpD={best_wr[1]["trades_per_day"]}, '
              f'Exp=${best_wr[1]["expectancy"]})')
        print()
        print('Ehrliche Einschaetzung:')
        max_tpd = max(m['trades_per_day'] for m in results.values())
        max_wr = max(m['winrate'] for m in results.values())
        if max_tpd < 0.5:
            print('  Volumen ist in allen Strategien sehr niedrig. Das Sniper-Ziel')
            print('  (1-2 Trades/Tag bei 60% WR) ist mit diesen klassischen Ansaetzen')
            print('  und 60 Tagen Daten NICHT realistisch erreichbar.')
        elif max_wr < 50:
            print('  Kein Ansatz erreicht stabile Winrate >= 50%. Evtl. ML-basierte')
            print('  Ensembles oder Regime-Switching noetig, nicht klassische TA.')
        else:
            print('  Signal da, aber Zielkombi (Volumen + WR) nicht gleichzeitig.')
            print('  Weitere Parameter-Tunings oder Hybrid-Ansaetze erforderlich.')
    print()
    print(f'Data source: TwelveData {SYMBOL}, M5/M15/H1, {total_days:.1f} Tage')


if __name__ == '__main__':
    main()
