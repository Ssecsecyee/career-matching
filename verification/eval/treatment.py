"""V3-T — does adding the category rules change which conditions the user is asked about?

    python -m eval.treatment shift                  # service-mode test runs, B vs the patch — no model call
    python -m eval.treatment shift --mode bounded   # B vs C2;  --set fresh for the unseen postings
    python -m eval.treatment shift --set fresh      # unseen postings, service mode: B vs the handed-over patch C2G
    python -m eval.treatment queue                  # blind sheet of the lines where the two sides (or runs) differ
    python -m eval.treatment score                  # after a person labelled the sheet

The live step labels each condition ask / review / reference. The teammate's question_selection keeps every
condition that is not `reference` as a question, so "asked" here means treatment != reference. Everything is
read from the answers already saved by eval.live_run; nothing is sent to a model.
The sheet shows the condition text only — not which side said what — and is written under data/real
(posting text, not in git). Labels hold condition ids and calls only.
"""
import argparse
import collections
import json
import random
from pathlib import Path

from eval.bc_run import jobs_of, teammate
from eval.condition_gold import GOLD, SNAPSHOT
from eval.live_run import fresh_jobs, predictions, repeats_of, runs_dir

ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / 'data' / 'real' / 'jumpit' / 'treatment_review_queue.json'
LABELS = ROOT / 'eval' / 'treatment_labels.json'
SEED = 20261118
PAIRS = {'adaptive': ('B', 'C2S'), 'bounded': ('B', 'C2')}
CALLS = ('ask', 'reference', 'unsure')          # a person's call: should be a question / reference only / cannot tell


def asked(treatment):
    return treatment is not None and treatment != 'reference'


def conditions_of(jobs):
    """{job_id: {condition_id: {'type', 'quote'}}} in the teammate's own split and ids."""
    review = teammate()['review']
    return {job_id: {review.review_key(c): {'type': c['type'], 'quote': c['quote']} for c in review.source_conditions(job)}
            for job_id, job in jobs.items()}


def guard(label, requirement_type):
    """The code guard in the handed-over patch (C2G): a required line the model calls "not a requirement"
    stays a question (review). Pure post-processing of one label, so it can be replayed on saved answers."""
    if (requirement_type == 'required' and label.get('treatment') == 'reference'
            and label.get('reason_code') == 'not_eligibility'):
        return dict(label, treatment='review', reason_code='ambiguous')
    return label


def table(variant, out_dir, conditions, guarded=False):
    """{(job_id, condition_id): [treatment in each run]} — None where the run has no label for it.
    guarded=True replays the C2G guard on the saved answers (no model call)."""
    repeats = repeats_of(out_dir, variant)
    preds = {k: {j: predictions(Path(out_dir) / variant / f'r{k}' / f'{j}.json') for j in conditions} for k in repeats}

    def one(k, j, c):
        label = preds[k][j].get(c)
        if label is None:
            return None
        return (guard(label, conditions[j][c]['type']) if guarded else label).get('treatment')
    return {(j, c): [one(k, j, c) for k in repeats] for j in conditions for c in conditions[j]}


def mostly_not_asked(runs):
    labelled = [t for t in runs if t is not None]
    return bool(labelled) and sum(not asked(t) for t in labelled) * 2 > len(labelled)


def shift(a, b, out_dir, conditions, guarded=False):
    ta, tb = table(a, out_dir, conditions), table(b, out_dir, conditions, guarded)
    keys = list(ta)

    def within(t):
        pairs = [(r[i], r[j]) for r in t.values() for i in range(len(r)) for j in range(i + 1, len(r))
                 if r[i] is not None and r[j] is not None]
        return round(sum(x == y for x, y in pairs) / len(pairs), 3) if pairs else None

    every = [(x, y) for k in keys for x, y in zip(ta[k], tb[k])]
    between = [(x, y) for x, y in every if x is not None and y is not None]      # a run with no label is not a disagreement
    moves = collections.Counter((x or '없음', y or '없음') for x, y in every if x != y)
    off_a = {k for k in keys if mostly_not_asked(ta[k])}
    off_b = {k for k in keys if mostly_not_asked(tb[k])}

    def brief(k):
        return {'job_id': k[0], 'condition_id': k[1], 'type': conditions[k[0]][k[1]]['type']}
    return {'conditions': len(keys), 'runs': {a: len(next(iter(ta.values()), [])), b: len(next(iter(tb.values()), []))},
            'distribution': {v: dict(collections.Counter(x or '없음' for r in t.values() for x in r)) for v, t in ((a, ta), (b, tb))},
            'same_between': round(sum(x == y for x, y in between) / len(between), 3) if between else None,
            'same_run_to_run': {a: within(ta), b: within(tb)},
            'moves': {f'{x}→{y}': n for (x, y), n in moves.most_common()},
            'mostly_not_asked': {a: len(off_a), b: len(off_b), 'both': len(off_a & off_b)},
            'newly_not_asked': [brief(k) for k in sorted(off_b - off_a)],
            'newly_asked': [brief(k) for k in sorted(off_a - off_b)]}


def discordant(a, b, out_dir, conditions):
    """Conditions whose asked/not-asked answer differs between the two sides or between runs of one side."""
    ta, tb = table(a, out_dir, conditions), table(b, out_dir, conditions)
    return [k for k in ta if len({asked(t) for t in ta[k] + tb[k] if t is not None}) > 1]


def queue(a, b, out_dir, conditions, path=QUEUE, seed=SEED):
    """Blind sheet: condition text only, shuffled. A drawn sheet is never overwritten."""
    path = Path(path)
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    keys = discordant(a, b, out_dir, conditions)
    random.Random(seed).shuffle(keys)
    sheet = {'drawn_from': {'a': a, 'b': b, 'runs': str(out_dir)}, 'seed': seed,
             'items': [{'n': i, 'job_id': j, 'condition_id': c, **conditions[j][c]} for i, (j, c) in enumerate(keys, 1)]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sheet, ensure_ascii=False, indent=1), encoding='utf-8')
    return sheet


def score(labels, a, b, out_dir, conditions, guarded=False):
    """On the lines a person called: how often each side's asked/not-asked decision matches the call."""
    ta, tb = table(a, out_dir, conditions), table(b, out_dir, conditions, guarded)
    kinds = {c: conditions[j][c]['type'] for j in conditions for c in conditions[j]}
    called = {k: labels[k[1]] for k in ta if labels.get(k[1]) in ('ask', 'reference')}
    out = {'labelled': len(labels), 'decided': len(called),
           'unsure': sum(1 for v in labels.values() if v == 'unsure')}
    per = {}
    for v, t in ((a, ta), (b, tb)):
        right = total = missed = extra = 0
        missed_required = set()
        for k, call in called.items():
            for x in t[k]:
                if x is None:
                    continue
                total += 1
                right += asked(x) == (call == 'ask')
                if call == 'ask' and not asked(x):
                    missed += 1
                    if kinds[k[1]] == 'required':
                        missed_required.add(k[1])
                extra += call == 'reference' and asked(x)
        per[v] = {'decisions': total, 'match': round(right / total, 3) if total else None,
                  'should_ask_but_not_asked': missed, 'required_conditions_ever_dropped': len(missed_required),
                  'should_not_ask_but_asked': extra}
    out['by_variant'] = per
    better = worse = same = 0
    for k, call in called.items():
        fa = sum(asked(x) == (call == 'ask') for x in ta[k] if x is not None) / max(1, sum(x is not None for x in ta[k]))
        fb = sum(asked(x) == (call == 'ask') for x in tb[k] if x is not None) / max(1, sum(x is not None for x in tb[k]))
        better += fb > fa
        worse += fb < fa
        same += fb == fa
    out['per_condition'] = {f'{b} 가 나음': better, '같음': same, f'{a} 가 나음': worse}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('command', choices=('shift', 'queue', 'score'))
    ap.add_argument('--mode', choices=tuple(PAIRS), default='adaptive')
    ap.add_argument('--set', choices=('test', 'fresh'), default='test')
    ap.add_argument('--guard', action='store_true', help='replay the C2G guard on side b (saved answers, no call)')
    args = ap.parse_args(argv)
    gold = json.loads(GOLD.read_text(encoding='utf-8'))
    fresh = args.set == 'fresh'
    mode = args.mode
    # The unseen postings were run in service mode only with the handed-over patch (C2G, guard in the code).
    a, b = ('B', 'C2G') if fresh and mode == 'adaptive' else PAIRS[mode]
    conditions = conditions_of(fresh_jobs(gold) if fresh else jobs_of(gold, SNAPSHOT))
    out_dir = runs_dir(fresh, mode)
    if args.command == 'shift':
        report = shift(a, b, out_dir, conditions, args.guard)
    elif args.command == 'queue':
        sheet = queue(a, b, out_dir, conditions)
        report = {'sheet': str(QUEUE), 'items': len(sheet['items']), 'labels_go_to': str(LABELS)}
    else:
        if not LABELS.exists():
            raise SystemExit(f'판정 파일이 없습니다: {LABELS}')
        report = score(json.loads(LABELS.read_text(encoding='utf-8'))['labels'], a, b, out_dir, conditions, args.guard)
    print(json.dumps({'set': args.set, 'mode': mode, 'a': a, 'b': b + ('+guard' if args.guard else ''), **report},
                     ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
