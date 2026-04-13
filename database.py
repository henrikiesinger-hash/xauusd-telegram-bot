import logging
import time
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
        return False

    try:
        client.table("trades").insert(trade_data).execute()
        log.info("Supabase saved: %s %s | %s",
                 trade_data.get("direction"), trade_data.get("entry"),
                 trade_data.get("result"))
        return True
    except Exception as e:
        log.error("Supabase save failed: %s", e)
        return False


def get_all_trades():
    client = _get_client()
    if not client:
        return None

    try:
        resp = client.table("trades").select("*").order("timestamp").execute()
        return resp.data
    except Exception as e:
        log.error("Supabase get_all_trades failed: %s", e)
        return None


def get_recent_trades(n=20):
    client = _get_client()
    if not client:
        return None

    try:
        resp = (client.table("trades")
                .select("*")
                .order("timestamp", desc=True)
                .limit(n)
                .execute())
        return resp.data
    except Exception as e:
        log.error("Supabase get_recent_trades failed: %s", e)
        return None


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
