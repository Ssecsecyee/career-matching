"""Session-scoped, source-backed memory. No inferred eligibility or cross-user cache."""
import hashlib
import re


def memory(state):
    profile = state.setdefault('profile', {})
    return profile.setdefault('memory', {'version': 1, 'statements': [], 'facts': [], 'confirmed': {}})


def record(state, text, kind='statement'):
    if not text or not text.strip():
        return
    value = memory(state)
    seq = value.get('sequence', 0) + 1
    value['sequence'] = seq
    value['statements'] = (value['statements'] + [{'id': str(seq), 'kind': kind, 'text': text[:4000]}])[-20:]


def context(state):
    value = memory(state)
    # Keep original messages in chat_messages; only bounded relevant memory goes to the model.
    recent = []
    size = 0
    for item in reversed(value['statements']):
        if size + len(item['text']) > 6000:
            break
        recent.insert(0, item)
        size += len(item['text'])
        if len(recent) == 6:
            break
    return {'facts': value['facts'][-16:], 'recent_statements': recent,
            'condition_answers': [{'quote': c['quote'][:600], 'assessment': c['assessment'], 'detail': c['detail'][:300]}
                                  for c in state.get('checks', [])[-4:]]}


def apply_facts(state, facts):
    value = memory(state)
    latest = {(f['category'], f['subject'].casefold()): f for f in value['facts']}
    for fact in facts:
        latest[(fact['category'], fact['subject'].casefold())] = dict(fact, basis='user_statement')
    value['facts'] = list(latest.values())[-32:]


def condition_key(kind, quote):
    # Only exactly equal original criteria can reuse a user's explicit answer.
    return hashlib.sha256((kind + ':' + quote).encode()).hexdigest()


def split_conditions(text, kind, source_id, version):
    """Split source bullets conservatively; retain OR clauses and continuation lines intact."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    bullets = any(re.match(r'^(?:[-*•●▪·]|\d+[.)])\s*', line) for line in lines)
    groups = []
    for line in lines:
        marked = bool(re.match(r'^(?:[-*•●▪·]|\d+[.)])\s*', line))
        continuation = bool(re.match(r'^(?:또는|혹은|및 |그리고|AND\b|OR\b|\(|※)', line, re.I))
        if groups and (continuation or (bullets and not marked)):
            groups[-1] += '\n' + line
        else:
            groups.append(line)
    if len(groups) > 40:
        # Do not silently discard conditions or overrun a session's input budget.
        raise ValueError('Too many source conditions')
    section = 'qualifications' if kind == 'required' else 'preferred_requirements'
    return [{'id': f'{source_id}:{version}:{kind}:{index}', 'type': kind, 'quote': quote,
             'section': section, 'key': condition_key(kind, quote)} for index, quote in enumerate(groups)]


def public_memory(state):
    value = memory(state)
    return {'facts': value['facts'], 'statement_count': len(value['statements']),
            'scope': 'current_session', 'basis': 'user_statement'}
