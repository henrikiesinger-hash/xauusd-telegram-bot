import requests
import pandas as pd
import numpy as np
import time
import os
from datetime import datetime

# =====================================
# SETTINGS
# =====================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("ALPHA_KEY")

SYMBOL = "XAUUSD"

# =====================================
# TELEGRAM
# =====================================

def send_message(text):

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": text
    }

    requests.post(url, json=payload)

# =====================================
# MARKET DATA
# =====================================

def get_data():

    url = f"https://www.alphavantage.co/query?function=FX_INTRADAY&from_symbol=XAU&to_symbol=USD&interval=5min&apikey={API_KEY}"

    r = requests.get(url)
    data = r.json()

    key = "Time Series FX (5min)"

    df = pd.DataFrame(data[key]).T

    df.columns = ["open","high","low","close"]

    df = df.astype(float)

    return df

# =====================================
# INDICATORS
# =====================================

def rsi(series, period=14):

    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))

def atr(df, period=14):

    high_low = df['high'] - df['low']
    high_close = abs(df['high'] - df['close'].shift())
    low_close = abs(df['low'] - df['close'].shift())

    ranges = pd.concat([high_low, high_close, low_close], axis=1)

    true_range = ranges.max(axis=1)

    return true_range.rolling(period).mean()

# =====================================
# SESSION FILTER
# =====================================

def session_active():

    utc = datetime.utcnow()
    hour = utc.hour

    if 7 <= hour < 10:
        return "London"

    if 13 <= hour < 16:
        return "New York"

    return None

# =====================================
# SIGNAL ENGINE
# =====================================

def check_signal(df):

    score = 0

    df['rsi'] = rsi(df['close'])
    df['atr'] = atr(df)

    r = df.iloc[-1]

    # RSI Momentum
    if 45 < r['rsi'] < 65:
        score += 15

    # Volatility
    if r['atr'] > df['atr'].mean():
        score += 15

    # Trend
    ema20 = df['close'].ewm(span=20).mean()
    ema50 = df['close'].ewm(span=50).mean()

    if ema20.iloc[-1] > ema50.iloc[-1]:
        trend = "BUY"
        score += 30

    else:
        trend = "SELL"
        score += 30

    # Breakout Strength
    candle = r['high'] - r['low']

    if candle > r['atr'] * 1.2:
        score += 20

    if score >= 60:
        return trend, score

    return None, score

# =====================================
# TRADE MESSAGE
# =====================================

def send_trade(signal, price, score):

    sl = price - 2 if signal == "BUY" else price + 2
    tp = price + 4 if signal == "BUY" else price - 4

    msg = f"""
🔥 XAUUSD SNIPER SIGNAL

Signal: {signal}
Price: {price}

SL: {sl}
TP: {tp}

Confidence: {score}/100
"""

    send_message(msg)

# =====================================
# BOT START
# =====================================

send_message("XAUUSD AI Sniper Bot V2 gestartet")

# =====================================
# LOOP
# =====================================

while True:

    try:

        session = session_active()

        if session:

            df = get_data()

            signal, score = check_signal(df)

            price = df['close'].iloc[-1]

            if signal:
                send_trade(signal, price, score)

        time.sleep(300)

    except Exception as e:

        print(e)

        time.sleep(60)
def generate_signal(df):

    last = df.iloc[-1]

    price = last["close"]
    ema50 = last["EMA50"]
    ema200 = last["EMA200"]
    rsi = last["RSI"]

    if ema50 > ema200 and rsi > 55:
        signal = "BUY"
    elif ema50 < ema200 and rsi < 45:
        signal = "SELL"
    else:
        signal = None

    return signal, price,
    
    def send_signal(signal, price, rsi):
        tp = price + 3
        sl = price - 2

    if signal == "SELL":
        tp = price - 3
        sl = price + 2

    text = f"""
🔥 XAUUSD AI SIGNAL

Signal: {signal}

Entry: {price}
Take Profit: {tp}
Stop Loss: {sl}

RSI: {rsi}
"""

    send_message(text)

while True:

    df = get_data()

    df = calculate_indicators(df)

    signal, price, rsi = generate_signal(df)

    if signal:
        send_signal(signal, price, rsi)

    time.sleep(300)
