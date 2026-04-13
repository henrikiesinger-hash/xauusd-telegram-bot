# XAUUSD SMC Trading Bot — Project Specification

## Identity

- **Asset:** XAUUSD (Gold/USD)
- **Strategy:** Smart Money Concepts (SMC)
- **Mode:** Signal-only (no auto-execution)
- **Deployment:** Railway (Python, Flask on port 8080)
- **Notifications:** Telegram Bot

## Architecture

```
main.py          → Scheduler, Telegram, Trade Management, Flask, Dashboard
strategy.py      → SMC Signal Logic, Scoring, SL/TP
data.py          → Candle Data (get_candles)
database.py      → Supabase Integration, persistente Trade-Daten
indicators.py    → EMA, RSI
config.py        → TELEGRAM_TOKEN, CHAT_ID, SUPABASE_URL, SUPABASE_KEY
trade_log.csv    → Persistent trade history (CSV backup)
```

## Strategy Rules

### Timeframes

- **H1:** Trend direction (EMA 50/200 crossover), Chop filter
- **M15:** Market structure, BOS, Order Blocks, Premium/Discount zones
- **M5:** Entry timing, RSI filter, Liquidity sweeps, ATR for SL/TP

### Entry Conditions (ALL must pass)

1. Session active: London Open (07 UTC) – NY Close (21 UTC), Mon–Fri
1. Not in cooldown (24 candles after WIN, 48 after LOSS)
1. H1 trend defined (EMA50 > EMA200 = bullish, vice versa)
1. H1 not choppy (EMA spread > 0.1%)
1. M15 Order Block detected and price inside OB zone
1. OB not previously used (one-shot per OB)
1. RSI filter: BUY only if RSI < 60, SELL only if RSI > 40
1. Score ≥ 6.0/10

### Scoring System (max ~10 points)

|Component       |Points        |
|----------------|--------------|
|Trend alignment |+2.0 (or -1.0)|
|Structure match |+1.0 to +2.0  |
|BOS confirmation|+2.0          |
|At Order Block  |+1.5          |
|Liquidity sweep |+0.5          |
|Premium/Discount|+0.5          |
|RSI confirmation|+0.5          |

### Confidence Levels

- **SNIPER:** Score ≥ 8.5
- **HIGH:** Score ≥ 7.0
- **MODERATE:** Score ≥ 6.0

### Risk Management

- SL: Structure-based + ATR buffer (0.3x ATR), clamped 8–12 points
- TP: Next swing target, minimum 2:1 RR
- Trade expiry: 24 hours
- No concurrent same-OB trades

## Telegram Interface

### Outgoing Messages

- Signal alerts (entry, SL, TP, RR, score, confidence)
- Trade results (WIN ✅ / LOSS ❌ / EXPIRED ⏰)

### Commands

- `/status` — Bot status, active trades, time
- `/stats` — Win/Loss count, winrate, total PnL, avg per trade
- `/log` — Download trade_log.csv
- `/dashboard` — Full performance overview with streak and best/worst trade

## Deployment

### Railway

- Runtime: Python 3.x
- Start: `gunicorn main:app --bind 0.0.0.0:8080`
- Health check: `GET /` returns `{"status": "running"}`
- Scheduler: APScheduler (1-min interval for analysis + trade checks)

### Environment Variables

- `TELEGRAM_TOKEN` — Bot token from BotFather
- `CHAT_ID` — Authorized Telegram chat ID
- `SUPABASE_URL` — Supabase project URL
- `SUPABASE_KEY` — Supabase anon/service key

### Dependencies

```
flask, requests, apscheduler, gunicorn, numpy, supabase
```

## Hard Rules

1. **NEVER place real trades** — this is a signal bot only
1. **NEVER modify scoring thresholds** without explicit approval
1. **NEVER remove or weaken risk management** (SL clamp, RR minimum)
1. **ALWAYS preserve session filter** — no signals outside London–NY
1. **ALWAYS log trades to CSV** — no silent failures
1. **ALWAYS test changes against existing trade_log.csv data**

## Current Status

- **Phase:** Testing (Week 3)
- **Focus:** Validating signal quality via Telegram
- **Next:** Analyze trade_log.csv results → decide on optimizations

## Development Guidelines

### Bug Fix Prompts

Include: error message, hypothesis for cause, numbered requirements.

### Feature Additions

1. Write plan first, get approval
1. Implement with tests
1. Verify existing signals not degraded

### Context Management

- This file = Tier 1 (always loaded, < 500 tokens target)
- CURRENT_TASK.md = Tier 2 (active task description)
- Individual files = Tier 3 (loaded on demand)
