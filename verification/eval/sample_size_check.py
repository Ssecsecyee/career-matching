"""Was 20 test postings enough? Re-check the 2026-11-13 decision on the sealed B·C results.

    python -m eval.sample_size_check          # numbers only, no model calls

docs/eval/verification.md §2 chose 20 postings from practice data (F1 within ±0.10 at 95%) and
promised to measure again on the test data. Three checks, all resampling whole postings:
  1. width of one variant's 95% interval at 20 postings (plan: ±0.10)
  2. design effect: that width vs the textbook width that treats every (posting, skill) pair as independent
  3. pairing: interval of C − B when B and C share the draw vs when they are drawn apart,
     and the smallest per-posting difference 20 postings detect at 95% / 80% power
"""
import argparse
import json
import math
import random
import statistics
from pathlib import Path

from eval.bc_run import RUNS, jobs_of, teammate
from eval.bc_score import f1, gold_by_condition, predictions, score_posting, summary
from eval.condition_gold import GOLD, SNAPSHOT, is_sealed

Z95, Z80 = 1.96, 0.84          # two-sided 5% false alarm, 80% power
ROUNDS, SEED = 4000, 20261118


def interval(values):
    values = sorted(values)
    return values[int(0.025 * len(values))], values[int(0.975 * len(values)) - 1]


def textbook_halfwidth(p, pairs, z=Z95):
    """95% half-width of a proportion if every pair were independent."""
    return z * math.sqrt(p * (1 - p) / pairs)


def detectable(sd, n, z=Z95, power_z=Z80):
    """Smallest mean per-posting difference a paired test on n postings finds 80% of the time."""
    return (z + power_z) * sd / math.sqrt(n)


def resample(per_b, per_c, metric, rounds=ROUNDS, seed=SEED):
    rng = random.Random(seed)
    idx = range(len(per_b))
    one, paired, apart = {'B': [], 'C': []}, [], []
    for _ in range(rounds):
        d1, d2 = [rng.choice(idx) for _ in idx], [rng.choice(idx) for _ in idx]
        b = summary([per_b[i] for i in d1])[metric]
        c = summary([per_c[i] for i in d1])[metric]
        c_apart = summary([per_c[i] for i in d2])[metric]
        one['B'].append(b), one['C'].append(c), paired.append(c - b), apart.append(c_apart - b)
    half = {v: (interval(x)[1] - interval(x)[0]) / 2 for v, x in one.items()}
    return {'halfwidth': {v: round(h, 3) for v, h in half.items()},
            'paired': [round(x, 3) for x in interval(paired)], 'apart': [round(x, 3) for x in interval(apart)]}


def check(gold, runs_dir=RUNS, snapshot_path=SNAPSHOT, mods=None):
    if not is_sealed(gold):
        raise SystemExit('정답이 봉인되지 않았습니다.')
    mods = mods or teammate()
    jobs = jobs_of(gold, snapshot_path)
    gold_c = gold_by_condition(gold, jobs, mods)
    out = {'postings': len(jobs)}
    for view in ('service', 'model'):
        per = {}
        for v in ('B', 'C'):
            recs = {j: json.loads((Path(runs_dir) / v / f'{j}.json').read_text(encoding='utf-8')) for j in jobs}
            per[v] = [score_posting(gold_c[j], predictions(recs[j], view)) for j in jobs]
        pairs = sum(p['gold_terms'] for p in per['B'])
        res = {m: resample(per['B'], per['C'], m) for m in ('macro_f1', 'micro_f1')}
        micro_b = summary(per['B'])['micro_f1']
        book = textbook_halfwidth(micro_b, pairs)
        res['design_effect'] = {'gold_pairs': pairs, 'textbook': round(book, 3),
                                'by_posting': res['micro_f1']['halfwidth']['B'],
                                'ratio': round((res['micro_f1']['halfwidth']['B'] / book) ** 2, 1)}
        diffs = [f1(c) - f1(b) for b, c in zip(per['B'], per['C']) if f1(b) is not None and f1(c) is not None]
        sd = statistics.stdev(diffs)
        res['per_posting'] = {'mean_diff': round(statistics.mean(diffs), 3), 'sd': round(sd, 3), 'n': len(diffs),
                              'detectable_80': round(detectable(sd, len(diffs)), 3),
                              'c_better_same_worse': [sum(d > 0 for d in diffs), sum(d == 0 for d in diffs),
                                                      sum(d < 0 for d in diffs)]}
        out[view] = res
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.parse_args(argv)
    print(json.dumps(check(json.loads(GOLD.read_text(encoding='utf-8'))), ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
