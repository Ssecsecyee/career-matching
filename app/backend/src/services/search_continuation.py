"""Bounded continuation intent and server-owned exposure tracking."""


def exclusion_ids(values):
    if not isinstance(values, (list, tuple)) or len(values) > 1000:
        raise ValueError('invalid_search_exclusions')
    if any(not isinstance(v, str) or not v.isdigit() or len(v) > 128 for v in values):
        raise ValueError('invalid_search_exclusions')
    return list(dict.fromkeys(values))


def mark_shown(state):
    page = state.get('search_navigation')
    if page is not None:
        page['shown_ids'] = list(dict.fromkeys(page['shown_ids'] + state.get('candidate_ids', [])))

# Compatibility imports; free-text v2 routing does not use these classifiers.
from src.services.legacy_intent import is_more_request
