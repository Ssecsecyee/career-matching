"""Second rater — does another person sort the conditions the same way? (inter-rater agreement)

    python -m eval.second_rater sheet     # 5 unseen postings (~50 lines) -> a CSV the teammate fills in
    python -m eval.second_rater score     # after both filled: agreement and Cohen's kappa on category

The postings come from the independent test set (eval/gold.holdout.json), drawn with a fixed seed before
anyone labelled them. The teammate sees the posting text only — never the user's answers, never a model's.
The user labels the same lines on the usual screen without seeing the teammate's sheet.
The CSV holds posting text and stays under data/real (not in git); eval/second_rater_sheet.json keeps ids only.
"""
import argparse
import collections
import csv
import json
import random
from pathlib import Path

from eval.condition_gold import CATEGORIES, conditions_of, load_parser, snapshot_rows
from eval.holdout import HOLDOUT
from eval.live_run import DISPLAY

ROOT = Path(__file__).resolve().parents[1]
SHEET_KEY = ROOT / 'eval' / 'second_rater_sheet.json'
OUT = ROOT / 'data' / 'real' / 'jumpit' / 'second_rater'
SEED = 20261119
POSTINGS = 5
CHOICES = {**{v: k for k, v in CATEGORIES.items()}, '조건 아님': 'not_condition'}     # Korean word -> label
HELP = ('기술 = 언어·프레임워크·DB·클라우드·도구 이름, 업무 도메인(금융·커머스 등), 어학 · 경력 = 연차, 어디서 일해 봤는지 · '
        '학력 · 자격증 · 성향 = 태도·소통 · 기타 = 이름 없는 일반 능력(문제 해결, API 설계 등) · '
        '조건 아님 = 안내 문구·제목처럼 요구 조건이 아닌 줄')


def draw(gold, seed=SEED, size=POSTINGS):
    return random.Random(seed).sample(sorted(gold['jobs']), size)


def sheet(gold, rows, parser, seed=SEED):
    """Rows of the CSV and the id key, in posting order then line order."""
    lines, key = [], []
    for job_id in draw(gold, seed):
        row = rows[job_id]
        by_key = {c['key']: c for c in conditions_of(row, parser)}
        for c in gold['jobs'][job_id]['conditions']:
            n = len(lines) + 1
            lines.append({'번호': n, '공고': f"{row.get('company_name', '')} · {row.get('title', '')}",
                          '칸': '필수' if c['type'] == 'required' else '우대',
                          '조건 원문': by_key[c['key']]['quote'].strip(), '분류': '', '메모': ''})
            key.append({'n': n, 'job_id': job_id, 'key': c['key']})
    return lines, {'seed': seed, 'postings': draw(gold, seed), 'lines': key, 'choices': list(CHOICES)}


def kappa(pairs):
    """Cohen's kappa for two raters over the same items: (observed - chance) / (1 - chance)."""
    n = len(pairs)
    if not n:
        return None
    observed = sum(a == b for a, b in pairs) / n
    left, right = collections.Counter(a for a, _ in pairs), collections.Counter(b for _, b in pairs)
    chance = sum(left[c] * right[c] for c in left) / (n * n)
    return round((observed - chance) / (1 - chance), 3) if chance < 1 else 1.0


def score(key, filled, user_labels):
    """filled: {n: Korean choice} from the teammate; user_labels: holdout labels by condition key."""
    pairs, missing, unknown = [], [], []
    for line in key['lines']:
        theirs = (filled.get(line['n']) or '').strip()
        mine = user_labels.get(line['key'])
        if not theirs or mine is None:
            missing.append(line['n'])
            continue
        if theirs not in CHOICES:
            unknown.append(line['n'])
            continue
        mine = 'not_condition' if mine.get('not_condition') else mine.get('category')
        pairs.append((CHOICES[theirs], mine))
    confusion = collections.Counter(f'{CATEGORIES.get(a, a)}/{CATEGORIES.get(b, b)}' for a, b in pairs if a != b)
    # The primary basis of V3-H (rule-log 2026-11-19): the label the user sees, where skill, other and a
    # non-condition line all read "직무 조건". The user's holdout labels drew "skill" narrower than this sheet's
    # help text, so the category kappa mixes rater noise with that difference; this one does not.
    shown = [tuple(DISPLAY['other' if x == 'not_condition' else x] for x in p) for p in pairs]
    return {'compared': len(pairs), 'missing': missing, 'unknown_choice': unknown,
            'agreement': round(sum(a == b for a, b in pairs) / len(pairs), 3) if pairs else None,
            'kappa': kappa(pairs), 'disagreements_teammate_user': dict(confusion.most_common()),
            'display_basis': {'agreement': round(sum(a == b for a, b in shown) / len(shown), 3) if shown else None,
                              'kappa': kappa(shown)}}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('command', choices=('sheet', 'score'))
    ap.add_argument('--filled', default=str(OUT / 'filled.csv'))
    args = ap.parse_args(argv)
    gold = json.loads(HOLDOUT.read_text(encoding='utf-8'))
    if args.command == 'sheet':
        if SHEET_KEY.exists():
            raise SystemExit(f'{SHEET_KEY.name}이 이미 있습니다. 판정표는 한 번만 뽑습니다.')
        rows, _ = snapshot_rows()
        parser, _ = load_parser()
        lines, key = sheet(gold, rows, parser)
        OUT.mkdir(parents=True, exist_ok=True)
        with open(OUT / 'sheet.csv', 'w', encoding='utf-8-sig', newline='') as f:     # BOM so Excel reads Korean
            w = csv.DictWriter(f, fieldnames=list(lines[0]))
            w.writeheader()
            w.writerows(lines)
        (OUT / 'README.txt').write_text(
            '분류 칸에 아래 중 하나를 적어 주세요: ' + ' / '.join(CHOICES) + '\n' + HELP + '\n'
            '한 줄에 여러 가지가 섞여 있으면 그 줄이 주로 묻는 것 하나만 고르고, 애매하면 메모에 적어 주세요.\n',
            encoding='utf-8-sig')
        SHEET_KEY.write_text(json.dumps(key, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        print(json.dumps({'postings': len(key['postings']), 'lines': len(lines), 'csv': str(OUT / 'sheet.csv')}, ensure_ascii=False))
    else:
        key = json.loads(SHEET_KEY.read_text(encoding='utf-8'))
        with open(args.filled, encoding='utf-8-sig', newline='') as f:
            filled = {int(r['번호']): r['분류'] for r in csv.DictReader(f)}
        print(json.dumps(score(key, filled, gold['labels']), ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
