"""V8 — regression check with no model call: rescore every saved run and compare with the saved score.

    python -m eval.regress

A scorer or answer-key change that moves a published number shows up here before it reaches a document.
Saved runs live under data/real (not in git) and the scorers import the teammate's repo read-only;
where either is missing the check is reported as skipped, not passed.
"""
import json
import sys
from pathlib import Path

from eval.condition_gold import GOLD, PARSER_FILE, is_sealed

ROOT = Path(__file__).resolve().parents[1]
JUMPIT = ROOT / 'data' / 'real' / 'jumpit'


def differences(new, saved, path=''):
    """Paths where two score reports differ. Tuples and lists count as the same (JSON has no tuple)."""
    new, saved = json.loads(json.dumps(new)), json.loads(json.dumps(saved))
    if isinstance(new, dict) and isinstance(saved, dict):
        out = []
        for key in sorted(set(new) | set(saved)):
            if key not in new or key not in saved:
                out.append(f'{path}/{key} (한쪽에만 있음)')
            else:
                out.extend(differences(new[key], saved[key], f'{path}/{key}'))
        return out
    return [] if new == saved else [f'{path}: 저장 {saved!r} → 지금 {new!r}']


def checks(gold):
    """(name, saved score file, function that rescoring it) — imported lazily: they load the teammate's code."""
    import eval.bc_score as bc
    import eval.holdout as holdout
    import eval.live_run as live
    import eval.v7_questions as v7
    runs = JUMPIT / 'live_runs'

    def holdout_score(mode='bounded'):
        key = json.loads(holdout.HOLDOUT.read_text(encoding='utf-8'))
        if not is_sealed(key):                      # a changed key must not pass as "same"
            return {'sealed_sha256': '봉인 깨짐'}
        return holdout.full_report(key, mode)

    return [
        ('V3·V4 배치', JUMPIT / 'bc_runs' / 'score.json', lambda: bc.score(gold)),
        ('V3 실시간 6개씩', runs / 'score.json', lambda: live.score(gold)),
        ('V3 실시간 서비스 방식', runs / 'adaptive' / 'score.json', lambda: live.score(gold, out_dir=runs / 'adaptive')),
        ('V3 새 공고', runs / 'fresh' / 'score.json', lambda: live.score_fresh(live.fresh_jobs(gold))),
        ('V3-H 새 공고 정답', holdout.SCORES['bounded'], holdout_score),
        ('V3-H 새 공고 서비스 방식', holdout.SCORES['adaptive'], lambda: holdout_score('adaptive')),
        ('V7 상담 답변', JUMPIT / 'v7_runs' / 'score.json', lambda: v7.score(gold)),
    ]


def run(gold_path=GOLD, parser_file=PARSER_FILE, plan=checks):
    if not Path(gold_path).exists() or not Path(parser_file).exists():
        return [{'name': '전체', 'status': 'skipped', 'why': '정답 파일 또는 팀원 저장소가 없음'}]
    gold = json.loads(Path(gold_path).read_text(encoding='utf-8'))
    rows = [{'name': '정답 봉인', 'status': 'same' if is_sealed(gold) else 'changed',
             'differences': [] if is_sealed(gold) else ['봉인 해시와 라벨이 다름']}]
    for name, saved, rescore in plan(gold):
        if not Path(saved).exists():
            rows.append({'name': name, 'status': 'skipped', 'why': f'저장된 점수 없음: {Path(saved).name}'})
            continue
        diff = differences(rescore(), json.loads(Path(saved).read_text(encoding='utf-8')))
        rows.append({'name': name, 'status': 'changed' if diff else 'same', 'differences': diff[:20]})
    return rows


def main(argv=None):
    rows = run()
    for r in rows:
        mark = {'same': '같음', 'changed': '달라짐', 'skipped': '건너뜀'}[r['status']]
        print(f"{mark}  {r['name']}" + (f" — {r['why']}" if r.get('why') else ''))
        for d in r.get('differences', []):
            print(f'      {d}')
    if any(r['status'] == 'changed' for r in rows):
        sys.exit(1)


if __name__ == '__main__':
    main()
