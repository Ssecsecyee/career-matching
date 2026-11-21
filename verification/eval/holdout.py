"""V3-H — an independent answer key for the 20 postings the rules never saw.

    python -m eval.holdout draw      # eval/gold.holdout.json, blank — once
    python -m eval.holdout status
    python -m eval.holdout seal
    python -m eval.holdout score     # B vs C2 on the answers already saved (6 per call) — no model call;
                                     # the label the user sees first (primary), the raw category second

The postings are the ones eval.live_run already ran as its "fresh" set: one per company, no company of the
first test set, none shown in discussion. Their B and C2 answers were saved before anyone looked at accuracy,
so labelling them blind gives a test the rules were not tuned on. Label on the same screen as the first set:

    CG_GOLD=eval/gold.holdout.json python -m streamlit run label_conditions.py --server.port 8505

The first answer key (eval/gold.conditions.json) is read to find the postings and is never written.
"""
import argparse
import collections
import json
from pathlib import Path

from eval.condition_gold import GOLD, conditions_of, is_sealed, load_parser, progress, seal, snapshot_rows
from eval.live_run import FRESH_SEED, RUNS, class_scores, fresh_jobs, score

ROOT = Path(__file__).resolve().parents[1]
HOLDOUT = ROOT / 'eval' / 'gold.holdout.json'
SCORE = RUNS / 'fresh' / 'holdout_score.json'         # git-excluded, next to the runs it scores
RUN_DIRS = {'bounded': RUNS / 'fresh', 'adaptive': RUNS / 'fresh' / 'adaptive'}   # 6 per call / the service's way
SCORES = {mode: d / 'holdout_score.json' for mode, d in RUN_DIRS.items()}


def draw(first, rows=None, snap=None, job_ids=None, parser=None):
    """Blank answer key for the unseen postings, in the same shape as the first one."""
    if rows is None:
        rows, snap = snapshot_rows()
    job_ids = list(job_ids if job_ids is not None else fresh_jobs(first))
    parser, parser_sha = parser or load_parser()
    jobs = {}
    for job_id in job_ids:
        row = rows[job_id]
        jobs[job_id] = {'source_version': row.get('source_version') or 1, 'url': row.get('source_url'),
                        'conditions': [{'id': c['id'], 'key': c['key'], 'type': c['type'],
                                        'spans': [[s['start'], s['end'], s['kind']] for s in c['source_spans']],
                                        'parse_notes': c['parse_notes']} for c in conditions_of(row, parser)]}
    return {
        '_comment': 'V3-H 독립 시험 정답(블라인드). 규칙을 만들 때 한 번도 쓰지 않은 공고다. 사람이 원문만 보고 '
                    '조건마다 범주·기술 이름·관계를 적는다. 원문은 넣지 않는다(위치만). 봉인 뒤에는 이 공고의 결과를 보고 '
                    '규칙·패치를 고치지 않는다(고치면 개발용으로 바뀐다).',
        'status': 'blank', 'labeled_by': 'pending',
        'guideline': 'docs/eval/labeling-guide.md (V3·V4 시험 정답과 같은 기준)',
        'parser': {'file': 'career-matching/app/backend/src/services/condition_structure.py',
                   'version': parser.PARSER_VERSION, 'sha256': parser_sha},
        'snapshot': {'at': (snap or {}).get('snapshot_at'), 'sha256': ((snap or {}).get('sha256') or '')[:16]},
        'sample': {'seed': FRESH_SEED, 'size': len(jobs),
                   'pool': 'jumpit backend after cleaning, one per company, no company of the first test set, '
                           'none shown in discussion — the postings of data/real/jumpit/live_runs/fresh',
                   'model_answers_saved_before_labelling': True},
        'jobs': jobs, 'labels': {}, 'sealed': None,
    }


def report(gold, out_dir=RUNS / 'fresh'):
    """Primary basis fixed before scoring (rule-log 2026-11-19): the label the user sees. Category is secondary."""
    return {'sealed_sha256': gold['sealed']['labels_sha256'][:12] if gold.get('sealed') else None,
            **{basis: score(gold, out_dir=out_dir, basis=basis) for basis in ('display', 'category')}}  # sealed only


def full_report(gold, mode='bounded'):
    """What `score` saves: the accuracy report, plus failures/latency/tokens for the service-mode runs."""
    out = report(gold, out_dir=RUN_DIRS[mode])
    if mode == 'adaptive':
        out['service'] = service_stats(RUN_DIRS[mode])
    return out


def service_stats(out_dir):
    """Per variant, from the saved service-mode records: postings that fell back to "ask everything", postings
    split after a truncated answer, model calls, tokens and the posting's latency. No answer key needed."""
    out = {}
    for variant_dir in sorted(p for p in Path(out_dir).iterdir() if p.is_dir()):
        recs = [json.loads(f.read_text(encoding='utf-8')) for f in sorted(variant_dir.glob('r*/*.json'))]
        if not recs:
            continue
        ok = [b for r in recs for b in r['batches'].values() if b['status'] == 'ok']
        lat = sorted(b['usage']['latency_ms'] for b in ok if (b.get('usage') or {}).get('latency_ms') is not None)
        parts = [x for b in ok for x in (b.get('usage') or {}).get('batches', [])]

        def pct(q):
            return round(lat[min(len(lat) - 1, int(q * len(lat)))] / 1000, 1) if lat else None
        out[variant_dir.name] = {
            'postings_run': len(recs),
            'fell_back_to_all_questions': sum(1 for r in recs if not any(b['status'] == 'ok' for b in r['batches'].values())),
            'failure_kinds': dict(collections.Counter(f"{b.get('error')}/{b.get('validation_code')}" for r in recs
                                                      for b in r['batches'].values() if b['status'] != 'ok')),
            'split_after_truncation': sum(1 for b in ok if (b.get('usage') or {}).get('calls', 1) > 1),
            'model_calls_ok': sum((b.get('usage') or {}).get('calls', 1) for b in ok),
            'input_tokens': sum(x.get('input_tokens') or 0 for x in parts),
            'output_tokens': sum(x.get('output_tokens') or 0 for x in parts),
            'latency_s': {'p50': pct(0.5), 'p95': pct(0.95), 'max': round(lat[-1] / 1000, 1) if lat else None}}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('command', choices=('draw', 'status', 'seal', 'score', 'classes'))
    ap.add_argument('--mode', choices=tuple(RUN_DIRS), default='bounded',
                    help='score: bounded = 6개씩 저장된 답, adaptive = 서비스 방식 B 대 최종 패치(C2G)')
    args = ap.parse_args(argv)
    if args.command == 'draw':
        if HOLDOUT.exists():
            raise SystemExit(f'{HOLDOUT.name}이 이미 있습니다. 시험지는 한 번만 뽑습니다.')
        gold = draw(json.loads(GOLD.read_text(encoding='utf-8')))
        HOLDOUT.write_text(json.dumps(gold, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        print(json.dumps(progress(gold), ensure_ascii=False))
        return
    gold = json.loads(HOLDOUT.read_text(encoding='utf-8'))
    if args.command == 'status':
        print(json.dumps(progress(gold), ensure_ascii=False))
    elif args.command == 'seal':
        if is_sealed(gold):
            raise SystemExit('이미 봉인됐습니다.')
        HOLDOUT.write_text(json.dumps(seal(gold), ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        print(json.dumps(progress(gold), ensure_ascii=False))
    elif args.command == 'classes':
        # Per-class P/R/F1 and macro F1 (report §6.5), added after the primary result was seen. The first test
        # set is shown next to it with the same function so the two are reported side by side, not merged.
        first = json.loads(GOLD.read_text(encoding='utf-8'))
        out = {basis: {'holdout_bounded': class_scores(gold, out_dir=RUN_DIRS['bounded'], basis=basis),
                       'holdout_adaptive': class_scores(gold, out_dir=RUN_DIRS['adaptive'], basis=basis)
                       if RUN_DIRS['adaptive'].exists() else None,
                       'test_bounded': class_scores(first, out_dir=RUNS, basis=basis),
                       'test_adaptive': class_scores(first, out_dir=RUNS / 'adaptive', basis=basis)}
               for basis in ('display', 'category')}
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        out = full_report(gold, args.mode)
        SCORES[args.mode].write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
