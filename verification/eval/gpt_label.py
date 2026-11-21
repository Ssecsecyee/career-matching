"""GPT helps with the V3·V4 labels; the person reviews every one on the labeling screen.

    python -m eval.gpt_label export                 # -> data/real/jumpit/gpt_label/part1..4.md (posting text, git-ignored)
    python -m eval.gpt_label import answers1.json … # GPT's JSON answers -> eval/gold.conditions.json
    python -m eval.gpt_label export --set holdout   # the unseen 20 (eval/gold.holdout.json) -> data/real/jumpit/gpt_label_holdout/

Only conditions the person has not answered go out, and an import never overwrites a person's answer.
Each imported label carries source "gpt" and reviewed False; saving the posting on the screen marks it
reviewed and keeps GPT's first answer next to it, so the share the person changed can be reported.
The answer key can be sealed only when every GPT label has been reviewed. Nothing here prints posting text.
"""
import argparse
import json
import re
from pathlib import Path

from eval.condition_gold import CATEGORIES, GOLD, SNAPSHOT, conditions_of, is_sealed, load_parser, missing_terms

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data' / 'real' / 'jumpit' / 'gpt_label'
SETS = {'test': (GOLD, OUT),
        'holdout': (ROOT / 'eval' / 'gold.holdout.json', ROOT / 'data' / 'real' / 'jumpit' / 'gpt_label_holdout')}
GUIDE = ROOT / 'docs' / 'eval' / 'labeling-guide.md'
PER_PART = 5
CHOICES = list(CATEGORIES) + ['not_condition']
RELATIONS = ('all', 'any', 'mixed', 'unknown')

INSTRUCTIONS = """# 채용공고 조건 라벨링

아래는 채용공고의 자격요건(필수)·우대사항(우대)을 줄 단위로 나눈 것입니다. 줄마다 세 가지를 정해 JSON으로만 답하세요.

## 1. category — 이 줄이 주로 묻는 것 하나
- skill: 언어·프레임워크·라이브러리·DB·클라우드와 그 서비스·도구·프로토콜·방법론(TDD, MSA, CI/CD)의 이름, 업무 도메인(금융·커머스·반도체 등), 어학(영어 가능 등), 기술 범주어(RDBMS, NoSQL, WAS, 메시지 큐). "~경험"으로 끝나도 그 대상이 이것들이면 skill. 일반 능력을 묻는 문장이라도 도구 이름이 예시로 붙으면 skill.
- experience: 경력 연차·기간, 어디서 일해 봤는지(스타트업·SI·컨설팅펌 근무 등)
- education: 학위·전공
- certificate: 자격증
- attitude: 태도·소통·성격
- other: 이름 없는 일반 능력(문제 해결, API 설계, 형상관리, 모니터링, CS 기초 등), 제품·서비스명, 지급 장비
- not_condition: 안내 문구·제목처럼 요구 조건이 아닌 줄

## 2. terms — 이 줄에 나온 기술 이름 목록
- 원문에 적힌 그대로, 이름만 적습니다("커머스 도메인 경험"이면 "커머스"). 번역하거나 표준 이름으로 바꾸지 마세요.
- category와 상관없이 기술 이름이 보이면 적습니다. 없으면 빈 목록 [].
- 회사명이 붙은 제품은 회사 플랫폼도 적습니다("AWS SQS/SNS" → AWS, SQS, SNS). 범주 이름과 제품이 함께 나오면 둘 다 적습니다.

## 3. relation — terms가 2개 이상일 때만 (1개 이하면 null)
- any(하나만 있으면 됨): "A/B", "A 또는 B", "A, B 등", "A 중 1개 이상"처럼 서로 대신할 수 있는 예시. 범주 이름 뒤에 제품을 예시로 나열한 경우("RDBMS(MySQL·Oracle 등)").
- all(모두 필요): 하는 일이 다른 기술의 나열("Redis, Kafka 등"은 캐시와 메시지 전달이라 all), 선후 관계인 기술("Docker, Kubernetes"), 단순 나열("Java, Spring, MySQL").
- mixed: 둘이 섞임(예: "Java 또는 Kotlin, 그리고 Spring") — note에 구조를 적으세요.
- unknown: 읽어도 판단할 수 없음.

## 답 형식
id마다 하나씩, 아래 형식의 JSON 배열 하나만 출력하세요. 설명 문장은 쓰지 마세요. 판단이 애매하면 note에 이유를 짧게 적으세요.
```json
[{"id": "P01-C01", "category": "skill", "terms": ["Java", "Kotlin"], "relation": "any", "note": ""}]
```
"""


def condition_ids(gold):
    """Screen numbering: P{posting}-C{condition}, the same numbers the labeling screen shows."""
    return {f'P{p:02d}-C{n:02d}': c['key'] for p, job in enumerate(gold['jobs'].values(), 1)
            for n, c in enumerate(job['conditions'], 1)}


def export(gold, snapshot_path=SNAPSHOT, out_dir=OUT, per_part=PER_PART):
    rows = {f"jumpit-{r['source_id']}": r for r in json.loads(Path(snapshot_path).read_text(encoding='utf-8'))['postings']}
    parser, _ = load_parser()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    jobs = list(gold['jobs'].items())
    files, sent = [], 0
    for start in range(0, len(jobs), per_part):
        lines = [INSTRUCTIONS, f'\n# 공고 {start + 1}~{min(start + per_part, len(jobs))}번\n']
        count = 0
        for p, (job_id, job) in enumerate(jobs[start:start + per_part], start + 1):
            row = rows[job_id]
            quotes = {c['key']: c['quote'] for c in conditions_of(row, parser)}
            todo = [(n, c) for n, c in enumerate(job['conditions'], 1) if c['key'] not in gold['labels']]
            if not todo:
                continue
            lines.append(f"\n## P{p:02d} · {row.get('company_name', '')} · {row.get('title', '')}\n")
            for n, c in todo:
                kind = '필수(자격요건)' if c['type'] == 'required' else '우대(우대사항)'
                lines.append(f"### P{p:02d}-C{n:02d} · {kind}\n```\n{quotes[c['key']].strip()}\n```\n")
                count += 1
        if count:
            path = out_dir / f'part{len(files) + 1}.md'
            path.write_text('\n'.join(lines), encoding='utf-8')
            files.append({'file': str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path), 'conditions': count})
            sent += count
    return {'files': files, 'conditions_sent': sent, 'already_answered_by_person': len(gold['labels'])}


def parse_answers(text):
    """The JSON array from GPT's reply (a ```json block or the bare array)."""
    block = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', text, re.S)
    body = block.group(1) if block else text[text.find('['):text.rfind(']') + 1]
    return json.loads(body)


def import_answers(gold, answers, snapshot_path=SNAPSHOT):
    """Put GPT's answers into unanswered conditions. Counts only — never the text."""
    ids = condition_ids(gold)
    rows = {f"jumpit-{r['source_id']}": r for r in json.loads(Path(snapshot_path).read_text(encoding='utf-8'))['postings']}
    parser, _ = load_parser()
    quotes = {}
    for job_id in gold['jobs']:
        quotes.update({c['key']: c['quote'] for c in conditions_of(rows[job_id], parser)})
    stats = {'imported': 0, 'kept_person_answer': 0, 'unknown_id': 0, 'invalid': 0, 'names_not_in_text': 0}
    for a in answers:
        key = ids.get(str(a.get('id', '')).strip())
        if not key:
            stats['unknown_id'] += 1
            continue
        if key in gold['labels']:
            stats['kept_person_answer'] += 1
            continue
        choice = a.get('category')
        terms = [str(t).strip() for t in (a.get('terms') or []) if str(t).strip()]
        rel = a.get('relation')
        if choice not in CHOICES or (len(terms) >= 2 and rel not in RELATIONS):
            stats['invalid'] += 1
            continue
        joined = ', '.join(terms)
        if missing_terms(joined, quotes[key]):
            stats['names_not_in_text'] += 1
        draft = {'category': 'other' if choice == 'not_condition' else choice, 'not_condition': choice == 'not_condition',
                 'terms': joined, 'relation': rel if len(terms) >= 2 else None, 'unknown': rel == 'unknown',
                 'note': str(a.get('note') or '').strip()}
        gold['labels'][key] = {**draft, 'source': 'gpt', 'reviewed': False, 'gpt_draft': dict(draft)}
        stats['imported'] += 1
    if gold['labels'] and gold.get('status') == 'blank':
        gold['status'] = 'in_progress'
    return stats


def review_stats(gold):
    """How many GPT drafts the person has reviewed, and how many of those the person changed."""
    gpt = [l for l in gold['labels'].values() if l.get('source') == 'gpt']
    done = [l for l in gpt if l.get('reviewed')]
    fields = ('category', 'not_condition', 'terms', 'relation')
    changed = [l for l in done if any(l.get(f) != l['gpt_draft'].get(f) for f in fields)]
    return {'gpt_drafts': len(gpt), 'reviewed': len(done), 'changed_by_person': len(changed),
            'person_only': len(gold['labels']) - len(gpt)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('command', choices=('export', 'import', 'stats'))
    ap.add_argument('files', nargs='*')
    ap.add_argument('--set', choices=tuple(SETS), default='test', help='test = 첫 시험지, holdout = 새 공고 20건')
    args = ap.parse_args(argv)
    gold_path, out_dir = SETS[args.set]
    gold = json.loads(gold_path.read_text(encoding='utf-8'))
    if args.command == 'export':
        print(json.dumps(export(gold, out_dir=out_dir), ensure_ascii=False, indent=1))
    elif args.command == 'import':
        if is_sealed(gold):
            raise SystemExit(f'{gold_path.name}은 봉인돼 있어 가져오지 않습니다.')
        answers = [a for f in args.files for a in parse_answers(Path(f).read_text(encoding='utf-8'))]
        stats = import_answers(gold, answers)
        gold_path.write_text(json.dumps(gold, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        print(json.dumps(stats, ensure_ascii=False))
    else:
        print(json.dumps(review_stats(gold), ensure_ascii=False))


if __name__ == '__main__':
    main()
