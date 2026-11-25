"""Weekday afternoon reminder: "N kept decisions are waiting. Type /review."  Cheap: no network."""
import time
from datetime import datetime

from . import state
from .capture import queue
from .config import Settings

THROTTLE_SECONDS = 3600


def waiting() -> int:
    return queue.count() + int(state.get("draft_count", 0) or 0)


def in_window(now: datetime, s: Settings) -> bool:
    return now.weekday() < 5 and s.reminder_start_hour <= now.hour < s.reminder_end_hour


def due(now: datetime, s: Settings, clock=time.time) -> bool:
    return in_window(now, s) and waiting() > 0 and clock() - float(state.get("last_reminder", 0) or 0) >= THROTTLE_SECONDS


def message(now: datetime, s: Settings, clock=time.time):
    """The reminder text if one is due (and marks it as shown), else None."""
    if not due(now, s, clock):
        return None
    state.set_(last_reminder=clock())
    n = waiting()
    return f"Superchat: {n} kept decision{'s' if n != 1 else ''} waiting for review. Mention this once and suggest /review."
