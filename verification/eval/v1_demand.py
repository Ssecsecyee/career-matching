"""V1+ — do duplicate postings change the skill-demand picture?

    python -m eval.v1_demand

Counts each skill two ways on the same snapshot of the teammate's job DB:
  rows    every DB row counts (what a plain COUNT gives today)
  groups  postings that eval.v1_reposts groups as the same opening count once
and compares shares and ranks. Fixed before looking at any result (rule-log 2026-11-18):
  - a skill = a Jumpit `tech_stacks` tag, compared case-insensitively after trimming — no extraction model,
    so extraction errors do not enter this comparison;
  - a group has a skill if any of its rows lists it;
  - main scenario merges `repost` pairs only; merging every variant kind as well is reported as a second scenario.
The snapshot is one site at one date: shares here are not the Korean job market's.
"""
import argparse
import collections
import json
from pathlib import Path

from eval.v1_reposts import SNAPSHOT, find_pairs, groups_of
from skillpath.sources.jumpit import to_posting

VARIANTS = {'career_variant', 'location_variant', 'other_variant'}
SCENARIOS = {'repost': {'repost'}, 'repost_and_variants': {'repost'} | VARIANTS}


def skills_of(row):
    out = {}
    for s in row.get('tech_stacks') or []:
        if s and s.strip():
            out.setdefault(s.strip().casefold(), s.strip())      # first spelling is the display name
    return out


def count(units):
    """units: list of {key: display name} — one per counted posting or group."""
    n, names = collections.Counter(), {}
    for unit in units:
        n.update(unit.keys())
        for key, name in unit.items():
            names.setdefault(key, name)
    return n, names


def compare(rows, groups, top=10):
    """rows: {posting id: snapshot row}. groups: lists of posting ids counted as one opening."""
    grouped = {x for g in groups for x in g}
    by_row = [skills_of(r) for r in rows.values()]
    merged = []
    for g in groups:
        unit = {}
        for x in g:
            unit.update(skills_of(rows[x]))
        merged.append(unit)
    by_group = merged + [skills_of(r) for i, r in rows.items() if i not in grouped]
    a, names = count(by_row)
    b, more = count(by_group)
    names.update({k: v for k, v in more.items() if k not in names})

    def ranked(c):
        order = sorted(c, key=lambda k: (-c[k], k))
        return {k: i for i, k in enumerate(order, 1)}, order
    ra, order_a = ranked(a)
    rb, order_b = ranked(b)
    share = lambda c, k, n: c[k] / n if n else 0.0
    table = [{'skill': names[k], 'rows': a[k], 'groups': b[k],
              'share_rows': round(share(a, k, len(by_row)), 4), 'share_groups': round(share(b, k, len(by_group)), 4),
              'share_diff': round(share(b, k, len(by_group)) - share(a, k, len(by_row)), 4),
              'rank_rows': ra[k], 'rank_groups': rb.get(k)} for k in order_a]
    head = table[:top]
    return {'units': {'rows': len(by_row), 'groups': len(by_group), 'removed': len(by_row) - len(by_group)},
            'skills': len(a),
            'top_rows': [names[k] for k in order_a[:top]], 'top_groups': [names[k] for k in order_b[:top]],
            'top_same_set': set(order_a[:top]) == set(order_b[:top]),
            'top_rank_changes': sum(1 for r in head if r['rank_rows'] != r['rank_groups']),
            'largest_share_changes': sorted(table, key=lambda r: -abs(r['share_diff']))[:top],
            'max_abs_share_diff': max((abs(r['share_diff']) for r in table), default=0.0),
            'top': head}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--snapshot', default=SNAPSHOT)
    ap.add_argument('--top', type=int, default=10)
    args = ap.parse_args(argv)
    doc = json.loads(Path(args.snapshot).read_text(encoding='utf-8'))
    rows = {f"jumpit-{r['source_id']}": r for r in doc['postings']}
    pairs = find_pairs([to_posting(r) for r in doc['postings']])
    report = {'snapshot_at': doc['snapshot_at'],
              **{name: compare(rows, groups_of(pairs, kinds), args.top) for name, kinds in SCENARIOS.items()}}
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
