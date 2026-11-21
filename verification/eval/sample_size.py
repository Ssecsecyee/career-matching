"""How many blind test postings are needed? (docs/eval/verification.md, 2026-11-13)

    python -m eval.sample_size

1. Textbook bound for a proportion at 95%: n = (z / 2d)^2 with the worst case p = 0.5.
   Its n counts independent (posting, skill) pairs.
2. Pairs inside one posting are not independent (a mis-split posting gets many of its skills wrong
   together), so the bound is checked against data: resample whole postings from the 22 approved
   practice postings and read the width of the 95% interval of F1 for each test size.
"""
import argparse
import json
import math
import random
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
Z95 = 1.96
LEVEL_RANK = {'required': 0, 'preferred': 1, 'responsibility': 0, 'unknown': 2}   # 주요업무 = 필수 (rule 11)
RANK_LEVEL = {0: 'required', 1: 'preferred'}


def formula_n(d, p=0.5, z=Z95):
    """Pairs needed so the 95% interval of a proportion is within +/- d."""
    return math.ceil(z * z * p * (1 - p) / (d * d))


def per_posting_counts(gold_labels, claims):
    """{posting: (true positives, predicted, gold)} over required/preferred (posting, skill, level) triples."""
    pred = {}
    for c in claims:
        if c['status'] == 'rejected':
            continue
        key = (c['posting_id'], c['canonical'])
        pred[key] = min(pred.get(key, 9), LEVEL_RANK[c['requirement']])
    out = {}
    for pid, by in gold_labels.items():
        gold = {((pid, s), lvl) for lvl, names in by.items() if lvl in ('required', 'preferred') for s in names}
        got = {(k, RANK_LEVEL[r]) for k, r in pred.items() if k[0] == pid and r in RANK_LEVEL}
        out[pid] = (len(gold & got), len(got), len(gold))
    return out


def micro_f1(counts, sample):
    tp = sum(counts[p][0] for p in sample)
    predicted = sum(counts[p][1] for p in sample)
    gold = sum(counts[p][2] for p in sample)
    precision = tp / predicted if predicted else 0.0
    recall = tp / gold if gold else 0.0
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def bootstrap_halfwidth(counts, n, rounds=4000, seed=7):
    """Half-width of the 95% percentile interval of micro F1 when n postings are drawn."""
    rng = random.Random(seed)
    ids = sorted(counts)
    values = sorted(micro_f1(counts, [rng.choice(ids) for _ in range(n)]) for _ in range(rounds))
    low, high = values[int(0.025 * rounds)], values[int(0.975 * rounds)]
    return (high - low) / 2, low, high


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--gold', default=ROOT / 'eval' / 'gold.real.json')
    ap.add_argument('--claims', default=ROOT / 'data' / 'real' / 'bedrock_eval' / 'claims.json')
    args = ap.parse_args()
    print('1) 공식 n = (z/2d)^2, p = 0.5 (기술 쌍 기준)')
    for d in (0.15, 0.10, 0.07, 0.05):
        print(f'   ±{d:.2f}: {formula_n(d)} 쌍')
    counts = per_posting_counts(json.loads(Path(args.gold).read_text(encoding='utf-8'))['labels'],
                                json.loads(Path(args.claims).read_text(encoding='utf-8')))
    pairs = [c[2] for c in counts.values()]
    print(f'2) 연습 {len(counts)}건: 공고당 필수·우대 정답 쌍 평균 {statistics.mean(pairs):.1f}개')
    print('3) 공고 단위 부트스트랩 (4,000회, seed 7): F1 95% 구간')
    for n in (10, 15, 20, 30, 40, 60):
        half, low, high = bootstrap_halfwidth(counts, n)
        print(f'   공고 {n:2d}건: ±{half:.3f} ({low:.2f} ~ {high:.2f})')


if __name__ == '__main__':
    main()
