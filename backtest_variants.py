"""
Backtest 8 strategy variants using yfinance Gold Futures (GC=F).

Data source: yfinance GC=F (Gold Futures — close proxy to XAUUSD)
Fallback: Synthetic gold data (GBM calibrated to XAUUSD volatility)
Caching: CSV files to avoid repeated API calls.
Output: Comparison table, rankings by Expectancy and Total PnL, recommendation.

WARNING: GC=F ≠ XAUUSD Spot. Absolute PnL is indicative.
         Relative ranking between variants IS meaningful.
"""

import os
import sys
import logging
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
log = logging.getLogger(__name__)

# ==============================
# DATA LOADING (yfinance + CSV cache + synthetic fallback)
# ==============================

CACHE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILES = {
    'm5': os.path.join(CACHE_DIR, 'cache_m5.csv'),
    'm15': os.path.join(CACHE_DIR, 'cache_m15.csv'),
    'h1': os.path.join(CACHE_DIR, 'cache_h1.csv'),
}

TICKER = 'GC=F'
DATA_SOURCE = 'unknown'


def generate_synthetic_gold(num_candles, tf_minutes, seed=42):
    """
    Generate synthetic XAUUSD-like candles using Geometric Brownian Motion.
    Calibrated to gold's typical intraday volatility (~0.5-0.8% daily).
    Uses a fixed seed for reproducibility across runs.
    """
    rng = np.random.RandomState(seed)

    # Gold params: start ~2350, daily vol ~0.6%, slight upward drift
    price = 2350.0
    daily_bars = int(24 * 60 / tf_minutes)
    # Annualized vol ~15%, convert to per-bar
    annual_vol = 0.15
    bar_vol = annual_vol / np.sqrt(252 * daily_bars)
    # Slight positive drift
    bar_drift = 0.0001 / daily_bars

    opens = []
    highs = []
    lows = []
    closes = []

    for _ in range(num_candles):
        o = price
        # Generate intra-bar price movement
        ret = bar_drift + bar_vol * rng.randn()
        c = o * (1 + ret)

        # High/Low: add realistic wicks
        wick_factor = abs(ret) + bar_vol * 0.5
        h = max(o, c) * (1 + abs(rng.randn()) * wick_factor * 0.5)
        l = min(o, c) * (1 - abs(rng.randn()) * wick_factor * 0.5)

        opens.append(round(o, 2))
        highs.append(round(h, 2))
        lows.append(round(l, 2))
        closes.append(round(c, 2))

        price = c

    return {
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
    }


def load_or_download(timeframe, interval, period):
    """Load from CSV cache or download via yfinance."""
    cache_path = CACHE_FILES[timeframe]

    if os.path.exists(cache_path):
        log.info('Loading %s from cache: %s', timeframe.upper(), cache_path)
        df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        if len(df) > 0:
            return df

    log.info('Downloading %s from yfinance (interval=%s, period=%s)...',
             timeframe.upper(), interval, period)

    try:
        import yfinance as yf
        df = yf.download(TICKER, interval=interval, period=period, progress=False)

        if df is not None and not df.empty:
            # Flatten MultiIndex columns if present
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.to_csv(cache_path)
            log.info('Cached %s candles to %s', len(df), cache_path)
            return df
    except Exception as e:
        log.warning('yfinance download failed for %s: %s', timeframe.upper(), e)

    log.warning('No data for %s — will use synthetic fallback', timeframe.upper())
    return None


def df_to_dict(df):
    """Convert DataFrame to dict format expected by strategy."""
    return {
        'open': df['Open'].tolist(),
        'high': df['High'].tolist(),
        'low': df['Low'].tolist(),
        'close': df['Close'].tolist(),
    }


def load_all_data():
    """Load M5, M15, H1 data. Falls back to synthetic if network unavailable."""
    global DATA_SOURCE

    m5_df = load_or_download('m5', '5m', '60d')
    m15_df = load_or_download('m15', '15m', '60d')
    h1_df = load_or_download('h1', '1h', '60d')

    if m5_df is not None and m15_df is not None and h1_df is not None:
        DATA_SOURCE = 'yfinance (GC=F Gold Futures)'
        m5_df = m5_df.dropna(subset=['Open', 'High', 'Low', 'Close'])
        m15_df = m15_df.dropna(subset=['Open', 'High', 'Low', 'Close'])
        h1_df = h1_df.dropna(subset=['Open', 'High', 'Low', 'Close'])
        return df_to_dict(m5_df), df_to_dict(m15_df), df_to_dict(h1_df)

    # Fallback: synthetic data
    log.info('Generating synthetic gold data (GBM, seed=42)...')
    DATA_SOURCE = 'Synthetic (GBM calibrated to XAUUSD volatility, seed=42)'

    # Generate ~60 trading days of data at each timeframe
    # M5: 60 days * ~14h trading * 12 bars/h = ~10,000 candles
    m5_data = generate_synthetic_gold(10000, 5, seed=42)
    m15_data = generate_synthetic_gold(3400, 15, seed=42)
    h1_data = generate_synthetic_gold(850, 60, seed=42)

    log.info('Synthetic M5: %d | M15: %d | H1: %d candles',
             len(m5_data['close']), len(m15_data['close']), len(h1_data['close']))

    return m5_data, m15_data, h1_data


# ==============================
# 8 VARIANT DEFINITIONS
# ==============================

VARIANTS = [
    {
        'name': 'V1: Baseline',
        'desc': 'Current strategy defaults',
        'score_threshold': 6.0,
        'rsi_buy_max': 60,
        'rsi_sell_min': 40,
        'cooldown_win': 24,
        'cooldown_loss': 48,
        'chop_enabled': True,
        'chop_threshold': 0.1,
        'min_rr': 2.0,
        'sl_min': 8.0,
        'sl_max': 12.0,
    },
    {
        'name': 'V2: Strict Score (>=7.0)',
        'desc': 'Higher quality threshold',
        'score_threshold': 7.0,
        'rsi_buy_max': 60,
        'rsi_sell_min': 40,
        'cooldown_win': 24,
        'cooldown_loss': 48,
        'chop_enabled': True,
        'chop_threshold': 0.1,
        'min_rr': 2.0,
        'sl_min': 8.0,
        'sl_max': 12.0,
    },
    {
        'name': 'V3: Relaxed Score (>=5.5)',
        'desc': 'More trades, lower threshold',
        'score_threshold': 5.5,
        'rsi_buy_max': 60,
        'rsi_sell_min': 40,
        'cooldown_win': 24,
        'cooldown_loss': 48,
        'chop_enabled': True,
        'chop_threshold': 0.1,
        'min_rr': 2.0,
        'sl_min': 8.0,
        'sl_max': 12.0,
    },
    {
        'name': 'V4: Tight RSI (45/55)',
        'desc': 'Tighter RSI filter',
        'score_threshold': 6.0,
        'rsi_buy_max': 55,
        'rsi_sell_min': 45,
        'cooldown_win': 24,
        'cooldown_loss': 48,
        'chop_enabled': True,
        'chop_threshold': 0.1,
        'min_rr': 2.0,
        'sl_min': 8.0,
        'sl_max': 12.0,
    },
    {
        'name': 'V5: Wide RSI (35/65)',
        'desc': 'Wider RSI filter, more entries',
        'score_threshold': 6.0,
        'rsi_buy_max': 65,
        'rsi_sell_min': 35,
        'cooldown_win': 24,
        'cooldown_loss': 48,
        'chop_enabled': True,
        'chop_threshold': 0.1,
        'min_rr': 2.0,
        'sl_min': 8.0,
        'sl_max': 12.0,
    },
    {
        'name': 'V6: Short Cooldown (12/24)',
        'desc': 'Faster re-entry after trades',
        'score_threshold': 6.0,
        'rsi_buy_max': 60,
        'rsi_sell_min': 40,
        'cooldown_win': 12,
        'cooldown_loss': 24,
        'chop_enabled': True,
        'chop_threshold': 0.1,
        'min_rr': 2.0,
        'sl_min': 8.0,
        'sl_max': 12.0,
    },
    {
        'name': 'V7: No Chop Filter',
        'desc': 'Trade in all market conditions',
        'score_threshold': 6.0,
        'rsi_buy_max': 60,
        'rsi_sell_min': 40,
        'cooldown_win': 24,
        'cooldown_loss': 48,
        'chop_enabled': False,
        'chop_threshold': 0.1,
        'min_rr': 2.0,
        'sl_min': 8.0,
        'sl_max': 12.0,
    },
    {
        'name': 'V8: High RR (>=3.0)',
        'desc': 'Require minimum 3:1 reward-risk',
        'score_threshold': 6.0,
        'rsi_buy_max': 60,
        'rsi_sell_min': 40,
        'cooldown_win': 24,
        'cooldown_loss': 48,
        'chop_enabled': True,
        'chop_threshold': 0.1,
        'min_rr': 3.0,
        'sl_min': 8.0,
        'sl_max': 12.0,
    },
]


# ==============================
# MOCK HTF STORE (per-variant isolation)
# ==============================

_htf_store = {'m15': None, 'h1': None}


def mock_get_candles(interval, limit=200):
    if '15' in interval:
        return _htf_store['m15']
    if '1h' in interval or '60' in interval:
        return _htf_store['h1']
    return None


# ==============================
# AGGREGATION (M5 -> M15 / M5 -> H1)
# ==============================

def aggregate_candles(data, factor):
    agg = {'open': [], 'high': [], 'low': [], 'close': []}
    total = len(data['close'])

    for i in range(0, total - factor + 1, factor):
        agg['open'].append(data['open'][i])
        agg['high'].append(max(data['high'][i:i + factor]))
        agg['low'].append(min(data['low'][i:i + factor]))
        agg['close'].append(data['close'][i + factor - 1])

    return agg


# ==============================
# TRADE SIMULATION
# ==============================

def simulate_trade(data, entry_index, direction, entry, sl, tp):
    for i in range(entry_index + 1, len(data['close'])):
        high = data['high'][i]
        low = data['low'][i]

        if direction == 'BUY':
            if low <= sl:
                return 'LOSS', round(-(entry - sl), 2)
            if high >= tp:
                return 'WIN', round(tp - entry, 2)
        else:
            if high >= sl:
                return 'LOSS', round(-(sl - entry), 2)
            if low <= tp:
                return 'WIN', round(entry - tp, 2)

    return 'NO RESULT', 0.0


# ==============================
# VARIANT SIGNAL GENERATOR
# ==============================

def generate_signal_variant(data_m5, candle_index, variant, m15_data, h1_data):
    """
    Generate signal using variant-specific parameters.
    Directly uses strategy module functions but applies variant overrides.
    """
    from indicators import ema as calc_ema, rsi as calc_rsi
    from strategy import (
        trend_direction, is_choppy, detect_orderblock,
        market_structure, detect_bos, liquidity_sweep,
        premium_discount, calculate_score, calculate_sl_tp,
    )

    c5 = data_m5['close']
    h5 = data_m5['high']
    l5 = data_m5['low']

    c15 = m15_data['close']
    h15 = m15_data['high']
    l15 = m15_data['low']
    o15 = m15_data['open']

    c1 = h1_data['close']
    price = c5[-1]

    # H1 trend
    trend = trend_direction(c1)
    if trend is None:
        return None

    # Chop filter (variant-controlled)
    if variant['chop_enabled'] and is_choppy(c1, variant['chop_threshold']):
        return None

    direction = trend

    # RSI filter (variant-controlled)
    rsi_val = calc_rsi(c5)
    if direction == 'bullish' and rsi_val > variant['rsi_buy_max']:
        return None
    if direction == 'bearish' and rsi_val < variant['rsi_sell_min']:
        return None

    # Order Block detection
    ob_low, ob_high = detect_orderblock(h15, l15, o15, c15, direction)
    if ob_low is None:
        return None

    if not (ob_low <= price <= ob_high):
        return None

    # Structure + BOS
    sweep = liquidity_sweep(h5, l5, c5)
    zone = premium_discount(h15, l15, price)
    structure, struct_str = market_structure(h15, l15)
    bos = detect_bos(h15, l15, c15)

    # Score (variant-controlled threshold)
    score = calculate_score(
        direction, trend, structure, struct_str, bos,
        True, sweep, zone, rsi_val
    )
    if score < variant['score_threshold']:
        return None

    # SL/TP
    sl, tp, sl_dist, rr = calculate_sl_tp(direction, price, h5, l5, c5)

    # Clamp SL to variant bounds
    sl_dist = max(variant['sl_min'], min(variant['sl_max'], sl_dist))
    if direction == 'bullish':
        sl = price - sl_dist
    else:
        sl = price + sl_dist

    # Recalculate TP to meet minimum RR
    tp_dist = abs(tp - price)
    if tp_dist < sl_dist * variant['min_rr']:
        tp_dist = sl_dist * variant['min_rr']
    tp = price + tp_dist if direction == 'bullish' else price - tp_dist
    rr = round(tp_dist / sl_dist, 1)

    if score >= 8.5:
        confidence = 'SNIPER'
    elif score >= 7.0:
        confidence = 'HIGH'
    else:
        confidence = 'MODERATE'

    return {
        'direction': 'BUY' if direction == 'bullish' else 'SELL',
        'entry': round(price, 2),
        'sl': round(sl, 2),
        'tp': round(tp, 2),
        'rr': rr,
        'sl_dist': round(sl_dist, 2),
        'score': score,
        'confidence': confidence,
    }


# ==============================
# RUN SINGLE VARIANT
# ==============================

def run_variant(variant, data_m5, data_m15, data_h1):
    """Run backtest for a single variant. Returns results dict."""
    total_candles = len(data_m5['close'])

    wins = 0
    losses = 0
    no_result = 0
    total = 0
    total_pnl = 0.0
    pnl_list = []
    last_signal_candle = -999

    # Need enough candles for H1 aggregation (12:1) to have 200+ H1 candles
    # 200 * 12 = 2400, so start at 2500 to be safe
    start_index = 2500
    if start_index >= total_candles:
        # Not enough data — try smaller start
        start_index = max(500, total_candles // 2)

    for i in range(start_index, total_candles):
        # Cooldown check
        if (i - last_signal_candle) < variant['cooldown_win']:
            continue

        sub_all = {
            'open': data_m5['open'][:i],
            'high': data_m5['high'][:i],
            'low': data_m5['low'][:i],
            'close': data_m5['close'][:i],
        }

        m15 = aggregate_candles(sub_all, 3)
        h1 = aggregate_candles(sub_all, 12)

        if len(h1['close']) < 200 or len(m15['close']) < 50:
            continue

        signal = generate_signal_variant(sub_all, i, variant, m15, h1)

        if signal:
            total += 1
            last_signal_candle = i

            result, pnl = simulate_trade(
                data_m5, i,
                signal['direction'],
                signal['entry'],
                signal['sl'],
                signal['tp'],
            )

            total_pnl += pnl
            pnl_list.append(pnl)

            if result == 'WIN':
                wins += 1
            elif result == 'LOSS':
                losses += 1
            else:
                no_result += 1

    resolved = wins + losses
    winrate = (wins / resolved * 100) if resolved > 0 else 0.0
    avg_pnl = (total_pnl / resolved) if resolved > 0 else 0.0

    # Expectancy = (winrate * avg_win) - (lossrate * avg_loss)
    win_pnls = [p for p in pnl_list if p > 0]
    loss_pnls = [p for p in pnl_list if p < 0]
    avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0.0
    avg_loss = abs(sum(loss_pnls) / len(loss_pnls)) if loss_pnls else 0.0

    if resolved > 0:
        expectancy = (winrate / 100 * avg_win) - ((1 - winrate / 100) * avg_loss)
    else:
        expectancy = 0.0

    return {
        'name': variant['name'],
        'desc': variant['desc'],
        'total': total,
        'wins': wins,
        'losses': losses,
        'no_result': no_result,
        'resolved': resolved,
        'winrate': winrate,
        'total_pnl': total_pnl,
        'avg_pnl': avg_pnl,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'expectancy': expectancy,
    }


# ==============================
# OUTPUT
# ==============================

def print_results(results):
    """Print comparison table and rankings."""

    print('\n' + '=' * 90)
    print(f'BACKTEST VARIANT COMPARISON — Data: {DATA_SOURCE}')
    print('=' * 90)

    # Header
    print(f'{"Variant":<28} {"Trades":>6} {"W":>4} {"L":>4} {"WR%":>6} '
          f'{"Tot PnL":>9} {"Avg PnL":>8} {"Expect":>8} {"AvgW":>7} {"AvgL":>7}')
    print('-' * 90)

    for r in results:
        print(f'{r["name"]:<28} {r["total"]:>6} {r["wins"]:>4} {r["losses"]:>4} '
              f'{r["winrate"]:>5.1f}% {r["total_pnl"]:>+9.2f} {r["avg_pnl"]:>+8.2f} '
              f'{r["expectancy"]:>+8.2f} {r["avg_win"]:>7.2f} {r["avg_loss"]:>7.2f}')

    # Ranking by Expectancy
    print('\n' + '=' * 60)
    print('RANKING BY EXPECTANCY (higher = better)')
    print('=' * 60)
    ranked = sorted(results, key=lambda x: x['expectancy'], reverse=True)
    for i, r in enumerate(ranked, 1):
        marker = ' <<<' if i == 1 else ''
        print(f'  #{i}: {r["name"]:<28} Expectancy: {r["expectancy"]:>+.2f}{marker}')

    # Ranking by Total PnL
    print('\n' + '=' * 60)
    print('RANKING BY TOTAL PnL (higher = better)')
    print('=' * 60)
    ranked_pnl = sorted(results, key=lambda x: x['total_pnl'], reverse=True)
    for i, r in enumerate(ranked_pnl, 1):
        marker = ' <<<' if i == 1 else ''
        print(f'  #{i}: {r["name"]:<28} Total PnL: {r["total_pnl"]:>+.2f}{marker}')

    # Recommendation
    print('\n' + '=' * 60)
    print('RECOMMENDATION')
    print('=' * 60)

    best_exp = ranked[0]
    best_pnl = ranked_pnl[0]

    if best_exp['name'] == best_pnl['name']:
        print(f'\n  Clear winner: {best_exp["name"]}')
        print(f'  - Best Expectancy: {best_exp["expectancy"]:+.2f}')
        print(f'  - Best Total PnL:  {best_exp["total_pnl"]:+.2f}')
        print(f'  - Winrate:         {best_exp["winrate"]:.1f}%')
        print(f'  - Trades:          {best_exp["total"]}')
        print(f'  Reason: Dominates both Expectancy and PnL.')
    else:
        print(f'\n  Best Expectancy: {best_exp["name"]}')
        print(f'    Expectancy={best_exp["expectancy"]:+.2f}, '
              f'PnL={best_exp["total_pnl"]:+.2f}, '
              f'WR={best_exp["winrate"]:.1f}%, '
              f'Trades={best_exp["total"]}')
        print(f'\n  Best Total PnL: {best_pnl["name"]}')
        print(f'    Expectancy={best_pnl["expectancy"]:+.2f}, '
              f'PnL={best_pnl["total_pnl"]:+.2f}, '
              f'WR={best_pnl["winrate"]:.1f}%, '
              f'Trades={best_pnl["total"]}')

        # Decide recommendation
        if best_exp['resolved'] >= 5 and best_exp['expectancy'] > 0:
            print(f'\n  >>> Recommended: {best_exp["name"]}')
            print(f'  Reason: Positive expectancy with sufficient sample size ({best_exp["resolved"]} resolved).')
            print(f'  Expectancy is the more robust metric for forward performance.')
        elif best_pnl['total_pnl'] > 0:
            print(f'\n  >>> Recommended: {best_pnl["name"]}')
            print(f'  Reason: Highest cumulative PnL ({best_pnl["total_pnl"]:+.2f}).')
        else:
            print(f'\n  >>> No clear winner. Consider extending the test period.')

    # Warning
    print('\n  NOTE: GC=F (Gold Futures) ≠ XAUUSD Spot.')
    print('  Absolute PnL is indicative. Relative ranking is meaningful.')
    print()


# ==============================
# MAIN
# ==============================

def main():
    log.info('Loading data...')
    data_m5, data_m15, data_h1 = load_all_data()

    if data_m5 is None:
        log.error('Failed to load data. Exiting.')
        sys.exit(1)

    log.info('M5: %d candles | M15: %d candles | H1: %d candles',
             len(data_m5['close']), len(data_m15['close']), len(data_h1['close']))

    # We use the M5 data directly (not aggregated from M15/H1)
    # because yfinance gives us real candles at each timeframe.
    # For the variant backtest, we aggregate M5 -> M15/H1 to match
    # the original backtest approach and feed HTF data per-candle.

    total_m5 = len(data_m5['close'])
    if total_m5 < 3000:
        log.warning('Only %d M5 candles available (ideally 5000+). '
                     'Results may have fewer trades.', total_m5)

    results = []

    for i, variant in enumerate(VARIANTS):
        log.info('Running %s (%d/%d): %s',
                 variant['name'], i + 1, len(VARIANTS), variant['desc'])
        result = run_variant(variant, data_m5, data_m15, data_h1)
        results.append(result)
        log.info('  -> %d trades, WR=%.1f%%, PnL=%+.2f, Exp=%+.2f',
                 result['total'], result['winrate'],
                 result['total_pnl'], result['expectancy'])

    print_results(results)


if __name__ == '__main__':
    main()
