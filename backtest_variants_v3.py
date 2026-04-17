"""
XAUUSD Strategy Backtest V3 - WR-Optimierung auf V_E Baseline

V2-Batch hat V_E_Aggressive als Sieger gekuert (Exp $2.71, WR 42.9%).
Ziel hier: Winrate auf >=55% heben, Volumen zweitrangig.

Neue Baseline = V_E aus V2:
  cooldown 6/12, RSI 75/25, midpoint=True, score=6.0,
  session 7-21 UTC, bos_required=False, min_rr=2.0,
  chop=False, entry_confirmation=False, structural_sl_tp=False.

Acht Varianten, jeweils NUR ein Hebel veraendert gegenueber Baseline.

Data Loading, Indikatoren, Backtest-Engine und compute_metrics sind 1:1 aus
backtest_variants.py uebernommen.

USAGE (Railway Shell):
python backtest_variants_v3.py
"""

import os
import sys
import time
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
FRIDAY_STOP_UTC = 19

BASELINE = {
    'cooldown_win': 6,
    'cooldown_loss': 12,
    'rsi_block_buy': 75.0,
    'rsi_block_sell': 25.0,
    'ob_midpoint': True,
    'score_threshold': 6.0,
    'bos_required': False,
    'min_rr': 2.0,
    'session_start_utc': 7,
    'session_end_utc': 21,
}


def variant(**overrides):
    cfg = dict(BASELINE)
    cfg.update(overrides)
    return cfg


VARIANTS = {
    'V_BASELINE':      variant(),
    'V_G_Score65':     variant(score_threshold=6.5),
    'V_H_Score70':     variant(score_threshold=7.0),
    'V_I_Score75':     variant(score_threshold=7.5),
    'V_J_LondonOnly':  variant(session_start_utc=7, session_end_utc=11),
    'V_K_LondonNY':    variant(session_start_utc=7, session_end_utc=16),
    'V_L_BOSrequired': variant(bos_required=True),
    'V_M_MinRR25':     variant(min_rr=2.5),
}

# ==============================
# DATA LOADING (TwelveData) - 1:1 aus backtest_variants.py
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
# INDICATORS - 1:1 aus backtest_variants.py
# ==============================

def ema(values, period):
    if len(values) < period:
        return values[-1] if values else 0
    k = 2 / (period + 1)
    ema_val = sum(values[:period]) / period
    for v in values[period:]:
        ema_val = v * k + ema_val * (1 - k)
    return ema_val


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
# STRATEGY LOGIC
# ==============================

def trend_direction(closes):
    if len(closes) < 200:
        return None
    e50 = ema(closes, 50)
    e200 = ema(closes, 200)
    if e50 > e200:
        return 'bullish'
    if e50 < e200:
        return 'bearish'
    return None


def market_structure(highs, lows):
    sh = find_swing_highs(highs)
    sl = find_swing_lows(lows)
    if len(sh) < 2 or len(sl) < 2:
        return 'ranging', 0.0
    hh = sh[-1][1] > sh[-2][1]
    hl = sl[-1][1] > sl[-2][1]
    lh = sh[-1][1] < sh[-2][1]
    ll = sl[-1][1] < sl[-2][1]
    if hh and hl:
        return 'bullish', 1.0
    if lh and ll:
        return 'bearish', 1.0
    if hh or hl:
        return 'bullish', 0.5
    if lh or ll:
        return 'bearish', 0.5
    return 'ranging', 0.0


def detect_bos(highs, lows, closes):
    sh = find_swing_highs(highs)
    sl = find_swing_lows(lows)
    if not sh or not sl:
        return None
    if closes[-1] > sh[-1][1]:
        return 'bullish'
    if closes[-1] < sl[-1][1]:
        return 'bearish'
    return None


def detect_orderblock(highs, lows, opens, closes, direction):
    if len(closes) < 22:
        return None, None
    best = None
    for i in range(len(closes) - 20, len(closes) - 2):
        body = abs(opens[i] - closes[i])
        if body < 0.01:
            continue
        if direction == 'bullish' and closes[i] < opens[i]:
            future_high = max(highs[i+1:i+4])
            displacement = future_high - lows[i]
            if displacement > body * 2:
                mitigated = any(closes[j] < lows[i] for j in range(i+1, len(closes)))
                if not mitigated:
                    best = (lows[i], highs[i])
        if direction == 'bearish' and closes[i] > opens[i]:
            future_low = min(lows[i+1:i+4])
            displacement = highs[i] - future_low
            if displacement > body * 2:
                mitigated = any(closes[j] > highs[i] for j in range(i+1, len(closes)))
                if not mitigated:
                    best = (lows[i], highs[i])
    return best if best else (None, None)


def liquidity_sweep(highs, lows, closes):
    if len(highs) < 10:
        return None
    prev_high = max(highs[-10:-1])
    prev_low = min(lows[-10:-1])
    if highs[-1] > prev_high and closes[-1] < prev_high:
        return 'bearish'
    if lows[-1] < prev_low and closes[-1] > prev_low:
        return 'bullish'
    return None


def premium_discount(highs, lows, price):
    hi = max(highs[-50:])
    lo = min(lows[-50:])
    if hi == lo:
        return 'mid'
    pct = (price - lo) / (hi - lo)
    if pct > 0.65:
        return 'premium'
    if pct < 0.35:
        return 'discount'
    return 'mid'


def calculate_score(direction, trend, structure, struct_str, bos, at_ob, sweep, zone, rsi_val):
    score = 0.0
    if trend == direction:
        score += 2.0
    else:
        score -= 1.0
    if structure == direction:
        score += 1.0 + struct_str
    if bos == direction:
        score += 2.0
    if at_ob:
        score += 1.5
    if sweep == direction:
        score += 0.5
    if direction == 'bullish' and zone == 'discount':
        score += 0.5
    if direction == 'bearish' and zone == 'premium':
        score += 0.5
    if direction == 'bullish' and 30 < rsi_val < 55:
        score += 0.5
    if direction == 'bearish' and 45 < rsi_val < 70:
        score += 0.5
    return round(score, 1)


def calculate_sl_tp_simple(direction, price, highs, lows, closes, min_rr):
    atr_val = calculate_atr(highs, lows, closes)
    if direction == 'bullish':
        swing_lows = find_swing_lows(lows, 3, 3)
        structure_sl = swing_lows[-1][1] if swing_lows else min(lows[-15:])
        sl_dist = price - (structure_sl - atr_val * 0.3)
    else:
        swing_highs = find_swing_highs(highs, 3, 3)
        structure_sl = swing_highs[-1][1] if swing_highs else max(highs[-15:])
        sl_dist = (structure_sl + atr_val * 0.3) - price
    sl_dist = max(8.0, min(12.0, sl_dist))
    sl = price - sl_dist if direction == 'bullish' else price + sl_dist
    tp_dist = sl_dist * min_rr
    tp = price + tp_dist if direction == 'bullish' else price - tp_dist
    return sl, tp, sl_dist, round(float(min_rr), 2)

# ==============================
# SIGNAL GENERATOR (config-parameterisiert, inkl. BOS-Gate + min_rr)
# ==============================

def generate_signal(data_m5, data_m15, data_h1, config, candle_index,
                    last_signal_idx, used_ob, last_result):
    c5 = data_m5['close']
    h5 = data_m5['high']
    l5 = data_m5['low']

    if len(c5) < 200 or len(data_m15['close']) < 50 or len(data_h1['close']) < 200:
        return None, used_ob, last_signal_idx

    cooldown = config['cooldown_loss'] if last_result == 'LOSS' else config['cooldown_win']
    if candle_index - last_signal_idx < cooldown:
        return None, used_ob, last_signal_idx

    c15 = data_m15['close']
    h15 = data_m15['high']
    l15 = data_m15['low']
    o15 = data_m15['open']
    c1 = data_h1['close']
    price = c5[-1]

    trend = trend_direction(c1)
    if trend is None:
        return None, used_ob, last_signal_idx

    direction = trend
    rsi_val = rsi(c5)
    if direction == 'bullish' and rsi_val > config['rsi_block_buy']:
        return None, used_ob, last_signal_idx
    if direction == 'bearish' and rsi_val < config['rsi_block_sell']:
        return None, used_ob, last_signal_idx

    ob_low, ob_high = detect_orderblock(h15, l15, o15, c15, direction)
    if ob_low is None:
        return None, used_ob, last_signal_idx

    if config['ob_midpoint']:
        mid = (ob_low + ob_high) / 2
        if direction == 'bullish' and price > mid:
            return None, used_ob, last_signal_idx
        if direction == 'bearish' and price < mid:
            return None, used_ob, last_signal_idx
    else:
        if not (ob_low <= price <= ob_high):
            return None, used_ob, last_signal_idx

    ob_id = (round(ob_low, 0), round(ob_high, 0))
    if ob_id == used_ob:
        return None, used_ob, last_signal_idx

    sweep = liquidity_sweep(h5, l5, c5)
    zone = premium_discount(h15, l15, price)
    structure, struct_str = market_structure(h15, l15)
    bos = detect_bos(h15, l15, c15)

    score = calculate_score(direction, trend, structure, struct_str, bos,
                            True, sweep, zone, rsi_val)
    if score < config['score_threshold']:
        return None, used_ob, last_signal_idx

    if config['bos_required'] and bos != direction:
        return None, used_ob, last_signal_idx

    sl, tp, sl_dist, rr = calculate_sl_tp_simple(direction, price, h5, l5, c5,
                                                 config['min_rr'])

    signal = {
        'direction': 'BUY' if direction == 'bullish' else 'SELL',
        'entry': round(price, 2),
        'sl': round(sl, 2),
        'tp': round(tp, 2),
        'sl_dist': round(sl_dist, 2),
        'tp_dist': round(abs(tp - price), 2),
        'rr': rr,
        'score': score,
    }
    return signal, ob_id, candle_index

# ==============================
# BACKTEST ENGINE (per-config session, weekend + Friday filter)
# ==============================

def map_htf_index(m5_time, htf_df):
    for i in range(len(htf_df)):
        if htf_df.iloc[i]['datetime'] > m5_time:
            return max(0, i - 1)
    return len(htf_df) - 1


def run_backtest(m5, m15, h1, config):
    trades = []
    active_trade = None
    last_signal_idx = -1000
    used_ob = None
    last_result = 'WIN'
    s_start = config['session_start_utc']
    s_end = config['session_end_utc']

    for i in range(200, len(m5)):
        current_time = m5.iloc[i]['datetime']
        hour = current_time.hour
        dow = current_time.dayofweek

        if hour < s_start or hour >= s_end:
            continue
        if dow >= 5:
            continue
        if dow == 4 and hour >= FRIDAY_STOP_UTC:
            continue

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
                    closed = True
                elif high >= active_trade['tp']:
                    pnl = active_trade['tp_dist']
                    trades.append({**active_trade, 'result': 'WIN', 'pnl': pnl,
                                   'duration_candles': i - active_trade['open_idx']})
                    last_result = 'WIN'
                    closed = True
            else:
                if high >= active_trade['sl']:
                    pnl = -active_trade['sl_dist']
                    trades.append({**active_trade, 'result': 'LOSS', 'pnl': pnl,
                                   'duration_candles': i - active_trade['open_idx']})
                    last_result = 'LOSS'
                    closed = True
                elif low <= active_trade['tp']:
                    pnl = active_trade['tp_dist']
                    trades.append({**active_trade, 'result': 'WIN', 'pnl': pnl,
                                   'duration_candles': i - active_trade['open_idx']})
                    last_result = 'WIN'
                    closed = True

            if closed:
                active_trade = None
            elif i - active_trade['open_idx'] > 288:
                active_trade = None

        if active_trade is not None:
            continue

        m15_idx = map_htf_index(current_time, m15)
        h1_idx = map_htf_index(current_time, h1)

        if m15_idx < 50 or h1_idx < 200:
            continue

        data_m5 = df_to_dict(m5, i + 1)
        data_m15 = df_to_dict(m15, m15_idx + 1)
        data_h1 = df_to_dict(h1, h1_idx + 1)

        signal, new_used_ob, new_last_signal_idx = generate_signal(
            data_m5, data_m15, data_h1, config, i,
            last_signal_idx, used_ob, last_result
        )

        if signal:
            active_trade = {**signal, 'open_idx': i}
            used_ob = new_used_ob
            last_signal_idx = i

    return trades

# ==============================
# METRICS (inkl. trades_per_day)
# ==============================

def compute_metrics(trades):
    if not trades:
        return {
            'total_trades': 0, 'wins': 0, 'losses': 0, 'winrate': 0,
            'total_pnl': 0, 'avg_pnl': 0, 'avg_rr': 0,
            'trades_per_day': 0.0,
            'fast_stop_rate': 0, 'max_drawdown': 0, 'expectancy': 0,
        }

    wins = [t for t in trades if t['result'] == 'WIN']
    losses = [t for t in trades if t['result'] == 'LOSS']
    total_pnl = sum(t['pnl'] for t in trades)
    winrate = len(wins) / len(trades) * 100

    avg_win = sum(t['pnl'] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t['pnl'] for t in losses) / len(losses) if losses else 0
    expectancy = (winrate / 100) * avg_win + (1 - winrate / 100) * avg_loss

    fast_stops = [t for t in losses if t['duration_candles'] <= 2]
    fast_stop_rate = len(fast_stops) / len(losses) * 100 if losses else 0

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

    return {
        'total_trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'winrate': round(winrate, 1),
        'total_pnl': round(total_pnl, 2),
        'avg_pnl': round(total_pnl / len(trades), 2),
        'avg_rr': round(avg_rr, 2),
        'trades_per_day': round(len(trades) / BACKTEST_DAYS, 2),
        'fast_stop_rate': round(fast_stop_rate, 1),
        'max_drawdown': round(max_dd, 2),
        'expectancy': round(expectancy, 2),
    }

# ==============================
# REPORT
# ==============================

def print_comparison_table(results):
    print('=' * 95)
    print('FULL COMPARISON TABLE')
    print('=' * 95)
    df = pd.DataFrame(results).T
    df = df[['total_trades', 'wins', 'losses', 'winrate', 'total_pnl',
            'avg_pnl', 'avg_rr', 'trades_per_day', 'max_drawdown', 'expectancy']]
    print(df.to_string())
    print()


def print_ranking_winrate(results):
    print('=' * 95)
    print('RANKING BY WINRATE')
    print('=' * 95)
    ranked = sorted(results.items(), key=lambda x: x[1]['winrate'], reverse=True)
    for rank, (name, m) in enumerate(ranked, 1):
        print(f'{rank}. {name:18s} WR: {m["winrate"]:5.1f}% | '
              f'Trades: {m["total_trades"]:3d} | Exp: ${m["expectancy"]:6.2f} | '
              f'T/Day: {m["trades_per_day"]:4.2f} | PnL: ${m["total_pnl"]:7.2f}')
    print()
    return ranked


def print_ranking_expectancy(results):
    print('=' * 95)
    print('RANKING BY EXPECTANCY')
    print('=' * 95)
    ranked = sorted(results.items(), key=lambda x: x[1]['expectancy'], reverse=True)
    for rank, (name, m) in enumerate(ranked, 1):
        print(f'{rank}. {name:18s} Exp: ${m["expectancy"]:6.2f} | '
              f'Trades: {m["total_trades"]:3d} | WR: {m["winrate"]:5.1f}% | '
              f'T/Day: {m["trades_per_day"]:4.2f} | PnL: ${m["total_pnl"]:7.2f}')
    print()
    return ranked


def print_ranking_pnl(results):
    print('=' * 95)
    print('RANKING BY TOTAL PNL')
    print('=' * 95)
    ranked = sorted(results.items(), key=lambda x: x[1]['total_pnl'], reverse=True)
    for rank, (name, m) in enumerate(ranked, 1):
        print(f'{rank}. {name:18s} PnL: ${m["total_pnl"]:7.2f} | '
              f'Exp: ${m["expectancy"]:5.2f} | Trades: {m["total_trades"]:3d} | '
              f'T/Day: {m["trades_per_day"]:4.2f} | WR: {m["winrate"]:5.1f}%')
    print()
    return ranked


def print_sniper_recommendation(results, ranked_by_wr):
    print('=' * 95)
    print('SNIPER RECOMMENDATION')
    print('=' * 95)
    print('Kriterien (WR-Fokus): trades_per_day >= 0.25, winrate >= 55%, expectancy > 0')
    print()

    def passes(m):
        return (m['trades_per_day'] >= 0.25
                and m['winrate'] >= 55.0
                and m['expectancy'] > 0)

    matches = [(n, m) for n, m in results.items() if passes(m)]

    if matches:
        matches_sorted = sorted(matches, key=lambda x: x[1]['winrate'], reverse=True)
        print(f'Varianten im WR-Ziel-Fenster: {len(matches_sorted)}')
        for rank, (name, m) in enumerate(matches_sorted, 1):
            print(f'  {rank}. {name}: WR {m["winrate"]}% | Exp ${m["expectancy"]} | '
                  f'T/Day {m["trades_per_day"]} | PnL ${m["total_pnl"]}')
    else:
        print('Keine Variante im WR-Ziel-Fenster')
        best_name, best_m = ranked_by_wr[0]
        print(f'Beste nach Winrate: {best_name} (WR {best_m["winrate"]}%)')
        missing = []
        if best_m['trades_per_day'] < 0.25:
            missing.append(f'trades_per_day={best_m["trades_per_day"]} (Ziel >=0.25)')
        if best_m['winrate'] < 55.0:
            missing.append(f'winrate={best_m["winrate"]}% (Ziel >=55%)')
        if best_m['expectancy'] <= 0:
            missing.append(f'expectancy={best_m["expectancy"]} (Ziel >0)')
        print(f'  Fehlt: {", ".join(missing) if missing else "nichts"}')
    print()


def print_change_vs_baseline(results):
    print('=' * 95)
    print('CHANGE VS BASELINE')
    print('=' * 95)
    if 'V_BASELINE' not in results:
        print('V_BASELINE fehlt, Vergleich nicht moeglich')
        print()
        return
    b = results['V_BASELINE']
    for name, m in results.items():
        if name == 'V_BASELINE':
            continue
        d_trades = m['total_trades'] - b['total_trades']
        d_wr = m['winrate'] - b['winrate']
        d_exp = m['expectancy'] - b['expectancy']
        print(f'{name:18s} WR {m["winrate"]:5.1f}% (baseline {b["winrate"]:5.1f}%, delta {d_wr:+.1f}), '
              f'Trades {m["total_trades"]:3d} (baseline {b["total_trades"]:3d}, delta {d_trades:+d}), '
              f'Exp ${m["expectancy"]:6.2f} (baseline ${b["expectancy"]:6.2f}, delta {d_exp:+.2f})')
    print()

# ==============================
# MAIN
# ==============================

def main():
    print('=' * 95)
    print('XAUUSD STRATEGY BACKTEST V3 - WR-OPTIMIERUNG (8 VARIANTEN)')
    print('=' * 95)
    print(f'Baseline = V_E from V2: {BASELINE}')
    print(f'Fixed: chop_filter=False, entry_confirmation=False, structural_sl_tp=False')
    print(f'Session filter adds: no weekend, no Friday >= {FRIDAY_STOP_UTC} UTC')
    print()

    m5, m15, h1 = load_data()

    results = {}
    for variant_name, config in VARIANTS.items():
        print(f'Running {variant_name} (cooldown {config["cooldown_win"]}/{config["cooldown_loss"]}, '
              f'RSI {config["rsi_block_buy"]}/{config["rsi_block_sell"]}, '
              f'mid={config["ob_midpoint"]}, score>={config["score_threshold"]}, '
              f'session {config["session_start_utc"]}-{config["session_end_utc"]}, '
              f'bos_req={config["bos_required"]}, min_rr={config["min_rr"]})...', flush=True)
        trades = run_backtest(m5, m15, h1, config)
        metrics = compute_metrics(trades)
        results[variant_name] = metrics
        print(f'  Trades: {metrics["total_trades"]} | WR: {metrics["winrate"]}% | '
              f'PnL: ${metrics["total_pnl"]} | T/Day: {metrics["trades_per_day"]} | '
              f'Expectancy: ${metrics["expectancy"]}', flush=True)
    print()

    print_comparison_table(results)
    print_ranking_winrate(results)
    ranked_wr = sorted(results.items(), key=lambda x: x[1]['winrate'], reverse=True)
    print_ranking_expectancy(results)
    print_ranking_pnl(results)
    print_sniper_recommendation(results, ranked_wr)
    print_change_vs_baseline(results)

    print(f'Data source: TwelveData {SYMBOL}, M5/M15/H1, {BACKTEST_DAYS} days')


if __name__ == '__main__':
    main()
