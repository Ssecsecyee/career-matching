"""V3·V4 blind answer key in the teammate's condition format.

    python -m eval.condition_gold draw      # 20 test postings -> eval/gold.conditions.json (no posting text)
    python -m eval.condition_gold status    # how far labeling has gone

Unit: one condition as the teammate's own splitter cuts it (career-matching
app/backend/src/services/condition_structure.py, condition-split-v3), loaded read-only from that repo.
For each condition the person writes (docs/eval/labeling-guide.md, V3·V4 section):
  category  skill / experience / education / certificate / attitude / other
  terms     skill names as written; ',' = all of them, '|' = any one of them ("Java | Kotlin, Spring")
  unknown   the person cannot tell how the terms relate
The file holds ids, offsets and labels only. Posting text stays in data/real/ (git-ignored).
"""
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path

from skillpath.sources.jumpit import CLEANED, SEEN, SEED, SNAPSHOT, sample

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / 'eval' / 'gold.conditions.json'
OLD_TEST = ROOT / 'eval' / 'gold.test.json'
TEAMMATE = Path(os.getenv('CAREER_MATCHING', ROOT.parent / 'career-matching'))
PARSER_FILE = TEAMMATE / 'app' / 'backend' / 'src' / 'services' / 'condition_structure.py'
SIZE = 20
CATEGORIES = {'skill': '기술', 'experience': '경력', 'education': '학력', 'certificate': '자격증',
              'attitude': '성향', 'other': '기타'}
SECTIONS = (('required', 'qualifications'), ('preferred', 'preferred_requirements'))


def load_parser(path=PARSER_FILE):
    """The teammate's splitter, imported from its file without changing it."""
    spec = importlib.util.spec_from_file_location('teammate_condition_structure', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, hashlib.sha256(Path(path).read_bytes()).hexdigest()


def conditions_of(row, parser):
    """Conditions of one snapshot row, exactly as the teammate's service would cut them."""
    out = []
    for kind, field in SECTIONS:
        text = row.get(field) or ''
        if isinstance(text, str) and text.strip():
            out += parser.structure_conditions(text, kind, str(row['source_id']), row.get('source_version') or 1)
    return out


def snapshot_rows():
    doc = json.loads(SNAPSHOT.read_text(encoding='utf-8'))
    return {f"jumpit-{r['source_id']}": r for r in doc['postings']}, doc


def parse_terms(value):
    """'Java | Kotlin, Spring' -> [['Java', 'Kotlin'], ['Spring']] (all of the groups, any one inside a group)."""
    groups = []
    for chunk in (value or '').split(','):
        options = [t.strip() for t in chunk.split('|') if t.strip()]
        if options:
            groups.append(options)
    return groups


def relation(label):
    """The person's AND/OR reading of one condition: atom, all, any, mixed, unknown or none."""
    groups = parse_terms(label.get('terms'))
    count = sum(len(g) for g in groups)
    if count == 0:
        return 'none'
    if count == 1:
        return 'atom'
    if label.get('relation') in ('all', 'any', 'mixed', 'unknown'):     # chosen on the screen (11/16 on)
        return label['relation']
    if label.get('unknown'):                                              # earlier answers: written with ',' and '|'
        return 'unknown'
    if len(groups) == 1:
        return 'any'
    return 'all' if all(len(g) == 1 for g in groups) else 'mixed'


def missing_terms(terms, quote):
    """Terms the person typed that are not in the condition text (case-insensitive)."""
    low = quote.lower()
    return [t for g in parse_terms(terms) for t in g if t.lower() not in low]


def draw(size=SIZE):
    """Same seed and pool as the first 10 (skillpath.sources.jumpit sample), drawn to `size`."""
    postings = json.loads(CLEANED.read_text(encoding='utf-8'))['postings']
    seen = json.loads(SEEN.read_text(encoding='utf-8')) if SEEN.exists() else []
    drawn = sample(postings, n=size, seed=SEED, exclude=seen)
    first = set(json.loads(OLD_TEST.read_text(encoding='utf-8'))['labels']) if OLD_TEST.exists() else set()
    rows, snap = snapshot_rows()
    parser, parser_sha = load_parser()
    jobs = {}
    for p in drawn:
        row = rows[p['id']]
        jobs[p['id']] = {'source_version': row.get('source_version') or 1, 'url': row.get('source_url'),
                         'conditions': [{'id': c['id'], 'key': c['key'], 'type': c['type'],
                                         'spans': [[s['start'], s['end'], s['kind']] for s in c['source_spans']],
                                         'parse_notes': c['parse_notes']} for c in conditions_of(row, parser)]}
    return {
        '_comment': 'V3·V4 시험 정답(블라인드). 사람이 원문만 보고 조건마다 범주·기술 이름·관계를 적는다. '
                    '원문은 넣지 않는다(위치만). 봉인 전에는 규칙·프롬프트를 이 공고로 고치지 않는다(D-010).',
        'status': 'blank', 'labeled_by': 'pending (human, blind)',
        'guideline': 'docs/eval/labeling-guide.md (V3·V4 시험 정답)',
        'parser': {'file': 'career-matching/app/backend/src/services/condition_structure.py',
                   'version': parser.PARSER_VERSION, 'sha256': parser_sha},
        'snapshot': {'at': snap.get('snapshot_at'), 'sha256': (snap.get('sha256') or '')[:16]},
        'sample': {'seed': SEED, 'size': len(drawn), 'pool': 'jumpit backend after cleaning, one per company',
                   'includes_first_10': sorted(first) == sorted(set(jobs) & first)},
        'jobs': jobs, 'labels': {}, 'sealed': None,
    }


def settled(label):
    """Answered by the person, or a GPT draft the person has reviewed on the screen."""
    return bool(label) and (label.get('source') != 'gpt' or bool(label.get('reviewed')))


def progress(gold):
    """'labeled' counts settled answers only: an unreviewed GPT draft is not an answer yet."""
    keys = [c['key'] for j in gold['jobs'].values() for c in j['conditions']]
    done = sum(1 for k in keys if settled(gold['labels'].get(k)))
    pending = sum(1 for k in keys if k in gold['labels'] and not settled(gold['labels'][k]))
    return {'status': gold['status'], 'postings': len(gold['jobs']), 'conditions': len(keys), 'labeled': done,
            'gpt_drafts_to_review': pending,
            'postings_done': sum(1 for j in gold['jobs'].values()
                                 if all(settled(gold['labels'].get(c['key'])) for c in j['conditions']))}


def seal(gold, allow_unreviewed=False):
    """Freeze the answers: the hash lets the B/C scorer refuse an answer key that changed after sealing.
    allow_unreviewed seals GPT drafts the person did not review (user decision 2026-11-16); the counts
    of who answered what are written into the seal so the report can state them."""
    keys = [c['key'] for j in gold['jobs'].values() for c in j['conditions']]
    answered = sum(1 for k in keys if k in gold['labels'])
    if answered != len(keys):
        raise ValueError(f'not every condition is labeled ({answered}/{len(keys)})')
    labels = [gold['labels'][k] for k in keys]
    unreviewed = sum(1 for l in labels if l.get('source') == 'gpt' and not l.get('reviewed'))
    if unreviewed and not allow_unreviewed:
        raise ValueError(f'{unreviewed} GPT drafts are not reviewed by the person yet')
    body = json.dumps(gold['labels'], ensure_ascii=False, sort_keys=True).encode('utf-8')
    gold['status'] = 'sealed'
    gold['sealed'] = {'at': dt.datetime.now().isoformat(timespec='seconds'), 'labels_sha256': hashlib.sha256(body).hexdigest(),
                      'answered_by': {'person': sum(1 for l in labels if l.get('source') != 'gpt'),
                                      'gpt_reviewed_by_person': sum(1 for l in labels if l.get('source') == 'gpt' and l.get('reviewed')),
                                      'gpt_not_reviewed': unreviewed}}
    return gold


def is_sealed(gold):
    if gold.get('status') != 'sealed' or not gold.get('sealed'):
        return False
    body = json.dumps(gold['labels'], ensure_ascii=False, sort_keys=True).encode('utf-8')
    return hashlib.sha256(body).hexdigest() == gold['sealed']['labels_sha256']


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('command', choices=('draw', 'status', 'seal'))
    ap.add_argument('--gpt-as-is', action='store_true', help='seal GPT drafts the person did not review')
    args = ap.parse_args(argv)
    if args.command == 'seal':
        gold = json.loads(GOLD.read_text(encoding='utf-8'))
        if is_sealed(gold):
            raise SystemExit('이미 봉인돼 있습니다.')
        seal(gold, allow_unreviewed=args.gpt_as_is)
        GOLD.write_text(json.dumps(gold, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        print(json.dumps(gold['sealed'], ensure_ascii=False))
        return
    if args.command == 'draw':
        if GOLD.exists() and json.loads(GOLD.read_text(encoding='utf-8')).get('labels'):
            raise SystemExit(f'{GOLD.name}에 이미 답이 있습니다. 시험지는 한 번만 뽑습니다.')
        gold = draw()
        GOLD.write_text(json.dumps(gold, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        # Counts only: the drawn text is not printed, so nobody tuning rules or prompts sees it.
        print(json.dumps({**progress(gold), 'includes_first_10': gold['sample']['includes_first_10']}, ensure_ascii=False))
    else:
        print(json.dumps(progress(json.loads(GOLD.read_text(encoding='utf-8'))), ensure_ascii=False))


if __name__ == '__main__':
    main()
