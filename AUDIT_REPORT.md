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
- [HIGH][RESOLVED] Bare `except: pass` swallows all CSV pnl parse errors in `/stats` (main.py:541)
  - Context: /stats Telegram command's CSV fallback path had bare `except: pass` around pnl parsing, silently swallowing all exceptions (including KeyboardInterrupt/SystemExit) and creating internal stats inconsistency — a row with unparseable pnl still incremented wins/losses but was excluded from total_pnl, so winrate basis and total_pnl diverged.
  - 2026-04-21: Resolved by commit 5cbe360. Replaced bare except with `except (ValueError, KeyError, TypeError) as e:` so KeyboardInterrupt/SystemExit now propagate. Moved wins/losses increment INSIDE try block — rows with bad pnl are now skipped entirely, keeping stats arithmetic internally consistent. Added skipped_rows counter with log.warning format `stats: skipping row, parse failed ts=<ts>: <exc>` using row.get('timestamp', '<no-ts>') to avoid KeyError in handler. Conditional `(N rows skipped)` suffix on Total PnL output only when skipped_rows > 0 — byte-identical to previous output when 0. Defensive `skipped_rows = 0` init in BOTH Supabase-primary and CSV-fallback branches prevents NameError in shared output path.
  - Verification: Railway clean boot confirmed post-5cbe360 (no syntax/import issues, scheduler started normally). /stats runtime test passed Supabase-primary path with byte-identical output to pre-fix state. Defensive init for Supabase-branch confirmed necessary (would have NameError'd in output construction otherwise). CSV-fallback-path parse behavior verified via code review only (cannot be forced without Supabase downtime). Out of scope: main.py:1230 deleteWebhook bare except remains (tracked under LOW).

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

## Backtest-Parity Audit — Dim A + B + C Findings (2026-04-22)

Scope: Static code-parity audit between Live (`origin/main @ 9b50149`,
post-HIGH-sweep) and V3 backtest script
(`3c26c91:backtest_variants_v3.py`). Dimensions A (Indicator Math),
B (last_result / Cooldown propagation), C (Session / Friday-Stop /
Session-Close). V_G live-deployment = manual parameter mutation of
`strategy.py` (commit e1dbee1), not a V3 code-merge. Findings below
affect confidence in V_G backtest metrics (WR 56.2%, Exp $5.75,
DD $16) but do not hard-invalidate V_G selection (relative ranking
vs V6 / other variants is robust because Dim A/B/C artefacts hit all
variants uniformly in the same batch backtest engine).

### Findings

**A-1 — EMA math SHIFTED (boundary-BREAKING-conditional)**
- Severity: MEDIUM
- Status: DEFERRED
- Live uses `np.convolve` with full-window exponential weights.
  V3 uses classical iterative SMA-seed + k=2/(period+1). Worst-case
  period=200: ~10 price-points spread on boundary candles.
- Downstream: `trend_direction` binary gate flips 20-50 M5-candles
  later in V3 than Live during sideways phases, nudging V3 toward
  more BUY signals during Feb-Apr 2026 uptrend.
- Impact envelope: WR +/- 3pp, Exp +/- $1, DD $12-$20.
- RSI and ATR math confirmed IDENTICAL (<1e-14).

**B-1 — Expiry / Session-Close Result-Mapping divergent (BEDINGT BREAKING)**
- Severity: MEDIUM (bedingt BREAKING for Hang-Trade scenarios)
- Status: DEFERRED
- V3 L487-488: `elif i - active_trade['open_idx'] > 288:
  active_trade = None` — no `trades.append`, no `last_result` update.
  Expired trades in V3 neither count as a trade nor as a LOSS; next
  cooldown uses the previous `last_result`.
- Live: `hydrate_strategy_state()` L1166-1199 maps
  `EXPIRED -> LOSS` and `SESSION_CLOSE -> LOSS` via `result_map`
  L1171-1172 at bot startup. `check_active_trades` logs
  `SESSION_CLOSE` L895 and `EXPIRED` L939 into CSV/Supabase.
- Sub-findings 1-9 of Dim B all IDENTICAL or EQUIVALENT (constants
  6/12, branching on last_result, candle-index units within
  backtest-path, str type + WIN default, set-timing on entry candle,
  init-value -999/-1000 both cooldown-clear, sync-vs-async result
  propagation blocked by open-trade gate, list+lock vs single-var
  semantically identical, hydration cold-start both 'WIN').
- Impact: 1-3 of V_G 16 trades potentially divergent. WR-risk -6pp
  to -19pp worst-case. DD-direction uncertain (SESSION_CLOSE PnL
  often smaller than full-SL, could lower DD in Live).

**C-1 — No 20:58 UTC Force-Close in V3 (DIVERGENT)**
- Severity: MEDIUM (downgraded from HIGH; overlaps with B-1)
- Status: DEFERRED
- Live `check_active_trades` L871-895 flat-closes open trades at
  20:58 UTC via current-price PnL and logs `SESSION_CLOSE`. V3
  L447-448 only `continue`s the run-loop at session-end, leaving
  `active_trade` open for the next active candle (next day 7 UTC,
  skipping weekend).
- Quantification: 0-2 of V_G 16 trades affected. V3-biased-optimistic
  on hang-trades that recover over weekend; no bias on strictly
  session-compliant trades.

**C-2 — 24h-Expiry semantic divergence (DIVERGENT)**
- Severity: MEDIUM
- Status: DEFERRED
- Live main.py:L938-940: `age_hours > 24` -> `log_trade(trade,
  'EXPIRED', 0, age_hours)` — appears in CSV with PnL=0.
- V3 L488: `elif i - active_trade['open_idx'] > 288:
  active_trade = None` — silent drop, no trades.append.
- Impact: 0-1 V_G trades affected. Live counts expired as 0-PnL in
  WR-denominator; V3 excludes from denominator entirely.

**C-3 — log_trade on SESSION_CLOSE / EXPIRED misses
record_trade_resolution call in running process**
- Severity: LOW
- Status: ACTIVE (cleanup candidate, defer fix until Phase 3 decision)
- main.py:L895 (`log_trade(trade, 'SESSION_CLOSE', ...)`) and L939
  (`log_trade(trade, 'EXPIRED', ...)`) do not call
  `strategy.record_trade_resolution(...)` in the running process.
  `_last_trade_result` remains at pre-event value.
- Practically cosmetic: next signal-eligible candle is 10+ hours
  away (next day 7 UTC), cooldown of 6*300s / 12*300s long expired.
  Bot-restart hydration L1166-1199 covers the restart case.
- Fix candidate (NOT TO BE APPLIED NOW): add
  `strategy.record_trade_resolution('LOSS')` after L895 and L940.

**C-4 — No Telegram 20:50 warning in V3 (cosmetic)**
- Severity: LOW
- Status: DEFERRED (N/A for parity; Live-only UX)

**C-5 — Force-close cron missing day_of_week filter (Live runtime issue)**
- Severity: MEDIUM
- Status: ACTIVE (runtime Live issue, out-of-scope for V3 parity)
- main.py:L1225:
  `scheduler.add_job(check_active_trades, 'cron', hour=20,
  minute=58, misfire_grace_time=60, id='force_close_cron_backup')`
  — no `day_of_week` parameter, fires Mo-So.
- Edge-case: Bot restart Fri-Sat with lingering open trade -> Sat
  20:58 cron fires on stale weekend TwelveData price -> unreliable
  PnL estimate logged to CSV/Supabase.
- Current live /stats WR 16.7% / -$32 / 6 trades may be partly
  tainted by daily SESSION_CLOSE events on Tue/Wed/Thu that should
  only trigger on Fri per FTMO gap-trading rationale.
- Fix candidate (NOT TO BE APPLIED NOW):
  `scheduler.add_job(check_active_trades, 'cron', day_of_week='fri',
  hour=20, minute=58, ...)`.

### RSI-75/25 Threshold — IDENTICAL

Signal-block thresholds Live strategy.py:L460/462 (75/25) match V3
config `rsi_block_buy`/`rsi_block_sell` (L43/44 -> L371/373) for V_G
baseline. Score-bonus bands 30-55 bullish / 45-70 bearish identical
Live:L379/381 vs V3:L318/320. Combined with Dim-A RSI math
IDENTICAL: RSI dimension fully parity-compliant.

### Combined A+B+C Worst-Case Impact Envelope for V_G

- WR: 56.2% -> live-realised band 37-60% (worst-case overlap of
  Dim A shift, Dim B expiry drops, Dim C session-close flats;
  realistically 50-59%)
- Exp: $5.75 -> $1.75-$6.50 (realistically $4-$6)
- DD: $16 -> $12-$22
- Trade-count: 16 -> 14-18

### V_G Selection Defensibility: BEDINGT TRAGBAR

V_G was selected over V6 on relative-score-threshold delta, which is
robust against Dim A/B/C artefacts because all variants run through
the same V3 engine. Absolute metrics carry +/- 5pp WR / +/- $2 Exp /
+/- $6 DD uncertainty margin. Re-backtest with live-codebase-aligned
engine recommended after 20-trade live-series, not before.

### Dimensions Remaining

- Dim D: OB-Detection parity (mitigation check, displacement ratio,
  OB midpoint entry, _used_ob one-shot gate) — NEXT
- Dim E: SL/TP Structural vs Simple
- Dim F: Indicator Thresholds in Score Calculation
- Dim G: Data-Loading (M5=5000 candles)
