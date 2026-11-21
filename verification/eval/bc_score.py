"""Score the B and C runs against the sealed V3·V4 answer key.

    python -m eval.bc_score            # numbers only — no posting text, no model quote

Per condition (matched by the teammate's own condition id):
  category   person's category vs model's category                                  (V3)
  terms      skill names the service would search with: terms of conditions the model
             calls skill and does not treat as reference — vs every skill name the person
             wrote, as (required/preferred, name) pairs; F1 per posting, macro = mean   (V3, headline)
  relation   for conditions where the person wrote 2+ names and knew the relation:
             correct / wrong / abstain (model said unresolved) / missing                (V4)
Two views of the model output:
  service    as the teammate's pipeline publishes it: a posting whose output fails the
             teammate's validate_review gets nothing (headline, fixed before any result)
  model      every condition the model returned, valid or not
The C − B difference comes with a 95% interval from a paired bootstrap over postings.
"""
import argparse
import json
import random
import re
from pathlib import Path

from eval.bc_run import RUNS, jobs_of, teammate
from eval.condition_gold import GOLD, SNAPSHOT, is_sealed, parse_terms, relation

BOOTSTRAP = 4000
SEED = 20261116


def norm(term):
    return re.sub(r'\s+', ' ', term).strip().casefold()


def shape(logic):
    """The model's AND/OR for one condition: atom, all, any, mixed or unresolved."""
    if logic['operator'] in ('atom', 'unresolved'):
        return logic['operator']
    ops = set()

    def walk(node):
        if node['operator'] in ('all', 'any'):
            ops.add(node['operator'])
        for child in node.get('children') or []:
            walk(child)
    walk(logic)
    return ops.pop() if len(ops) == 1 else 'mixed'


def gold_by_condition(gold, jobs, mods):
    """{job_id: {condition_id: (type, label)}} with the teammate's own condition ids."""
    out = {}
    for job_id, job in jobs.items():
        keyed = {c['key']: c for c in mods['review'].source_conditions(job)}
        out[job_id] = {mods['review'].review_key(keyed[c['key']]): (c['type'], gold['labels'][c['key']])
                       for c in gold['jobs'][job_id]['conditions']}
    return out


def predictions(record, view):
    if not record:
        return {}
    if view == 'service' and not record.get('validation', {}).get('ok'):
        return {}
    return {c['condition_id']: c for b in record['batches'].values() if b['status'] == 'ok' for c in b['conditions']}


def score_posting(gold_conds, preds):
    cat_right = sum(1 for cid, (_, lab) in gold_conds.items() if preds.get(cid, {}).get('category') == lab['category'])
    gold_terms = {(kind, norm(t)) for kind, lab in gold_conds.values() for g in parse_terms(lab['terms']) for t in g}
    pred_terms = set()
    for cid, c in preds.items():
        if cid in gold_conds and c['category'] == 'skill' and c['treatment'] != 'reference':
            kind = gold_conds[cid][0]
            pred_terms |= {(kind, norm(t)) for p in c['parts'] for t in p['terms']}
    hit = len(gold_terms & pred_terms)
    rel = {'correct': 0, 'wrong': 0, 'abstain': 0, 'missing': 0, 'person_unknown': 0}
    for cid, (_, lab) in gold_conds.items():
        r = relation(lab)
        if r == 'unknown':
            rel['person_unknown'] += 1
        if r not in ('all', 'any', 'mixed'):
            continue
        if cid not in preds:
            rel['missing'] += 1
        else:
            s = shape(preds[cid]['logic'])
            rel['abstain' if s == 'unresolved' else 'correct' if s == r else 'wrong'] += 1
    return {'conditions': len(gold_conds), 'category_right': cat_right, 'gold_terms': len(gold_terms),
            'pred_terms': len(pred_terms), 'term_hits': hit, 'relation': rel}


def f1(p):
    if not p['gold_terms'] and not p['pred_terms']:
        return None                                   # nothing to find and nothing found: left out of the mean
    prec = p['term_hits'] / p['pred_terms'] if p['pred_terms'] else 0.0
    rec = p['term_hits'] / p['gold_terms'] if p['gold_terms'] else 0.0
    return 2 * prec * rec / (prec + rec) if prec + rec else 0.0


def summary(per):
    scores = [s for s in (f1(p) for p in per) if s is not None]
    hits, pred, gold = (sum(p[k] for p in per) for k in ('term_hits', 'pred_terms', 'gold_terms'))
    micro_p, micro_r = (hits / pred if pred else 0.0), (hits / gold if gold else 0.0)
    rel = {k: sum(p['relation'][k] for p in per) for k in ('correct', 'wrong', 'abstain', 'missing', 'person_unknown')}
    decided = rel['correct'] + rel['wrong']
    return {'postings': len(per), 'macro_f1': round(sum(scores) / len(scores), 3) if scores else None,
            'micro_f1': round(2 * micro_p * micro_r / (micro_p + micro_r), 3) if micro_p + micro_r else 0.0,
            'micro_precision': round(micro_p, 3), 'micro_recall': round(micro_r, 3),
            'category_accuracy': round(sum(p['category_right'] for p in per) / sum(p['conditions'] for p in per), 3),
            'relation': rel, 'relation_accuracy_when_decided': round(rel['correct'] / decided, 3) if decided else None}


def paired_interval(per_b, per_c, metric, n=BOOTSTRAP, seed=SEED):
    """95% interval of C − B, resampling postings (both variants on the same draw)."""
    rng = random.Random(seed)
    idx = range(len(per_b))
    diffs = []
    for _ in range(n):
        draw = [rng.choice(idx) for _ in idx]
        b, c = summary([per_b[i] for i in draw])[metric], summary([per_c[i] for i in draw])[metric]
        if b is not None and c is not None:
            diffs.append(c - b)
    diffs.sort()
    return round(diffs[int(0.025 * len(diffs))], 3), round(diffs[int(0.975 * len(diffs)) - 1], 3)


def score(gold, runs_dir=RUNS, snapshot_path=SNAPSHOT, allow_unsealed=False, mods=None):
    if not allow_unsealed and not is_sealed(gold):
        raise SystemExit('정답이 봉인되지 않았습니다. 봉인한 정답으로만 채점합니다.')
    mods = mods or teammate()
    jobs = jobs_of(gold, snapshot_path)
    gold_c = gold_by_condition(gold, jobs, mods)
    report = {'validation_failed': {}}
    per = {}
    for variant in ('B', 'C'):
        records = {}
        for job_id in jobs:
            path = Path(runs_dir) / variant / f'{job_id}.json'
            records[job_id] = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
        report['validation_failed'][variant] = sum(1 for r in records.values() if r and not r.get('validation', {}).get('ok'))
        report.setdefault('missing_runs', {})[variant] = sum(1 for r in records.values() if r is None)
        for view in ('service', 'model'):
            per[(variant, view)] = [score_posting(gold_c[j], predictions(records[j], view)) for j in jobs]
            report.setdefault(view, {})[variant] = summary(per[(variant, view)])
    for view in ('service', 'model'):
        report[view]['C_minus_B'] = {
            m: {'diff': round(report[view]['C'][m] - report[view]['B'][m], 3)
                if report[view]['C'][m] is not None and report[view]['B'][m] is not None else None,
                'ci95': paired_interval(per[('B', view)], per[('C', view)], m)}
            for m in ('macro_f1', 'micro_f1', 'category_accuracy')}
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.parse_args(argv)
    report = score(json.loads(GOLD.read_text(encoding='utf-8')))
    (RUNS / 'score.json').write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
