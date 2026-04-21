# AUDIT_REPORT.md

Date: 2026-04-20
Branch: claude/backtest-sell-diagnosis-2FPSX
Scope: live stack (main.py, strategy.py, indicators.py, data.py, database.py, news_filter.py, config.py) + backtest orphans

## Counts

- CRITICAL: 3
- HIGH: 7
- MEDIUM: 10
- LOW: 15
- **Total: 35**

## Top 5 Most Impactful

1. News blackout timestamp off by 4–5h → trades fire through NFP/FOMC (news_filter.py:95-109)
2. `active_trades` in-memory only → Railway restart drops open trades silently (main.py:32)
3. `check_trade_result` only scans last ~4.2h of M5 → SL/TP between 4.2h–24h misreported as EXPIRED (main.py:790, 795)
4. Two APScheduler threads mutate `active_trades` without lock → append/replace race loses trades (main.py:32, 827, 921, 1103)
5. Session force-close window 2min wide with 2min scheduler → fire at 21:00 skips close, FTMO violation risk (main.py:837-839, 846, 1131)

## CRITICAL

- `news_filter._parse_event_time` strips TZ offset without converting → blackout window off by 4–5h (news_filter.py:95-109)
- `active_trades` in-memory only, never persisted → Railway restart drops all open trades silently (main.py:32)
- `check_trade_result` fetches only 50 M5 candles (~4.2h) → SL/TP hits between 4.2h and 24h are missed, trade marked EXPIRED (main.py:790, 795)

## HIGH

- [HIGH][RESOLVED] `active_trades` mutated by two APScheduler threads without lock → append/replace race can drop trades (main.py:32, 827, 921, 1103). Resolved by commit 8bff461 (active_trades_lock added; all 3 mutation sites covered — main.py:933, 1124, 1156).
- [HIGH][RESOLVED] Session force-close window is 2min wide (20:58–21:00) with 2min scheduler interval → fire at exactly 21:00 skips close, trade stays open past FTMO cutoff (main.py:837-839, 846, 1131). Resolved by commits 1a83846 (widen predicate + misfire_grace) and f9a25f8 (cron backup at 20:58 UTC).
- [HIGH][PHASE1-RESOLVED] `_used_ob` is a single value, not a set → only the last OB is blocked, spec says 'one-shot per OB' (strategy.py:24, 450-451, 474)
  - 2026-04-21: Phase 1 deployed (commit 1791642). Behavioral no-op: added ob_id logging at write-site + daily 07 UTC reset of _used_ob. Purpose: establish 1-2 week baseline of ob_id collision rate before Phase 2 (set swap). Railway boot verified 6 scheduler jobs, reset_used_ob active.
  - Phase 2 decision gate: review log data after 1-2 weeks. If collision rate < 5% and round(...,0) granularity shows no near-price conflicts, proceed with set() swap. Otherwise address id granularity first.
- [HIGH][RESOLVED] `is_in_cooldown_backtest` uses `COOLDOWN_AFTER_WIN` only, never LOSS → backtest/live parity broken (strategy.py:62-64)
  - 2026-04-21: Resolved by commit f3b0081. Mirrored live path if/else branching on _last_trade_result into is_in_cooldown_backtest. Candle-count units preserved (no * 300 multiplier, unlike live path which uses seconds). Behavioral no-op on main: is_in_cooldown_backtest is production-unreachable when BACKTEST_MODE=False. Fix is spec-compliance and future-proofing for backtest harness refactor. Railway verified 6 scheduler jobs, clean boot, no tracebacks.
  - Related task (separate from this finding): audit orphan backtest scripts for 6/12 branching correctness and last_result propagation. V_G strategy selection (WR 56.2%, exp $5.75, DD $16) was driven by those scripts, not by strategy.is_in_cooldown_backtest. Priority HIGH but AFTER the audit sweep completes.
- [HIGH][RESOLVED] `strategy._last_signal_time = 0` default → cooldown always passes on first signal after restart (strategy.py:22, 60)
  - 2026-04-21: Resolved by commit 7d66fc8. Added hydrate_strategy_state() in main.py called after load_open_trades: primary source database.get_all_trades() (Supabase with CSV fallback) uses last completed trade's timestamp + result; fallback to load_open_trades() max(timestamp) with conservative result=LOSS when only open trades exist; cold-start defaults retained otherwise. EXPIRED and SESSION_CLOSE mapped to LOSS for funded FTMO safety, unknown enum defaults to LOSS. All failures fall through to module defaults without crashing boot. Railway boot verified: source=Supabase/CSV raw_result=LOSS mapped=LOSS.
- [HIGH][RESOLVED] Cross-module write `strategy._last_trade_result = result` from main.py mutates another module's private state (main.py:888-889)
  - 2026-04-21: Resolved by commit 37c3a9d. Added public setter strategy.record_trade_resolution(result, ts=None) mirroring the record_signal_live() encapsulation pattern, with optional co-write of _last_signal_time when ts is supplied. Replaces three cross-module writes: main.py:902 (runtime resolution in check_active_trades) and main.py:1173, 1187 (HIGH #6 hydration paths for Supabase/CSV and open_trades fallback). Removed redundant local `import strategy` at the resolution call site. Setter validates result ∈ {WIN, LOSS} and ts > 0 via log.warning without raising, preserving boot robustness. Behavioral no-op: same values at same call sites. Railway boot verified: setter log line emitted from strategy module with matching ts.
- Bare `except: pass` swallows all CSV pnl parse errors in `/stats` (main.py:535)

## MEDIUM

- `rsi()` uses simple mean instead of Wilder's smoothing → values diverge from TradingView/MT4 references (indicators.py:31-32)
- `calculate_atr()` uses simple mean instead of Wilder's smoothing → SL buffer sizing off vs standard (strategy.py:284)
- `data.CACHE` check-then-set not atomic and has no lock → two threads can issue duplicate TwelveData fetches (data.py:13-21)
- Supabase `save_trade` retry always strips `regime` on any failure → network errors misdiagnosed as schema drift (database.py:44-59)
- `_htf_cache` never invalidated on downstream error, stale M15/H1 data can persist up to 300s (strategy.py:25-26, 78-94)
- `detect_orderblock` scans fixed `range(len-20, len-2)` with no OB age filter → can pick 100-candle-old mitigated blocks if `mitigated` check misses (strategy.py:203-229)
- `news_filter` cache keyed by UTC date only, no TTL → stale events persist all day even if feed updates (news_filter.py:11-12, 37-38)
- `_last_outside_session_log` never reset across day boundary → first 'outside session' log after midnight delayed up to 15min (main.py:1035, 1043-1045)
- `check_trade_result` ignores exact wick sequence within a candle → SL-then-TP in same candle counts as LOSS, may misattribute results (main.py:802-815)
- Weekly review runs Fri 21:00 UTC (cron) but Fri signals cut off at 19:00 UTC → fine, but no fallback if scheduler misses that exact minute (main.py:1132)

## LOW

- `RELEVANT_KEYWORDS` defined but never referenced (news_filter.py:19-25)
- `atr()` in indicators.py never imported anywhere (indicators.py:41-57)
- `LONDON_OPEN_UTC`/`NY_CLOSE_UTC` duplicated across 8 files (strategy.py:19-20 + 7 backtest files)
- 6 of 8 backtest scripts use obsolete config (score 6.0, cooldown 24/48) vs live V_G 6.5/6/12 (backtest_top5.py:30-31, backtest_diagnosis.py:43-45, backtest_variants.py:81-83, backtest_variants_v2.py:39, backtest_variants_v3.py:8, backtest_main.py)
- `_last_signal_candle = -999` magic sentinel (strategy.py:23)
- `BACKTEST_MODE` module-level flag toggled externally, no guard (strategy.py:12)
- `handle_command` lowercases text before dispatch → case-insensitive but undocumented (main.py:770, 776)
- `get_candles` prints errors instead of logging (data.py:37, 56)
- `deleteWebhook` startup call wrapped in bare `except: pass` (main.py:1141)
- `init_csv()` runs at module import with no error handling (main.py:52)
- `_client` Supabase singleton never refreshed → stale connection persists if Supabase restarts (database.py:9, 12-29)
- Telegram `parse_mode=HTML` used but user input never escaped → cosmetic only, chat_id gated (main.py:434)
- Dashboard HTML embeds `all_trades` JSON inline, no size cap → page grows unbounded with history (main.py:147, 163-189)
- `format_signal` calls `news_filter.get_next_event()` on every signal → redundant API read, cache mitigates (main.py:1011)
- Regime detection logged but never persisted per-tick — only on signal fire (strategy.py:483-484)

## Dead Code To Delete

- `backtest_main.py`
- `backtest_variants.py`
- `backtest_variants_v2.py`
- `backtest_variants_v3.py`
- `backtest_top5.py`
- `backtest_nonsmc.py`
- `backtest_diagnosis.py`
- `backtest_sell_diagnosis.py`
- `atr()` function in `indicators.py` (orphan, never imported)
- `RELEVANT_KEYWORDS` constant in `news_filter.py` (defined, never referenced)

## New Findings From CRITICAL #3 Analysis

- [HIGH][RESOLVED] Cache in `data.py:19-21` is keyed on `interval` only, not `limit`. `get_candles("5min", 50)` can return 200 cached candles if `run_analysis` populated the cache first; conversely a cold-boot 50 silently caps subsequent 200-candle requests for 60s TTL. Latent bug affecting strategy↔trade-check consistency. Resolved by commit 351cd08 (cache key changed to (interval, limit) tuple at all 5 usage sites in data.py).
- [INFO][RESOLVED] TwelveData credit usage verified via dashboard on 2026-04-21. Plan is Basic 8 (800/day, 8/min). Actual usage ~44/800 with minutely max 3/8. Cache TTL effectively suppresses the theoretical 1440/day upper bound. No action needed.
- [MEDIUM][DEFERRED] SL-before-TP wick sequence within same candle (existing MEDIUM #49) touched by CRITICAL #3 fix loop but deferred by scope; requires separate intra-candle precision analysis.
