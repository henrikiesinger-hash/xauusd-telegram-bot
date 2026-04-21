import logging
import time
import requests
from datetime import datetime

log = logging.getLogger('news_filter')

# ==============================
# CACHE
# ==============================

_events_cache = []
_cache_date = None

BLACKOUT_MINUTES = 3
NEWS_API_URL = 'https://nfs.faireconomy.media/ff_calendar_thisweek.json'

# USD-relevant keywords for XAU/USD
RELEVANT_CURRENCIES = {'USD'}
RELEVANT_KEYWORDS = {
    'nonfarm', 'non-farm', 'nfp', 'fomc', 'fed', 'cpi', 'ppi',
    'gdp', 'retail sales', 'unemployment', 'interest rate',
    'powell', 'inflation', 'payroll', 'jobless', 'ism',
    'consumer confidence', 'durable goods', 'housing',
    'trade balance', 'pce',
}


# ==============================
# FETCH EVENTS
# ==============================

def fetch_todays_events():
    global _events_cache, _cache_date

    today = time.strftime('%Y-%m-%d', time.gmtime())

    if _cache_date == today and _events_cache:
        return _events_cache

    try:
        resp = requests.get(NEWS_API_URL, timeout=10)

        if resp.status_code != 200:
            log.error('News API returned %s', resp.status_code)
            return _events_cache

        data = resp.json()
        events = []

        for item in data:
            impact = item.get('impact', '').lower()
            if impact != 'high':
                continue

            country = item.get('country', '').upper()
            if country not in RELEVANT_CURRENCIES:
                continue

            event_date = item.get('date', '')
            if not event_date.startswith(today):
                continue

            title = item.get('title', '')
            event_time = item.get('date', '')

            # Parse time from ISO format
            ts = _parse_event_time(event_time)
            if ts is None:
                continue

            events.append({
                'title': title,
                'time_utc': event_time,
                'timestamp': ts,
                'impact': 'HIGH',
                'country': country,
            })

        events.sort(key=lambda e: e['timestamp'])
        _events_cache = events
        _cache_date = today

        log.info('News loaded: %s high-impact events today', len(events))
        return events

    except Exception as e:
        log.error('News fetch failed: %s', e)
        return _events_cache


def _parse_event_time(time_str):
    # Format: '2026-04-15T13:30:00-04:00' (ForexFactory, Eastern Time, DST-aware)
    if not time_str:
        return None
    try:
        dt = datetime.fromisoformat(time_str)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        return None
    return dt.timestamp()


# ==============================
# BLACKOUT CHECK
# ==============================

def is_news_blackout():
    events = fetch_todays_events()

    if not events:
        return False, None

    now = time.time()
    window = BLACKOUT_MINUTES * 60

    for event in events:
        diff = event['timestamp'] - now

        if -window <= diff <= window:
            minutes_away = round(diff / 60, 1)
            return True, {
                'title': event['title'],
                'time_utc': event['time_utc'],
                'minutes_away': minutes_away,
            }

    return False, None


# ==============================
# UPCOMING EVENTS
# ==============================

def get_upcoming_events(limit=5):
    events = fetch_todays_events()

    if not events:
        return []

    now = time.time()
    upcoming = [e for e in events if e['timestamp'] > now]

    return upcoming[:limit]


def get_next_event():
    upcoming = get_upcoming_events(1)
    return upcoming[0] if upcoming else None
