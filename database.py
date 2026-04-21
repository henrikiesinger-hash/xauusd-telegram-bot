import logging
import time
import csv
import os
from config import SUPABASE_URL, SUPABASE_KEY

log = logging.getLogger("database")

_client = None


def _get_client():
    global _client

    if _client is not None:
        return _client

    if not SUPABASE_URL or not SUPABASE_KEY:
        log.warning("Supabase credentials missing")
        return None

    try:
        from supabase import create_client
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
        log.info("Supabase connected")
        return _client
    except Exception as e:
        log.error("Supabase connection failed: %s", e)
        return None


def save_trade(trade_data):
    client = _get_client()
    if not client:
        log.error('Supabase save skipped: no client')
        return False

    try:
        client.table('trades').insert(trade_data).execute()
        log.info('Supabase saved: %s %s | %s',
                 trade_data.get('direction'), trade_data.get('entry'),
                 trade_data.get('result'))
        return True
    except Exception as e:
        log.error('Supabase save failed: %s', e)

        # Retry without optional fields that may not exist in table
        optional_fields = ['regime']
        retry_data = {k: v for k, v in trade_data.items() if k not in optional_fields}

        try:
            client.table('trades').insert(retry_data).execute()
            log.info('Supabase saved on retry (without optional fields): %s %s | %s',
                     retry_data.get('direction'), retry_data.get('entry'),
                     retry_data.get('result'))
            return True
        except Exception as e2:
            log.error('Supabase retry also failed: %s', e2)
            return False


def get_all_trades():
    client = _get_client()
    if not client:
        log.warning('Supabase client unavailable, falling back to CSV')
        return _get_all_trades_csv()

    try:
        resp = client.table('trades').select('*').order('timestamp').execute()
        data = resp.data

        if data is None or len(data) == 0:
            log.warning('Supabase returned empty data (RLS enabled?), falling back to CSV')
            return _get_all_trades_csv()

        return data
    except Exception as e:
        log.error('Supabase get_all_trades failed: %s', e)
        return _get_all_trades_csv()


def _get_all_trades_csv():
    csv_file = 'trade_log.csv'
    if not os.path.exists(csv_file):
        return None

    try:
        trades = []
        with open(csv_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                trades.append({
                    'timestamp': float(row.get('timestamp', 0)),
                    'date_utc': row.get('date_utc', ''),
                    'direction': row.get('direction', ''),
                    'entry': float(row.get('entry', 0)),
                    'sl': float(row.get('sl', 0)),
                    'tp': float(row.get('tp', 0)),
                    'sl_dist': float(row.get('sl_dist', 0)),
                    'tp_dist': float(row.get('tp_dist', 0)),
                    'rr': float(row.get('rr', 0)),
                    'score': float(row.get('score', 0)),
                    'confidence': row.get('confidence', ''),
                    'result': row.get('result', ''),
                    'pnl': float(row.get('pnl', 0)),
                    'duration_h': float(row.get('duration_h', 0)),
                    'regime': row.get('regime', ''),
                })

        log.info('CSV fallback loaded %s trades', len(trades))
        return trades if trades else None
    except Exception as e:
        log.error('CSV fallback failed: %s', e)
        return None


def get_recent_trades(n=20):
    client = _get_client()
    if not client:
        all_trades = _get_all_trades_csv()
        return list(reversed(all_trades[-n:])) if all_trades else None

    try:
        resp = (client.table('trades')
                .select('*')
                .order('timestamp', desc=True)
                .limit(n)
                .execute())
        data = resp.data

        if data is None or len(data) == 0:
            all_trades = _get_all_trades_csv()
            return list(reversed(all_trades[-n:])) if all_trades else None

        return data
    except Exception as e:
        log.error('Supabase get_recent_trades failed: %s', e)
        all_trades = _get_all_trades_csv()
        return list(reversed(all_trades[-n:])) if all_trades else None


def get_trades_since(since_timestamp):
    client = _get_client()
    if not client:
        return None

    try:
        resp = (client.table("trades")
                .select("*")
                .gte("timestamp", since_timestamp)
                .order("timestamp")
                .execute())
        return resp.data
    except Exception as e:
        log.error("Supabase get_trades_since failed: %s", e)
        return None


def get_trades_today():
    now = time.gmtime()
    midnight = time.mktime(time.strptime(
        time.strftime("%Y-%m-%d", now), "%Y-%m-%d"
    )) - time.timezone
    return get_trades_since(midnight)


def get_weekly_pnl(weeks=4):
    now = time.time()
    result = []

    for w in range(weeks):
        end = now - w * 7 * 86400
        start = end - 7 * 86400
        trades = get_trades_since(start)

        if trades is None:
            result.append({"week": w + 1, "pnl": 0, "trades": 0})
            continue

        week_trades = [t for t in trades if t.get("timestamp", 0) < end]
        pnl = sum(t.get("pnl", 0) for t in week_trades)
        result.append({"week": w + 1, "pnl": round(pnl, 2), "trades": len(week_trades)})

    return result


def save_open_trades(trades):
    client = _get_client()
    if not client:
        log.error('save_open_trades: no Supabase client')
        return False

    if not trades:
        try:
            client.table('open_trades').delete().neq('timestamp', 0).execute()
            return True
        except Exception as e:
            log.error('save_open_trades: clear failed: %s', e)
            return False

    rows = []
    for t in trades:
        rows.append({
            'timestamp': t['timestamp'],
            'direction': t['direction'],
            'entry': t['entry'],
            'sl': t['sl'],
            'tp': t['tp'],
            'sl_dist': t.get('sl_dist', 0),
            'tp_dist': t.get('tp_dist', 0),
            'score': t.get('score', 0),
            'confidence': t.get('confidence', ''),
            'regime': t.get('regime', ''),
        })

    try:
        client.table('open_trades').upsert(rows, on_conflict='timestamp').execute()
    except Exception as e:
        if '23505' in str(e):
            log.warning('save_open_trades: duplicate key, retrying with +1us offset')
            for r in rows:
                r['timestamp'] = r['timestamp'] + 0.000001
            try:
                client.table('open_trades').upsert(rows, on_conflict='timestamp').execute()
            except Exception as e2:
                log.error('save_open_trades: upsert retry failed: %s', e2)
                return False
        else:
            log.error('save_open_trades: upsert failed: %s', e)
            return False

    current_ts = [r['timestamp'] for r in rows]
    try:
        client.table('open_trades').delete().not_.in_('timestamp', current_ts).execute()
    except Exception as e:
        log.error('save_open_trades: delete stale failed: %s', e)
        return False

    return True


def load_open_trades():
    client = _get_client()
    if not client:
        log.error('load_open_trades: no Supabase client, active_trades stays empty')
        return []

    try:
        resp = client.table('open_trades').select('*').execute()
        rows = resp.data or []
    except Exception as e:
        log.error('load_open_trades: fetch failed: %s', e)
        return []

    if not rows:
        log.info('load_open_trades: no open trades to restore')
        return []

    timestamps = [row['timestamp'] for row in rows
                  if row.get('timestamp') is not None]

    closed_set = set()
    try:
        resp = (client.table('trades')
                .select('timestamp')
                .in_('timestamp', timestamps)
                .execute())
        closed_set = {r['timestamp'] for r in (resp.data or [])}
    except Exception as e:
        log.error('load_open_trades: batched cross-check failed, treating all as valid: %s', e)

    valid = []
    ghost_ts = []

    for row in rows:
        ts = row.get('timestamp')
        if ts is None:
            continue

        if ts in closed_set:
            log.warning('load_open_trades: dropping ghost ts=%s (already in trades)', ts)
            ghost_ts.append(ts)
            continue

        valid.append(row)

    if ghost_ts:
        try:
            client.table('open_trades').delete().in_('timestamp', ghost_ts).execute()
            log.info('load_open_trades: deleted %s ghost rows', len(ghost_ts))
        except Exception as e:
            log.error('load_open_trades: ghost delete failed: %s', e)

    log.info('load_open_trades: restored %s open trades', len(valid))
    return valid


def get_stats():
    trades = get_all_trades()
    if not trades:
        return None

    wins = [t for t in trades if t.get("result") == "WIN"]
    losses = [t for t in trades if t.get("result") == "LOSS"]
    resolved = len(wins) + len(losses)

    if resolved == 0:
        return {
            "total_trades": len(trades),
            "wins": 0,
            "losses": 0,
            "winrate": 0,
            "total_pnl": 0,
            "avg_pnl": 0,
            "best_trade": None,
            "worst_trade": None,
            "current_streak": {"type": "none", "count": 0},
        }

    total_pnl = sum(t.get("pnl", 0) for t in trades)
    winrate = round((len(wins) / resolved) * 100, 1)
    avg_pnl = round(total_pnl / resolved, 2)

    sorted_by_pnl = sorted(trades, key=lambda t: t.get("pnl", 0))
    best = sorted_by_pnl[-1]
    worst = sorted_by_pnl[0]

    # Current streak
    streak_type = None
    streak_count = 0
    for t in reversed(trades):
        r = t.get("result")
        if r not in ("WIN", "LOSS"):
            continue
        if streak_type is None:
            streak_type = r
            streak_count = 1
        elif r == streak_type:
            streak_count += 1
        else:
            break

    return {
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "winrate": winrate,
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": avg_pnl,
        "best_trade": {
            "direction": best.get("direction"),
            "entry": best.get("entry"),
            "pnl": best.get("pnl"),
            "score": best.get("score"),
        },
        "worst_trade": {
            "direction": worst.get("direction"),
            "entry": worst.get("entry"),
            "pnl": worst.get("pnl"),
            "score": worst.get("score"),
        },
        "current_streak": {
            "type": streak_type or "none",
            "count": streak_count,
        },
    }
