"""Score confirmed claims against human labels.

python -m eval.evaluate --gold eval/gold.fixtures.json --claims outputs/latest/claims.json
python -m eval.evaluate --gold eval/gold.real.json --claims outputs/real/claims.json

Gold format: {"labels": {posting_id: {level: [skill, ...]}}} where level is one of
required, preferred, responsibility, mention. Keys starting with "_" are notes and are ignored.
One (posting, skill) pair has exactly one level in the gold: the strongest that applies.

skill:              (posting, skill) found at all, whatever the level
labeled:            (posting, skill, level) found with the right level
required_preferred: the same, restricted to required/preferred on either side (the headline numbers)
"""
import argparse
import json
from pathlib import Path

LEVELS = ('required', 'preferred', 'responsibility', 'mention')
RANK = {level: i for i, level in enumerate(LEVELS)}
# Claims use the pipeline's internal names; "unknown" (outside any known section) is a bare mention.
CLAIM_LEVEL = {'required': 'required', 'preferred': 'preferred', 'responsibility': 'responsibility', 'unknown': 'mention'}


def _prf(predicted, gold):
    tp = len(predicted & gold)
    precision = tp / len(predicted) if predicted else 0.0
    recall = tp / len(gold) if gold else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {'tp': tp, 'predicted': len(predicted), 'gold': len(gold),
            'precision': round(precision, 3), 'recall': round(recall, 3), 'f1': round(f1, 3)}


def gold_tuples(gold_labels):
    out = set()
    for pid, by in gold_labels.items():
        for level, names in by.items():
            if level.startswith('_'):
                continue
            if level not in RANK:
                raise ValueError(f'{pid}: unknown level {level!r}; use one of {LEVELS}')
            out.update((pid, skill, level) for skill in names)
    return out


def predicted_tuples(claims, gold_labels):
    """One level per (posting, skill): the strongest sentence wins, as in analyze.demand."""
    best = {}
    for c in claims:
        if c['status'] != 'confirmed' or c['posting_id'] not in gold_labels:
            continue
        key, level = (c['posting_id'], c['canonical']), CLAIM_LEVEL[c['requirement']]
        if key not in best or RANK[level] < RANK[best[key]]:
            best[key] = level
    return {(pid, skill, level) for (pid, skill), level in best.items()}


def score(gold_labels, claims):
    gold, labeled = gold_tuples(gold_labels), predicted_tuples(claims, gold_labels)
    strong = {'required', 'preferred'}
    result = {'skill': _prf({(p, s) for p, s, _ in labeled}, {(p, s) for p, s, _ in gold}),
              'labeled': _prf(labeled, gold),
              'required_preferred': _prf({t for t in labeled if t[2] in strong}, {t for t in gold if t[2] in strong}),
              'postings': len(gold_labels),
              'status': {k: sum(c['status'] == k for c in claims) for k in ('confirmed', 'uncertain', 'rejected')}}
    result['missed'] = sorted(gold - labeled)
    result['extra'] = sorted(labeled - gold)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--gold', default='eval/gold.fixtures.json')
    parser.add_argument('--claims', default='outputs/latest/claims.json')
    args = parser.parse_args()
    doc = json.loads(Path(args.gold).read_text(encoding='utf-8'))
    claims = json.loads(Path(args.claims).read_text(encoding='utf-8'))
    result = score(doc['labels'], claims)
    result['gold_status'] = doc.get('status', 'approved')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
