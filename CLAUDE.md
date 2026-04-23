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
news_filter.py   → ForexFactory integration (3min blackout)
config.py        → TELEGRAM_TOKEN, CHAT_ID, SUPABASE_URL, SUPABASE_KEY
trade_log.csv    → Persistent trade history (CSV backup)
```

## Strategy Rules

### Timeframes

- **H1:** Trend direction (EMA 50/200 crossover), Chop filter
- **M15:** Market structure, BOS, Order Blocks, Premium/Discount zones
- **M5:** Entry timing, RSI filter, Liquidity sweeps, ATR for SL/TP

### Entry Conditions (ALL must pass)

1. Session active: London Open (07 UTC) – NY Close (21 UTC), Mon–Thu full, Fri bis 19 UTC (FTMO Gap Rule)
1. Not in cooldown (6 after WIN, 12 after LOSS)
1. H1 trend defined (EMA50 > EMA200 = bullish, vice versa)
1. M15 Order Block detected and price past OB midpoint (V_G config)
1. OB not previously used (one-shot per OB)
1. RSI filter: BUY only if RSI < 75, SELL only if RSI > 25
1. Score ≥ 5.5/10

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
- Session Close: warning at 20:50 UTC, force close at 20:58 UTC (FTMO compliance)
- News blackout: 3min around high-impact events (ForexFactory)

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
- Scheduler: APScheduler: analysis every 5min, trade checks every 2min, weekly review Fri 21 UTC

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

## Development Reminders

### /ultrareview Available
- Cloud multi-agent code review, 3 free runs available (Pro/Max subscription)
- Use BEFORE large deploys: new strategies, FTMO-critical fixes, refactorings
- Skip for small surgical changes (1-5 line edits)
- Command: /ultrareview (current branch) or /ultrareview <PR#>

### Backtest Caveat
- TwelveData Free Plan limits to 5000 M5 candles = 17.4 days, NOT 60 days
- All '60-day' backtest claims are actually ~17 days of data
- Small sample sizes, WR estimates have wide confidence intervals
- Upgrade TwelveData plan for proper 60+ day backtests

### Session Start Workflow
Run /recap at session start to refresh context from previous session.

## Current Status

- **Account:** FTMO 80k 1-Step Standard (Order 23264598, opened 2026-04-09)
- **Live Config:** V_G_Score65 (Score 5.5, Cooldown 6/12, RSI 75/25, OB Midpoint ON)
- **Backup:** Branch v6-live-backup-20260418 at commit 8d2decb (FTMO-Fix V6 state)
- **Regime Detection:** Shadow mode active, logging only, no filtering
- **Next:** Monitor V_G live performance (2 weeks), compare vs backtest

## Development Guidelines

### Bug Fix Prompts

Include: error message, hypothesis for cause, numbered requirements.

### Feature Additions

1. Write plan first, get approval
1. Implement with tests
1. Verify existing signals not degraded
