"""Job visibility policy; date-only expiry is a policy, not a source timestamp."""
from datetime import datetime, time, timedelta, timezone
import json

KST = timezone(timedelta(hours=9))
RAW_DATE_SQL = "JSON_UNQUOTE(JSON_EXTRACT(additional_sections,'$.page_extraction.deadline.raw'))"
PRECISION_SQL = "JSON_UNQUOTE(JSON_EXTRACT(additional_sections,'$.page_extraction.deadline.precision'))"
# ISO date-only values are normalized by ingestion. Unknown/malformed values do
# not establish a confirmed deadline. Exact timestamps use UTC storage convention.
VISIBLE_SQL = ("(deadline_type='always_open' OR ((deadline_at IS NULL OR deadline_at>UTC_TIMESTAMP(6)) AND NOT ("
               "COALESCE(" + PRECISION_SQL + ", '')='date_only' AND COALESCE(" + RAW_DATE_SQL + ", '') REGEXP "
               "'^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$' AND " + RAW_DATE_SQL +
               "<CAST(DATE(UTC_TIMESTAMP()+INTERVAL 9 HOUR) AS CHAR))))")


def effective_deadline(row):
    if row.get('deadline_type') == 'always_open':
        return None
    value = row.get('deadline_at')
    if value:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    extra = row.get('additional_sections') or {}
    if isinstance(extra, (str, bytes)):
        extra = json.loads(extra)
    deadline = extra.get('page_extraction', {}).get('deadline', {})
    if deadline.get('precision') == 'date_only':
        try:
            date = datetime.strptime(deadline['raw'], '%Y-%m-%d').date()
            return datetime.combine(date + timedelta(days=1), time(), KST).astimezone(timezone.utc)
        except (KeyError, TypeError, ValueError):
            pass
    return None


def expired(row, now=None):
    deadline = effective_deadline(row)
    return bool(deadline and deadline <= (now or datetime.now(timezone.utc)))
