"""V1 — duplicate postings in the teammate's job DB (docs/eval/v1-reposts.md).

    python -m eval.v1_reposts                 # report + pairs from the friend-DB snapshot
    python -m eval.v1_reposts --round 2       # also draw review round 2 (companies no earlier round showed)
    python -m eval.v1_reposts --score --round 2

The teammate's DB only blocks the same (source, source_id). A company that re-posts the same job
under a new Jumpit number, or posts one body under several titles on the same day, adds rows that
inflate counts and can show the same opening several times in search. This check finds them.

Kinds of pair (same company only):
  repost        same job title (one side may add a suffix) and requirement sentences overlap >= 0.6
                (the F-006/F-011 rule in skillpath/dedupe.py)
  career_variant  titles differ only by career words (신입/경력/주니어/시니어/n~m년 ...) and bodies overlap
  location_variant titles differ only by place words and bodies overlap
  other_variant   titles differ in other words but bodies overlap (often a different job)
Code proposes the kind; a person checks a sample without seeing the proposal (review queue).
"""
import argparse
import collections
import datetime as dt
import json
import random
import re
from pathlib import Path

from skillpath.dedupe import _normalise, company_key, requirement_sentences, same_title, title_key
from skillpath.sources.jumpit import to_posting

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / 'data' / 'real' / 'jumpit' / 'snapshot.json'
OUT = ROOT / 'data' / 'real' / 'jumpit'
OVERLAP = 0.6
SEED = 20261113
ROUND_SEEDS = {1: 20261113, 2: 20261114}
VARIANT_SAMPLE = 20


def round_paths(n):
    """Files of one review round. The queue and the code's pairs are frozen when the round is drawn;
    labels hold ids and calls only (no posting text)."""
    return {'queue': OUT / f'v1_review_queue_r{n}.json', 'pairs': OUT / f'v1_pairs_r{n}.json',
            'labels': ROOT / 'eval' / f'v1_review_labels_r{n}.json'}

# Level words: titles that differ only by these are the same opening at another level (career_variant).
# 2026-11-14: rank, grade, education and "미만" added after round 1 of the person's review (rule-log).
CAREER_WORDS = re.compile(
    r'신입|경력직?|주니어|시니어|인턴|무관|이상|이하|미만|초과|junior|senior|\bsr\b|\bjr\b|years?|'
    r'(?:사원|주임|대리|과장|차장|부장|선임|책임|수석)급?|팀장|[초중고특]급|'
    r'학사|석사|박사|초대졸|대졸|고졸|학력|'
    r'\d+\s*[~\-]\s*\d+\s*(?:년|y)?|\d+\s*(?:년|y)\s*[↑+]?|\d+\s*↑|↑', re.IGNORECASE)
PLACE_WORDS = re.compile(
    r'서울|부산|대구|대전|광주|울산|인천|세종|경기|판교|분당|수원|성남|구로|가산|강남|여의도|천안|창원|'
    r'본사|지사|지점|사업장|센터|r&d', re.IGNORECASE)


def _strip(pattern, posting):
    return title_key({'title': pattern.sub(' ', posting.get('title') or ''), 'company': posting.get('company')})


def classify_pair(a, b):
    """Kind of a same-company pair, or None when the bodies are not alike."""
    sa, sb = requirement_sentences(a), requirement_sentences(b)
    small = min(len(sa), len(sb)) < 3
    overlap = len(sa & sb) / len(sa | sb) if (sa | sb) else 1.0
    if small:
        # Too little text to compare: only an exactly equal title counts (dedupe.py fallback).
        return ('repost', overlap) if title_key(a) and title_key(a) == title_key(b) else (None, overlap)
    if overlap < OVERLAP:
        return None, overlap
    if title_key(a) and title_key(a) == title_key(b):
        return 'repost', overlap
    # Within one site a career word is a different opening ("백엔드 개발자" vs "백엔드 개발자 (신입)"),
    # so career bands are checked before the suffix allowance that dedupe.py keeps for cross-site copies.
    ca, cb = _strip(CAREER_WORDS, a), _strip(CAREER_WORDS, b)
    if ca and ca == cb:
        return 'career_variant', overlap
    if same_title(a, b):
        return 'repost', overlap
    pa, pb = _strip(PLACE_WORDS, a), _strip(PLACE_WORDS, b)
    if pa and pa == pb:
        return 'location_variant', overlap
    return 'other_variant', overlap


def visible(row, on):
    """Shown in the teammate's search on a date (approximation of their deadline policy)."""
    if row.get('recruitment_status') == 'closed':
        return False
    deadline = row.get('deadline_at')
    return deadline is None or dt.date.fromisoformat(deadline[:10]) >= on


def find_pairs(postings):
    by_company = collections.defaultdict(list)
    for p in postings:
        by_company[company_key(p['company'])].append(p)
    pairs = []
    for group in by_company.values():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                kind, overlap = classify_pair(group[i], group[j])
                if kind:
                    pairs.append({'kind': kind, 'a': group[i]['id'], 'b': group[j]['id'], 'overlap': round(overlap, 3)})
    return pairs


def groups_of(pairs, kinds):
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for p in pairs:
        if p['kind'] in kinds:
            parent[find(p['a'])] = find(p['b'])
    out = collections.defaultdict(list)
    for x in list(parent):
        out[find(x)].append(x)
    return sorted((sorted(g) for g in out.values() if len(g) > 1), key=lambda g: g[0])


def summarize(groups, rows, on):
    vis = [sum(visible(rows[x], on) for x in g) for g in groups]
    return {'groups': len(groups), 'extra_copies': sum(len(g) - 1 for g in groups),
            'share_of_rows': round(sum(len(g) - 1 for g in groups) / len(rows), 3),
            'groups_shown_together': sum(1 for v in vis if v >= 2),
            'copies_shown_together': sum(v - 1 for v in vis if v >= 2),
            'group_sizes': dict(sorted(collections.Counter(len(g) for g in groups).items()))}


def diff_lines(a, b, limit=8):
    sa, sb = requirement_sentences(a), requirement_sentences(b)
    text = lambda p: {_normalise(s): s for k in ('qualifications', 'preferred')
                      for s in (p['sections'].get(k) or '').splitlines() if s.strip()}
    ta, tb = text(a), text(b)
    return ([ta[k] for k in sa - sb if k in ta][:limit], [tb[k] for k in sb - sa if k in tb][:limit])


def review_queue(pairs, postings, exclude, seed=SEED, sample=VARIANT_SAMPLE, skip_companies=()):
    """Edited reposts: every pair. Variants: one group per company, seeded sample. No proposal shown.
    skip_companies keeps a later round on companies no earlier round showed (held-out check)."""
    by_id = {p['id']: p for p in postings}
    items = []
    for p in pairs:
        if p['kind'] == 'repost' and p['overlap'] < 1.0 and not ({p['a'], p['b']} & exclude):
            a, b = by_id[p['a']], by_id[p['b']]
            only_a, only_b = diff_lines(a, b)
            items.append({'item': f"pair:{p['a']}:{p['b']}", 'question': 'repost',
                          'company': a['company'], 'postings': [_brief(a), _brief(b)],
                          'only_in_first': only_a, 'only_in_second': only_b})
    variant_groups = groups_of(pairs, {'career_variant', 'location_variant', 'other_variant'})
    rng = random.Random(seed)
    rng.shuffle(variant_groups)
    seen_companies, picked = {company_key(c) for c in skip_companies}, 0
    for g in variant_groups:
        if set(g) & exclude:
            continue
        company = company_key(by_id[g[0]]['company'])
        if company in seen_companies:
            continue
        seen_companies.add(company)
        items.append({'item': 'group:' + ':'.join(g), 'question': 'variant',
                      'company': by_id[g[0]]['company'], 'postings': [_brief(by_id[x]) for x in g]})
        picked += 1
        if picked >= sample:
            break
    return items


LABEL_KIND = {'same': 'repost', 'career': 'career_variant', 'location': 'location_variant', 'different': 'other_variant'}


def proposed_kind(item, pairs):
    """The code's call for a review item: 'repost' for a pair, the most common pair kind inside a group."""
    ids = item['item'].split(':')[1:]
    kinds = collections.Counter(p['kind'] for p in pairs if p['a'] in ids and p['b'] in ids)
    return kinds.most_common(1)[0][0] if kinds else None


def score_review(queue, labels, pairs):
    """Agreement between the person's call and the code's call, per question; 'unsure' is counted apart."""
    out = {}
    for question in ('repost', 'variant'):
        items = [i for i in queue if i['question'] == question and i['item'] in labels]
        sure = [i for i in items if labels[i['item']]['label'] != 'unsure']
        agree = sum(1 for i in sure if LABEL_KIND.get(labels[i['item']]['label']) == proposed_kind(i, pairs))
        out[question] = {'labeled': len(items), 'unsure': len(items) - len(sure), 'agree': agree,
                         'agreement': round(agree / len(sure), 3) if sure else None,
                         'person_calls': dict(collections.Counter(labels[i['item']]['label'] for i in items))}
    return out


def _brief(p):
    return {'id': p['id'], 'title': p['title'], 'date': (p.get('date_created') or '')[:10], 'url': p['url']}


def earlier_rounds(n):
    """Postings and companies shown in rounds before n."""
    ids, companies = set(), set()
    for k in range(1, n):
        path = round_paths(k)['queue']
        if path.exists():
            for item in json.loads(path.read_text(encoding='utf-8')):
                ids |= set(item['item'].split(':')[1:])
                companies.add(item['company'])
    return ids, companies


def score_round(n):
    """The code's call frozen when the round was drawn ('at_review') and today's call ('now').
    Only 'at_review' is a fair score; 'now' on an earlier round was tuned on those same answers."""
    paths = round_paths(n)
    queue = json.loads(paths['queue'].read_text(encoding='utf-8'))
    labels = json.loads(paths['labels'].read_text(encoding='utf-8'))['labels']
    out = {'round': n, 'at_review': score_review(queue, labels, json.loads(paths['pairs'].read_text(encoding='utf-8')))}
    current = OUT / 'v1_pairs.json'
    if current.exists():
        out['now'] = score_review(queue, labels, json.loads(current.read_text(encoding='utf-8')))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--snapshot', default=SNAPSHOT)
    ap.add_argument('--round', type=int, help='draw this review round (never overwrites a drawn round); with --score, score it')
    ap.add_argument('--score', action='store_true', help='score a review round (default 1)')
    args = ap.parse_args(argv)
    if args.score:
        print(json.dumps(score_round(args.round or 1), ensure_ascii=False, indent=1))
        return
    doc = json.loads(Path(args.snapshot).read_text(encoding='utf-8'))
    rows = {f"jumpit-{r['source_id']}": r for r in doc['postings']}
    postings = [to_posting(r) for r in doc['postings']]
    on = dt.date.fromisoformat(doc['snapshot_at'][:10])
    pairs = find_pairs(postings)
    report = {'snapshot_at': doc['snapshot_at'], 'rows': len(rows), 'visible_on': on.isoformat(),
              'pairs_by_kind': dict(collections.Counter(p['kind'] for p in pairs)),
              'repost': summarize(groups_of(pairs, {'repost'}), rows, on),
              'variant_all': summarize(groups_of(pairs, {'career_variant', 'location_variant', 'other_variant'}), rows, on)}
    for kind in ('career_variant', 'location_variant', 'other_variant'):
        report[kind] = summarize(groups_of(pairs, {kind}), rows, on)
    # Postings the blind test set holds, or that were already shown in discussion, stay out of review.
    exclude = set(json.loads((ROOT / 'eval' / 'gold.test.json').read_text(encoding='utf-8'))['labels'])
    seen = OUT / 'shown_in_discussion.json'
    if seen.exists():
        exclude |= set(json.loads(seen.read_text(encoding='utf-8')))
    (OUT / 'v1_pairs.json').write_text(json.dumps(pairs, ensure_ascii=False), encoding='utf-8')
    (OUT / 'v1_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    if args.round:
        paths = round_paths(args.round)
        if paths['queue'].exists():
            report['review_queue'] = f"round {args.round} already drawn — left as is"
        else:
            shown, companies = earlier_rounds(args.round)
            queue = review_queue(pairs, postings, exclude | shown, seed=ROUND_SEEDS.get(args.round, SEED + args.round),
                                 skip_companies=companies)
            paths['queue'].write_text(json.dumps(queue, ensure_ascii=False, indent=1), encoding='utf-8')
            paths['pairs'].write_text(json.dumps(pairs, ensure_ascii=False), encoding='utf-8')
            report['review_queue'] = {'round': args.round, **collections.Counter(i['question'] for i in queue)}
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
