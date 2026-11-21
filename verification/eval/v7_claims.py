"""V7+ — are the consultation answers factually right, claim by claim? (post-hoc re-scoring of saved answers)

    python -m eval.v7_claims packets     # one file per posting: what the posting says + the saved B answers
    python -m eval.v7_claims check       # code checks on the judged files: quotes must be real
    python -m eval.v7_claims summary
    python -m eval.v7_claims review      # the contradicted / unsupported / unclear claims as one sheet for a person

V7 only counted whether expected skill names appear in an answer. This looks the other way: every factual
statement an answer makes about the posting is listed and judged against the posting text.
  supported     the posting says so (evidence = exact quote from the posting)
  contradicted  the posting says otherwise (evidence = the quote it contradicts)
  unsupported   stated as a fact about this posting, but nothing in the posting backs it
  advice        clearly general advice or explanation, not a claim about this posting
  meta          talk about the conversation itself (offers, next steps, section headings)
  unclear       cannot be judged from the posting
A judge (an AI draft, then a person on the flagged ones) writes the claims; code verifies that every quoted
answer span is in the answer and every evidence quote is in the posting. Nothing is sent to Bedrock.
Packets and judged files hold posting text and stay under data/real (not in git).
"""
import argparse
import collections
import json
import re
from pathlib import Path

from eval.condition_gold import GOLD, SNAPSHOT

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / 'data' / 'real' / 'jumpit' / 'v7_runs'
OUT = ROOT / 'data' / 'real' / 'jumpit' / 'v7_claims'
QUESTIONS = ('required', 'preferred', 'experience')
VERDICTS = ('supported', 'contradicted', 'unsupported', 'advice', 'meta', 'unclear')
FACTUAL = ('supported', 'contradicted', 'unsupported')
TAGS = ('level_swap', 'years_wrong', 'guarantee', 'substitute')   # 필수·우대 뒤바뀜 / 연차 왜곡 / 합격 단정 / 교육으로 경력·학위 대체
FIELDS = ('title', 'company_name', 'qualifications', 'preferred_requirements', 'responsibilities')


def squash(text):
    """Whitespace and Markdown emphasis do not count when checking that a quote is really there."""
    return re.sub(r'[\s*_`#>|-]+', '', text or '')


def posting_of(row):
    out = {k: row.get(k) or '' for k in FIELDS}
    out['tech_stacks'] = ', '.join(row.get('tech_stacks') or [])
    out['career'] = json.dumps({k: row.get(k) for k in ('min_career_years', 'max_career_years', 'newcomer')}, ensure_ascii=False)
    return out


def packets(gold, variant='B', runs=RUNS, snapshot_path=SNAPSHOT, out_dir=OUT):
    rows = {f"jumpit-{r['source_id']}": r for r in json.loads(Path(snapshot_path).read_text(encoding='utf-8'))['postings']}
    target = Path(out_dir) / 'packets'
    target.mkdir(parents=True, exist_ok=True)
    made = []
    for job_id in gold['jobs']:
        path = Path(runs) / f'{job_id}.json'
        if not path.exists():
            continue
        record = json.loads(path.read_text(encoding='utf-8'))
        packet = {'job_id': job_id, 'variant': variant, 'posting': posting_of(rows[job_id]),
                  'answers': {q: {'question': record['answers'][q]['question'],
                                  'answer': record['answers'][q]['variants'][variant]['message']} for q in QUESTIONS}}
        (target / f'{job_id}.json').write_text(json.dumps(packet, ensure_ascii=False, indent=1), encoding='utf-8')
        made.append(job_id)
    return made


def problems(judged, packet):
    """What code can verify about a judged file. An empty list means every quote is real."""
    out = []
    posting = squash(' '.join(packet['posting'].values()))
    for q in QUESTIONS:
        claims = (judged.get('answers') or {}).get(q)
        if claims is None:
            out.append(f'{q}: 판정 없음')
            continue
        answer = squash(packet['answers'][q]['answer'])
        for i, c in enumerate(claims, 1):
            where = f'{q}#{i}'
            if c.get('verdict') not in VERDICTS:
                out.append(f'{where}: 알 수 없는 판정 {c.get("verdict")!r}')
            if not c.get('answer_quote') or squash(c['answer_quote']) not in answer:
                out.append(f'{where}: 답변에 없는 인용')
            if c.get('verdict') in ('supported', 'contradicted'):
                if not c.get('evidence') or squash(c['evidence']) not in posting:
                    out.append(f'{where}: 공고에 없는 근거')
            for tag in c.get('tags') or []:
                if tag not in TAGS:
                    out.append(f'{where}: 알 수 없는 표시 {tag!r}')
    return out


def load(out_dir=OUT):
    out = {}
    for path in sorted((Path(out_dir) / 'judged').glob('*.json')):
        packet = json.loads((Path(out_dir) / 'packets' / path.name).read_text(encoding='utf-8'))
        out[path.stem] = (json.loads(path.read_text(encoding='utf-8')), packet)
    return out


def summary(files):
    """files: {job_id: (judged, packet)}. Rates are over factual claims; advice and meta are counted apart."""
    by_q = {q: collections.Counter() for q in QUESTIONS}
    tags, flagged, answers_with_issue, answers, reviewed = collections.Counter(), [], 0, 0, 0
    for job_id, (judged, _) in files.items():
        for q in QUESTIONS:
            claims = judged['answers'].get(q) or []
            answers += 1
            bad = [c for c in claims if c['verdict'] in ('contradicted', 'unsupported')]
            answers_with_issue += bool(bad)
            for c in claims:
                by_q[q][c['verdict']] += 1
                tags.update(c.get('tags') or [])
                reviewed += bool(c.get('reviewed_from'))      # verdict changed when the flagged claims were re-read
            flagged += [{'job_id': job_id, 'question': q, 'verdict': c['verdict'], 'tags': c.get('tags') or [],
                         'answer_quote': c['answer_quote'], 'evidence': c.get('evidence'), 'note': c.get('note')} for c in bad]
    total = sum(by_q.values(), collections.Counter())
    factual = sum(total[v] for v in FACTUAL)

    def rates(c):
        n = sum(c[v] for v in FACTUAL)
        return {'factual_claims': n, **{v: c[v] for v in VERDICTS},
                'supported_rate': round(c['supported'] / n, 3) if n else None,
                'unsupported_rate': round(c['unsupported'] / n, 3) if n else None,
                'contradicted_rate': round(c['contradicted'] / n, 3) if n else None}
    return {'postings': len(files), 'answers': answers, 'claims': sum(total.values()), 'factual_claims': factual,
            'all': rates(total), 'by_question': {q: rates(by_q[q]) for q in QUESTIONS},
            'answers_with_contradicted_or_unsupported': answers_with_issue,
            'postings_with_contradicted': len({f['job_id'] for f in flagged if f['verdict'] == 'contradicted'}),
            'verdicts_changed_on_review': reviewed, 'tags': dict(tags), 'flagged': flagged}


def review_rows(files, verdicts=('contradicted', 'unsupported', 'unclear')):
    """The claims a person has to confirm, one row each: the AI's verdict and the quotes it rests on."""
    rows = []
    for job_id, (judged, _) in sorted(files.items()):
        for q in QUESTIONS:
            for i, c in enumerate(judged['answers'].get(q) or [], 1):
                if c['verdict'] in verdicts:
                    rows.append({'n': len(rows) + 1, 'job_id': job_id, 'question': q, 'claim': f'{q}#{i}',
                                 'verdict': c['verdict'], 'answer_quote': c.get('answer_quote') or '',
                                 'evidence': c.get('evidence') or '', 'note': c.get('note') or ''})
    return rows


def review_sheet(rows):
    """Markdown sheet (posting text inside: written under data/real only). The person fills the last column."""
    cell = lambda s: ' '.join(str(s).split()).replace('|', '/')      # noqa: E731 — one table cell
    lines = ['# V7+ 사람 확인표', '',
             'AI가 "모순·근거 없음·판단 불가"로 둔 주장만 모았다. 마지막 칸에 맞음 / 바꿈(→판정) 중 하나를 적는다.',
             '판정 뜻: contradicted 공고와 반대 · unsupported 공고에 근거 없음 · unclear 공고만으로 판단 불가', '',
             '| # | 공고 | 질문 | AI 판정 | 답변에서 | 공고 근거 | AI 메모 | 사람 판정 |', '|---|---|---|---|---|---|---|---|']
    lines += [f"| {r['n']} | {r['job_id']} | {r['question']} | {r['verdict']} | {cell(r['answer_quote'])} | "
              f"{cell(r['evidence'])} | {cell(r['note'])} |  |" for r in rows]
    return '\n'.join(lines) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('command', choices=('packets', 'check', 'summary', 'review'))
    args = ap.parse_args(argv)
    if args.command == 'packets':
        made = packets(json.loads(GOLD.read_text(encoding='utf-8')))
        print(json.dumps({'packets': len(made), 'dir': str(OUT / 'packets')}, ensure_ascii=False))
        return
    files = load()
    if args.command == 'check':
        bad = {job: p for job, (judged, packet) in files.items() if (p := problems(judged, packet))}
        print(json.dumps({'judged': len(files), 'files_with_problems': len(bad), 'problems': bad}, ensure_ascii=False, indent=1))
    elif args.command == 'review':
        rows = review_rows(files)
        path = OUT / 'review_sheet.md'
        path.write_text(review_sheet(rows), encoding='utf-8')
        print(json.dumps({'rows': len(rows), 'by_verdict': dict(collections.Counter(r['verdict'] for r in rows)),
                          'sheet': str(path)}, ensure_ascii=False))
    else:
        report = summary(files)
        (OUT / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
        print(json.dumps({k: v for k, v in report.items() if k != 'flagged'}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
