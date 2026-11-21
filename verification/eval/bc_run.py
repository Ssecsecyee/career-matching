"""V3·V4 runs: the teammate's condition classifier as is (B) and with the user's rules added (C).

    python -m eval.bc_run plan                       # calls and token estimate per variant — no call, no text printed
    python -m eval.bc_run run --variant B --live     # needs the sealed answer key and an explicit --live

The teammate's code is imported read-only from career-matching/app/backend: the same batching (plan),
the same Bedrock call (_call_batch: system prompt, tool schema, maxTokens 4096) and the same output check
(validate_review). The only change between B and C is the system prompt: C = B + eval/prompts/c_rules.md
(the parts of docs/eval/labeling-guide.md that fit the teammate's format, fixed before any test result).
Every batch result is cached under data/real/jumpit/bc_runs/<variant>/ (git-ignored, holds model quotes),
so a rerun never calls twice and scoring never calls at all.
"""
import argparse
import hashlib
import importlib
import json
import os
import sys
import time
from pathlib import Path

from eval.condition_gold import GOLD, SNAPSHOT, TEAMMATE, is_sealed

ROOT = Path(__file__).resolve().parents[1]
BACKEND = TEAMMATE / 'app' / 'backend'
RUNS = ROOT / 'data' / 'real' / 'jumpit' / 'bc_runs'
C_RULES = ROOT / 'eval' / 'prompts' / 'c_rules.md'
VARIANTS = ('B', 'C')
MODEL = os.getenv('BEDROCK_MODEL_ID', 'global.anthropic.claude-sonnet-4-6')
REGION = os.getenv('AWS_REGION', 'ap-northeast-2')
OUTPUT_TOKENS_PER_CONDITION = 300      # rough planning figure for the estimate only


def teammate():
    """The teammate's backend modules, imported without changing a file."""
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    return {'classifier': importlib.import_module('src.bedrock.condition_classifier'),
            'review': importlib.import_module('src.services.condition_review'),
            'schema': importlib.import_module('src.schemas.condition_review')}


def system_prompt(variant, mods=None):
    base = (mods or teammate())['classifier'].SYSTEM
    if variant == 'B':
        return base
    if variant == 'C':
        return base + '\n\n' + C_RULES.read_text(encoding='utf-8').strip()
    raise ValueError(f'unknown variant {variant}')


def jobs_of(gold, snapshot_path=SNAPSHOT):
    """Snapshot rows of the test postings in the shape the teammate's functions read."""
    rows = {f"jumpit-{r['source_id']}": r for r in json.loads(Path(snapshot_path).read_text(encoding='utf-8'))['postings']}
    return {job_id: {'source_id': str(rows[job_id]['source_id']), 'source_version': rows[job_id].get('source_version') or 1,
                     'qualifications': rows[job_id].get('qualifications') or '',
                     'preferred_requirements': rows[job_id].get('preferred_requirements') or ''}
            for job_id in gold['jobs']}


def plan(gold, snapshot_path=SNAPSHOT, mods=None):
    """How many calls each variant makes and roughly how many tokens — nothing is sent."""
    mods = mods or teammate()
    cls = mods['classifier'].ConditionClassifier
    schema = json.dumps(mods['schema'].ConditionReview.model_json_schema(), ensure_ascii=False)
    out = {}
    for variant in VARIANTS:
        prompt = system_prompt(variant, mods)
        calls = conditions = in_bytes = 0
        for job in jobs_of(gold, snapshot_path).values():
            for batch in cls.plan(job, 'bounded'):
                calls += 1
                conditions += len(batch)
                in_bytes += len((prompt + schema + json.dumps({'conditions': batch}, ensure_ascii=False)).encode('utf-8'))
        out[variant] = {'calls': calls, 'conditions': conditions,
                        'input_tokens_est': round(in_bytes / 3),          # utf-8 bytes / 3: rough for Korean + JSON
                        'output_tokens_est': conditions * OUTPUT_TOKENS_PER_CONDITION,
                        'system_prompt_sha256': hashlib.sha256(prompt.encode('utf-8')).hexdigest()[:16]}
    return out


def run(variant, gold, *, client=None, snapshot_path=SNAPSHOT, out_dir=RUNS, max_calls=None, mods=None, log=print):
    """Call the teammate's classifier batch by batch; cache each batch; record the teammate's own output check."""
    if not is_sealed(gold):
        raise SystemExit('정답이 봉인되지 않았습니다. 라벨링을 끝내고 봉인한 뒤에 실행합니다.')
    mods = mods or teammate()
    module = mods['classifier']
    base = module.SYSTEM
    module.SYSTEM = system_prompt(variant, mods)          # the one difference between B and C, in this process only
    os.environ['ENABLE_LIVE_BEDROCK'] = 'true'
    try:
        classifier = module.ConditionClassifier(MODEL, REGION, client=client)
        target = Path(out_dir) / variant
        target.mkdir(parents=True, exist_ok=True)
        made = 0
        for job_id, job in jobs_of(gold, snapshot_path).items():
            path = target / f'{job_id}.json'
            record = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {
                'job_id': job_id, 'variant': variant, 'model': MODEL, 'region': REGION,
                'system_prompt_sha256': hashlib.sha256(module.SYSTEM.encode('utf-8')).hexdigest()[:16], 'batches': {}}
            for batch in classifier.plan(job, 'bounded'):
                key = hashlib.sha256('|'.join(c['condition_id'] for c in batch).encode()).hexdigest()[:16]
                if record['batches'].get(key, {}).get('status') == 'ok':
                    continue
                if max_calls is not None and made >= max_calls:
                    log(f'호출 상한 {max_calls}회에 닿아 멈춤')
                    path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding='utf-8')
                    return made
                record['batches'][key] = call_batch(classifier, batch)
                made += 1
            conditions = [c for b in record['batches'].values() if b['status'] == 'ok' for c in b['conditions']]
            try:
                mods['review'].validate_review(job, {'conditions': conditions})
                record['validation'] = {'ok': True}
            except (ValueError, KeyError, TypeError) as exc:
                record['validation'] = {'ok': False, 'error': type(exc).__name__}
            path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding='utf-8')
            failed = sum(1 for b in record['batches'].values() if b['status'] != 'ok')
            log(f"{variant} {job_id}: 묶음 {len(record['batches'])} · 실패 {failed} · 팀원 검증 {'통과' if record['validation']['ok'] else '실패'}")
        return made
    finally:
        module.SYSTEM = base


def call_batch(classifier, batch, retries=3):
    """One call through the teammate's own _call_batch. Throttling is retried; a bad answer is recorded, not retried."""
    for attempt in range(retries + 1):
        try:
            value, usage = classifier._call_batch(batch)
            return {'status': 'ok', 'conditions': value['conditions'], 'usage': usage}
        except Exception as exc:                  # noqa: BLE001 — provider and format errors are both recorded
            throttled = 'Throttling' in type(exc).__name__ or 'Throttling' in str(exc)
            if throttled and attempt < retries:
                time.sleep(2 ** attempt * 2)
                continue
            return {'status': 'error', 'error': type(exc).__name__,
                    'validation_code': getattr(exc, 'validation_code', None), 'usage': getattr(exc, 'usage', None)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('command', choices=('plan', 'run'))
    ap.add_argument('--variant', choices=VARIANTS)
    ap.add_argument('--live', action='store_true', help='actually call Bedrock (needs the user\'s approval)')
    ap.add_argument('--max-calls', type=int)
    args = ap.parse_args(argv)
    gold = json.loads(GOLD.read_text(encoding='utf-8'))
    if args.command == 'plan':
        print(json.dumps({'model': MODEL, 'region': REGION, 'sealed': is_sealed(gold), **plan(gold)}, ensure_ascii=False, indent=1))
        return
    if not args.variant or not args.live:
        raise SystemExit('실행은 --variant B|C 와 --live 가 모두 있어야 합니다 (Bedrock 호출은 사용자 승인 후).')
    made = run(args.variant, gold, max_calls=args.max_calls)
    print(json.dumps({'variant': args.variant, 'calls_made': made}, ensure_ascii=False))


if __name__ == '__main__':
    main()
