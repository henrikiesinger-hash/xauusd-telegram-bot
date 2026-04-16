'''
XAUUSD Strategy Backtest - Top 5 Strategien Vergleich
Railway-kompatibel, nutzt TwelveData API

USAGE (Railway Shell):
python backtest_top5.py

Der TWELVE_DATA_KEY wird aus den Railway Environment Variables gelesen.
Live-Bot wird NICHT beeinflusst - dieses Script laeuft nur einmal on-demand.
'''

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

COOLDOWN_AFTER_WIN = 24
COOLDOWN_AFTER_LOSS = 48
LONDON_OPEN_UTC = 7
NY_CLOSE_UTC = 21

STRATEGIES = {}

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
