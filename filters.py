from datetime import datetime
from config import COOLDOWN_MINUTES

last_signal_time = None


def weekend_filter():
    day = datetime.utcnow().weekday()
    return day < 5


def session_filter():
    hour = datetime.utcnow().hour
    return 7 <= hour <= 22


def cooldown_filter():
    global last_signal_time

    if last_signal_time is None:
        return True

    diff = datetime.utcnow() - last_signal_time
    return diff.total_seconds() > COOLDOWN_MINUTES * 60


def update_signal_time():
    global last_signal_time
    last_signal_time = datetime.utcnow()