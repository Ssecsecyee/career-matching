"""Training visibility policy; never changes the provider recruitment status."""
import json
from datetime import date, datetime, time, timedelta, timezone

KST = timezone(timedelta(hours=9))


def effective_start(row):
    """Naive DB timestamps are UTC; date-only starts expire at KST midnight."""
    value = row.get('starts_at')
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    if isinstance(value, date):
        return datetime.combine(value, time.min, KST)
    extra = row.get('additional_sections') or {}
    if isinstance(extra, (str, bytes)):
        extra = json.loads(extra)
    raw = (extra.get('date_precision') or {}).get('starts_at', {}).get('raw')
    if raw:
        try:
            return datetime.combine(date.fromisoformat(raw), time.min, KST)
        except (TypeError, ValueError):
            pass
    return None


def start_visibility(row, *, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('Training policy requires timezone-aware now')
    start = effective_start(row)
    if start is None:
        return False, 'start_unknown'
    return (True, 'before_start') if start > now else (False, 'training_started')
