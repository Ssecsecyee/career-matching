"""Read-only KST projections; storage, predicates and ordering stay UTC."""
UTC_COLUMNS=frozenset('created_at updated_at started_at finished_at expires_at fetched_at last_seen_at deadline_at starts_at ends_at application_deadline invalidated_at processed_at'.split())

def kst_projection(column, prefix=''):
    reference=prefix+column
    return f'DATE_ADD({reference}, INTERVAL 9 HOUR) AS {column}' if column in UTC_COLUMNS else reference
