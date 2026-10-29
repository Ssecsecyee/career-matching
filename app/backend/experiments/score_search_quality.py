"""Score a completed pilot after human review; unjudged pools are rejected."""
import csv
import json
import math
from pathlib import Path
import sys

folder = Path(sys.argv[1])
results = json.loads((folder / 'results.json').read_text(encoding='utf-8'))
with (folder / 'judgments.csv').open(encoding='utf-8-sig', newline='') as f:
    rows = list(csv.DictReader(f))
if any(r['grade_0_to_3'] not in ('0', '1', '2', '3') for r in rows):
    raise SystemExit('Complete every pooled judgment with an integer 0..3 first.')
grades = {(r['query_id'], r['source_id']): int(r['grade_0_to_3']) for r in rows}
def dcg(values):
    return sum((2 ** v - 1) / math.log2(i + 2) for i, v in enumerate(values))
scored = []
for r in results:
    qid = r['query_id']
    g = [grades[qid, i] for i in r['ids'][:5]]
    ideal = sorted([v for (q, _), v in grades.items() if q == qid], reverse=True)[:5]
    denominator = dcg(ideal)
    scored.append(dict(query_id=qid, arm=r['arm'], precision_at_5=sum(v >= 2 for v in g) / 5,
                       ndcg_at_5=dcg(g) / denominator if denominator else None,
                       reciprocal_rank_at_5=next((1 / (i + 1) for i, v in enumerate(g) if v >= 2), 0),
                       note='Pooled judgments; no claim of full-corpus recall. Relevance threshold >=2.'))
(folder / 'scores.json').write_text(json.dumps(scored, indent=2), encoding='utf-8')
print('Saved scores.json. Zero-relevance queries have undefined nDCG.')
