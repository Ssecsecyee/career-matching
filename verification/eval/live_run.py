"""The teammate's live chatbot step — category labels for a selected posting (selected-question-v1) —
as is (B) and with the user's "what counts as a skill" rules added (C). Scored on category accuracy
against the sealed V3·V4 answer key.

    python -m eval.live_run plan                          # calls and token estimate — no call
    python -m eval.live_run run --variant B --repeat 3 --live
    python -m eval.live_run run --variant C2S --repeat 3 --live --mode adaptive
    python -m eval.live_run score [--mode adaptive]

The teammate's QuestionConditionReviewer (app/backend/src/bedrock/question_reviewer.py) is imported
read-only. --mode bounded calls it batch by batch (6 conditions). --mode adaptive follows the service
(services/selected_condition_review.py): one call for the whole posting, 6-condition batches only past
20 conditions or after a truncated answer, and any other failure leaves the posting without labels.
It labels category and treatment only — no skill names, no logic — so C adds just the category part
of eval/prompts/c_rules.md (the names/logic sections ask for output this step does not produce and
would contradict its "do not extract" instruction). C2S is the patch as measured on 2026-11-18
(docs/handoff/live-category-fix.measured-20261118.diff: C2 rules + short ids); C2G is the patch to hand over
(docs/handoff/live-category-fix.diff: the same plus a code guard that keeps a required line the model calls
"not a requirement" as a question). Each is applied to a temp copy of the teammate's file.
Batches are cached under data/real/jumpit/live_runs/.
"""
import argparse
import collections
import datetime as dt
import functools
import hashlib
import importlib
import importlib.util
import json
import os
import random
import shutil
import subprocess
import tempfile
from pathlib import Path

from eval.bc_run import BACKEND, C_RULES, MODEL, REGION, jobs_of, teammate
from eval.condition_gold import CATEGORIES, GOLD, SNAPSHOT, is_sealed

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / 'data' / 'real' / 'jumpit' / 'live_runs'
RULES_V2 = ROOT / 'eval' / 'prompts' / 'live_category_rules_v2.md'
PATCHES = {'C2S': ROOT / 'docs' / 'handoff' / 'live-category-fix.measured-20261118.diff',   # the runs saved on 11-18
           'C2G': ROOT / 'docs' / 'handoff' / 'live-category-fix.diff'}                     # + required-line guard (11-19)
PATCH = PATCHES['C2G']
PATCHED_FILE = 'app/backend/src/bedrock/question_reviewer.py'
VARIANTS = ('B', 'C', 'C2', 'C2S', 'C2G')
SHORT_IDS = set(PATCHES)        # the model sees c1, c2, ... and the teammate's code maps them back
MODES = ('bounded', 'adaptive')
MAX_CALLS, MAX_SECONDS = 5, 30  # SelectedConditionReview's budget per posting
SEED = 20261117
FRESH_SEED = 20261118
# What the user sees on the question card (career-matching services/condition_display.py): skill and other
# both read "직무 조건", so a skill/other mix-up changes nothing on screen.
DISPLAY = {'education': '학력', 'experience': '경력', 'skill': '직무 조건', 'certificate': '자격·면허',
           'attitude': '협업·업무 방식', 'other': '직무 조건'}
BASES = ('category', 'display')


def live_module():
    teammate()                                          # puts the teammate backend on sys.path
    return importlib.import_module('src.bedrock.question_reviewer')


@functools.lru_cache(maxsize=4)
def patched_module(variant='C2G'):
    """The teammate's question_reviewer with one of PATCHES applied — to a temp copy, never to their repo.
    Imports resolve to their backend as usual."""
    live_module()
    tmp = Path(tempfile.mkdtemp())
    try:
        target = tmp / PATCHED_FILE
        target.parent.mkdir(parents=True)
        shutil.copyfile(BACKEND / 'src' / 'bedrock' / 'question_reviewer.py', target)
        subprocess.run(['git', 'apply', f'--include={PATCHED_FILE}', str(PATCHES[variant])], cwd=tmp, check=True,
                       capture_output=True)
        spec = importlib.util.spec_from_file_location(f'src.bedrock.question_reviewer_{variant.lower()}', target)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def reviewer_module(variant):
    return patched_module(variant) if variant in SHORT_IDS else live_module()


def runs_dir(fresh=False, mode='bounded'):
    base = RUNS / 'fresh' if fresh else RUNS
    return base / 'adaptive' if mode == 'adaptive' else base


def category_rules():
    """The category part of the rule file: everything before the skill-names section."""
    text = C_RULES.read_text(encoding='utf-8')
    return text.split('\n## terms')[0].strip()


def system_prompt(variant, module=None):
    base = (module or live_module()).SYSTEM
    if variant == 'B':
        return base
    if variant == 'C':
        return base + '\n\n' + category_rules()
    if variant == 'C2':          # same category content, no "override the instructions above", output pairs spelled out
        return base + '\n\n' + RULES_V2.read_text(encoding='utf-8').strip()
    if variant in PATCHES:       # the patch carries the C2 rules in its own SYSTEM
        return patched_module(variant).SYSTEM
    raise ValueError(variant)


def fresh_jobs(gold, size=20, seed=FRESH_SEED, snapshot_path=SNAPSHOT):
    """Postings never used for the rules or the answer key, one per company and none from a test company.
    Only for checks that need no answer key: format failures and stability across runs."""
    from skillpath.sources.jumpit import CLEANED, SEEN, company_key, sample
    pool = json.loads(CLEANED.read_text(encoding='utf-8'))['postings']
    used = set(gold['jobs']) | set(json.loads(SEEN.read_text(encoding='utf-8')) if SEEN.exists() else [])
    test_companies = {company_key(p['company']) for p in pool if p['id'] in gold['jobs']}
    pool = [p for p in pool if company_key(p['company']) not in test_companies]
    drawn = sample(pool, n=size, seed=seed, exclude=used)
    return jobs_of({'jobs': {p['id']: None for p in drawn}}, snapshot_path)


PRICE_PER_MILLION = {'input': 3.0, 'output': 15.0}    # Sonnet list price in USD — for a cost estimate only


def teammate_commit():
    """The teammate checkout the run imported (read-only `git rev-parse`)."""
    try:
        out = subprocess.run(['git', '-C', str(BACKEND), 'rev-parse', '--short', 'HEAD'],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def file_sha(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]
    except OSError:
        return None


def client_config(client):
    """Timeouts and retries of the boto3 client actually used (None for a stand-in client)."""
    cfg = getattr(getattr(client, 'meta', None), 'config', None)
    if cfg is None:
        return None
    return {'connect_timeout': cfg.connect_timeout, 'read_timeout': cfg.read_timeout, 'retries': cfg.retries}


def estimated_cost(batches):
    usages = [b['usage'] for b in batches.values() if b.get('usage')]
    tokens = {k: sum(u.get(f'{k}_tokens') or 0 for u in usages) for k in PRICE_PER_MILLION}
    return round(sum(tokens[k] * PRICE_PER_MILLION[k] / 1e6 for k in tokens), 4)


class Recorder:
    """Passes calls through and keeps the last response, so a rejected answer is kept for diagnosis."""

    def __init__(self, inner):
        self.inner, self.last, self.calls = inner, None, 0

    def converse(self, **kw):
        self.calls += 1                                  # counted before the call: a timed-out call is still billed
        self.last = self.inner.converse(**kw)
        return self.last


class Tracked:
    """Wraps the reviewer's batch call: remembers the batch in flight and the labels that passed before a failure."""

    def __init__(self, reviewer):
        self.call, self.batch, self.passed = reviewer._call_batch, None, []
        reviewer._call_batch = self                     # classify() calls self._call_batch(batch)

    def reset(self):
        self.batch, self.passed = None, []

    def __call__(self, batch):
        self.batch = batch
        value, usage = self.call(batch)
        self.passed.extend(value['conditions'])
        return value, usage


def resolve_like_service(module, reviewer, job):
    """The model part of the teammate's SelectedConditionReview.resolve: one call for the whole posting,
    6-condition batches past 20 conditions, and a split only after a truncated answer. Any other failure
    raises — the service then sends every condition as a question (fallback_all_questions)."""
    try:
        review, usage = reviewer.classify(job, mode='adaptive', max_calls=MAX_CALLS, max_seconds=MAX_SECONDS)
    except module.ModelOutputTruncatedError as exc:
        bounded, adaptive = reviewer.plan(job, 'bounded'), reviewer.plan(job, 'adaptive')
        spent = getattr(exc, 'usage', {})
        used = spent.get('calls', 1)
        if len(adaptive) != 1 or len(bounded) <= 1 or used + len(bounded) > MAX_CALLS:
            raise
        review, usage = reviewer.classify(job, mode='bounded', max_calls=MAX_CALLS - used,
                                          max_seconds=max(0, MAX_SECONDS - spent.get('latency_ms', 0) / 1000))
        usage = dict(usage, calls=usage.get('calls', 0) + used, initial_truncated_attempt=spent)
    teammate()['review'].validated_envelope(job, review)     # the service checks the envelope before caching it
    return review, usage


def label_of(c):
    return {k: c[k] for k in ('condition_id', 'category', 'treatment', 'reason_code')}


def batch_key(batch):
    return hashlib.sha256('|'.join(c['condition_id'] for c in batch).encode()).hexdigest()[:16]


class Replay:
    """Stands in for Bedrock and returns a fixed tool answer, so the teammate's own checks can be rerun on it."""

    def __init__(self, tool_input):
        self.tool_input = tool_input

    def converse(self, **kw):
        return {'stopReason': 'tool_use', 'usage': {'inputTokens': 0, 'outputTokens': 0},
                'output': {'message': {'content': [{'toolUse': {'name': 'submit_question_labels', 'input': self.tool_input}}]}}}


def edits(a, b):
    """Characters changed, dropped or added to turn a into b (Levenshtein)."""
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, y in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (x != y))
    return row[-1]


def miscopied(got, want, limit=4):
    """Pairs each id the model wrote that is not in the batch with the batch id it was meant to be:
    the closest one left, if it differs by at most `limit` characters. None when the answer has another problem."""
    unknown = [g for g in got if g not in want]
    missing = [w for w in want if w not in got]
    if not unknown or len(unknown) != len(missing):
        return None
    pairs = {}
    for g in unknown:
        best = min(missing, key=lambda w: edits(g, w))
        if edits(g, best) > limit:
            return None
        pairs[g] = best
        missing.remove(best)
    return pairs


def diagnose(variant, gold, *, out_dir=RUNS, jobs=None, snapshot_path=SNAPSHOT):
    """For each rejected batch whose answer was kept: was a miscopied condition_id the only problem?
    Puts the intended ids back, changes nothing else, and reruns the teammate's own checks. No model call."""
    module = reviewer_module(variant)
    jobs = jobs if jobs is not None else jobs_of(gold, snapshot_path)
    rows, live = [], os.environ.get('ENABLE_LIVE_BEDROCK')
    os.environ['ENABLE_LIVE_BEDROCK'] = 'true'               # the check refuses to run otherwise; Replay makes no call
    try:
        for k in repeats_of(out_dir, variant):
            for job_id, job in jobs.items():
                path = Path(out_dir) / variant / f'r{k}' / f'{job_id}.json'
                if not path.exists():
                    continue
                cls = module.QuestionConditionReviewer
                planned = {batch_key(b): b for mode in MODES for b in cls.plan(job, mode)}
                for key, b in json.loads(path.read_text(encoding='utf-8'))['batches'].items():
                    if b['status'] == 'ok':
                        continue
                    answer = (b.get('rejected') or {}).get('tool_input')
                    row = {'run': k, 'job_id': job_id, 'error': b.get('error'), 'validation_code': b.get('validation_code'),
                           'answer_kept': answer is not None}
                    if answer and key in planned:
                        sent = planned[key]
                        want = [f'c{i}' for i in range(1, len(sent) + 1)] if variant in SHORT_IDS else [c['condition_id'] for c in sent]
                        got = [c.get('condition_id') for c in answer.get('conditions', [])]
                        pairs = miscopied(got, want)
                        row['miscopied_ids'] = len(pairs) if pairs else 0
                        row['passes_with_true_ids'] = False
                        if pairs:
                            fixed = {'conditions': [{**c, 'condition_id': pairs.get(c['condition_id'], c['condition_id'])}
                                                    for c in answer['conditions']]}
                            try:
                                value, _ = cls(MODEL, REGION, client=Replay(fixed))._call_batch(sent)
                                row['passes_with_true_ids'] = True
                                row['labels'] = {c['condition_id']: c['category']
                                                 for c in b.get('passed_before', []) + value['conditions']}
                            except Exception:   # noqa: BLE001 — another problem besides the ids
                                pass
                    rows.append(row)
    finally:
        if live is None:
            os.environ.pop('ENABLE_LIVE_BEDROCK', None)
        else:
            os.environ['ENABLE_LIVE_BEDROCK'] = live
    return rows


def if_ids_were_right(variant, gold, rows, *, out_dir=RUNS, snapshot_path=SNAPSHOT):
    """Accuracy and run-to-run agreement had the batches rejected only for miscopied ids been accepted.
    An estimate from the answers the model already gave, not a new run."""
    gc = gold_categories(gold, snapshot_path)
    repeats = repeats_of(out_dir, variant)
    preds = {k: {j: {cid: l['category'] for cid, l in predictions(Path(out_dir) / variant / f'r{k}' / f'{j}.json').items()}
                 for j in gc} for k in repeats}
    for r in rows:
        if r.get('passes_with_true_ids'):
            preds[r['run']][r['job_id']].update(r['labels'])
    total = sum(map(len, gc.values()))
    right = [sum(preds[k][j].get(cid) == cat for j in gc for cid, cat in gc[j].items()) for k in repeats]
    macro = [sum(sum(preds[k][j].get(cid) == cat for cid, cat in gc[j].items()) / len(gc[j]) for j in gc) / len(gc)
             for k in repeats]
    return {'accuracy_per_run': [round(r / total, 3) for r in right],
            'accuracy_mean': round(sum(right) / (total * len(repeats)), 3),
            'macro_accuracy_mean': round(sum(macro) / len(macro), 3),
            'unlabeled_conditions_per_run': [sum(cid not in preds[k][j] for j in gc for cid in gc[j]) for k in repeats],
            'same_answer_every_run': round(sum(len({preds[k][j].get(cid) for k in repeats}) == 1
                                               for j in gc for cid in gc[j]) / total, 3)}


def rejected_output(response):
    if not response:
        return None
    blocks = response.get('output', {}).get('message', {}).get('content', [])
    tools = [b['toolUse'].get('input') for b in blocks if 'toolUse' in b]
    return {'stop_reason': response.get('stopReason'), 'tool_input': tools[0] if tools else None}


def plan(gold, snapshot_path=SNAPSHOT, mode='bounded'):
    module = live_module()
    cls = module.QuestionConditionReviewer
    schema = json.dumps(module.QuestionLabels.model_json_schema(), ensure_ascii=False)
    out = {}
    for variant in VARIANTS:
        prompt = system_prompt(variant, module)
        calls = conds = size = 0
        for job in jobs_of(gold, snapshot_path).values():
            for batch in cls.plan(job, mode):
                calls += 1
                conds += len(batch)
                payload = [{k: x[k] for k in ('condition_id', 'requirement_type', 'quote')} for x in batch]
                size += len((prompt + schema + json.dumps(payload, ensure_ascii=False)).encode('utf-8'))
        out[variant] = {'calls_per_run': calls, 'conditions': conds, 'input_tokens_est': round(size / 3),
                        'output_tokens_est': conds * 90}
    return out


def run(variant, gold, repeat, *, client=None, jobs=None, snapshot_path=SNAPSHOT, out_dir=RUNS, log=print,
        mode='bounded'):
    """Returns the number of model calls made. A finished batch (or, in adaptive mode, posting) is not called again."""
    if not is_sealed(gold):
        raise SystemExit('정답이 봉인되지 않았습니다.')
    if mode not in MODES:
        raise ValueError(mode)
    module = reviewer_module(variant)
    base = module.SYSTEM
    module.SYSTEM = system_prompt(variant, module)
    os.environ['ENABLE_LIVE_BEDROCK'] = 'true'
    try:
        recorder = Recorder(client or module.question_runtime_client(REGION))   # the service's own client settings
        reviewer = module.QuestionConditionReviewer(MODEL, REGION, client=recorder)
        tracked = Tracked(reviewer)
        target = Path(out_dir) / variant / f'r{repeat}'
        target.mkdir(parents=True, exist_ok=True)
        # Run record fields asked for by the external review (§15.3); older records simply lack them.
        provenance = {'teammate_commit': teammate_commit(), 'snapshot_sha256': file_sha(snapshot_path),
                      'answer_key_sha256': ((gold.get('sealed') or {}).get('labels_sha256') or '')[:12] or None,
                      'inference_config': client_config(getattr(recorder, 'inner', None))}
        # The cache key is not read here: the patch moves it together with prompt_version (recorded above).
        for job_id, job in (jobs if jobs is not None else jobs_of(gold, snapshot_path)).items():
            path = target / f'{job_id}.json'
            record = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {
                'job_id': job_id, 'variant': variant, 'repeat': repeat, 'model': MODEL, 'mode': mode,
                'prompt_version': reviewer.prompt_version,
                'system_prompt_sha256': hashlib.sha256(module.SYSTEM.encode('utf-8')).hexdigest()[:16],
                'started_at': dt.datetime.now().isoformat(timespec='seconds'), **provenance, 'batches': {}}
            if mode == 'adaptive':
                if not any(b['status'] == 'ok' for b in record['batches'].values()):
                    recorder.last = None
                    tracked.reset()
                    try:
                        review, usage = resolve_like_service(module, reviewer, job)
                        record['batches'] = {'posting': {'status': 'ok', 'labels': [label_of(c) for c in review['conditions']],
                                                         'usage': usage}}
                    except Exception as exc:    # noqa: BLE001 — the whole posting falls back to questions
                        key = batch_key(tracked.batch) if tracked.batch else 'posting'
                        record['batches'] = {key: {'status': 'error', 'error': type(exc).__name__,
                                                   'validation_code': getattr(exc, 'validation_code', None),
                                                   'rejected': rejected_output(recorder.last),
                                                   'passed_before': [label_of(c) for c in tracked.passed],
                                                   'usage': getattr(exc, 'usage', None)}}
            else:
                for batch in reviewer.plan(job, 'bounded'):
                    key = batch_key(batch)
                    if record['batches'].get(key, {}).get('status') == 'ok':
                        continue
                    recorder.last = None
                    try:
                        value, usage = tracked(batch)
                        record['batches'][key] = {'status': 'ok', 'labels': [label_of(c) for c in value['conditions']],
                                                  'usage': usage}
                    except Exception as exc:    # noqa: BLE001 — recorded, not retried (the service does not retry)
                        record['batches'][key] = {'status': 'error', 'error': type(exc).__name__,
                                                  'validation_code': getattr(exc, 'validation_code', None),
                                                  'rejected': rejected_output(recorder.last)}
            record['finished_at'] = dt.datetime.now().isoformat(timespec='seconds')
            record['estimated_cost_usd'] = estimated_cost(record['batches'])      # successful calls only
            path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding='utf-8')
            bad = sum(1 for b in record['batches'].values() if b['status'] != 'ok')
            log(f'{variant} {mode} r{repeat} {job_id}: 묶음 {len(record["batches"])} · 실패 {bad}')
        return recorder.calls
    finally:
        module.SYSTEM = base


def gold_categories(gold, snapshot_path=SNAPSHOT):
    mods = teammate()
    out = {}
    for job_id, job in jobs_of(gold, snapshot_path).items():
        keyed = {c['key']: c for c in mods['review'].source_conditions(job)}
        out[job_id] = {mods['review'].review_key(keyed[c['key']]): gold['labels'][c['key']]['category']
                       for c in gold['jobs'][job_id]['conditions']}
    return out


def predictions(path):
    if not path.exists():
        return {}
    r = json.loads(path.read_text(encoding='utf-8'))
    return {l['condition_id']: l for b in r['batches'].values() if b['status'] == 'ok' for l in b['labels']}


def score(gold, out_dir=RUNS, snapshot_path=SNAPSHOT, allow_unsealed=False, basis='category'):
    """Category accuracy per variant (a failed batch counts as wrong, as the service gets no label).
    basis 'display' scores the label the user sees instead (DISPLAY), for answer and prediction alike."""
    if not allow_unsealed and not is_sealed(gold):
        raise SystemExit('정답이 봉인되지 않았습니다.')
    if basis not in BASES:
        raise ValueError(f'basis must be one of {BASES}')
    seen = DISPLAY if basis == 'display' else {c: c for c in DISPLAY}
    gc = {j: {cid: seen.get(cat, cat) for cid, cat in cats.items()}
          for j, cats in gold_categories(gold, snapshot_path).items()}
    jobs = list(gc)
    report, per = {}, {}
    for variant in VARIANTS:
        repeats = repeats_of(out_dir, variant)
        if not repeats and variant != 'B':
            continue
        preds = {k: {j: {cid: {**l, 'category': seen.get(l.get('category'), l.get('category'))}
                         for cid, l in predictions(Path(out_dir) / variant / f'r{k}' / f'{j}.json').items()}
                     for j in jobs} for k in repeats}
        per[variant] = [[sum(preds[k][j].get(cid, {}).get('category') == cat for cid, cat in gc[j].items()) / len(gc[j])
                         for j in jobs] for k in repeats]
        right = [sum(preds[k][j].get(cid, {}).get('category') == cat for j in jobs for cid, cat in gc[j].items()) for k in repeats]
        total = sum(len(gc[j]) for j in jobs)
        missing = [sum(cid not in preds[k][j] for j in jobs for cid in gc[j]) for k in repeats]
        stable = sum(1 for j in jobs for cid in gc[j]
                     if len({preds[k][j].get(cid, {}).get('category') for k in repeats}) == 1) if repeats else 0
        confusion = collections.Counter((cat, preds[repeats[0]][j].get(cid, {}).get('category', '없음'))
                                        for j in jobs for cid, cat in gc[j].items()) if repeats else {}
        report[variant] = {
            'repeats': len(repeats), 'conditions': total,
            'accuracy_per_run': [round(r / total, 3) for r in right],
            'accuracy_mean': round(sum(right) / (total * len(repeats)), 3) if repeats else None,
            'macro_accuracy_mean': round(sum(sum(x) / len(x) for x in per[variant]) / len(repeats), 3) if repeats else None,
            'missing_labels_per_run': missing,
            'same_answer_every_run': round(stable / total, 3) if repeats else None,
            **stability(out_dir, variant, {j: list(gc[j]) for j in jobs}),
            'confusion_first_run': {f'{CATEGORIES.get(g, g)}→{CATEGORIES.get(p, p)}': n
                                    for (g, p), n in sorted(confusion.items(), key=lambda x: -x[1])}}
    for variant in VARIANTS[1:]:
        if variant not in report or not report['B']['repeats']:
            continue
        b = [sum(x) / len(x) for x in zip(*per['B'])]          # per-posting accuracy, averaged over runs
        c = [sum(x) / len(x) for x in zip(*per[variant])]
        rng = random.Random(SEED)
        diffs = []
        for _ in range(4000):
            draw = [rng.randrange(len(jobs)) for _ in jobs]
            diffs.append(sum(c[i] - b[i] for i in draw) / len(draw))
        diffs.sort()
        report[f'{variant}_minus_B_macro'] = {'diff': round(sum(c) / len(c) - sum(b) / len(b), 3),
                                              'ci95': [round(diffs[100], 3), round(diffs[3899], 3)]}
    return report


def class_scores(gold, out_dir=RUNS, snapshot_path=SNAPSHOT, basis='category', allow_unsealed=False):
    """Precision, recall and F1 per answer class, pooled over every saved run (a line run 3 times counts 3 times).
    A missing label counts against recall only. Macro F1 averages the classes the answer key uses; a class the
    model never predicts gets precision None and F1 0 (zero_division=0)."""
    if not allow_unsealed and not is_sealed(gold):
        raise SystemExit('정답이 봉인되지 않았습니다.')
    seen = DISPLAY if basis == 'display' else {c: c for c in DISPLAY}
    gc = {j: {cid: seen.get(cat, cat) for cid, cat in cats.items()}
          for j, cats in gold_categories(gold, snapshot_path).items()}
    classes = sorted({c for cats in gc.values() for c in cats.values()})
    out = {}
    for variant in VARIANTS:
        repeats = repeats_of(out_dir, variant)
        if not repeats:
            continue
        pairs = []
        for k in repeats:
            for j, cats in gc.items():
                preds = predictions(Path(out_dir) / variant / f'r{k}' / f'{j}.json')
                pairs += [(cat, seen.get(preds.get(cid, {}).get('category'), preds.get(cid, {}).get('category')))
                          for cid, cat in cats.items()]
        per = {}
        for c in classes:
            tp = sum(g == c and p == c for g, p in pairs)
            fp = sum(g != c and p == c for g, p in pairs)
            fn = sum(g == c and p != c for g, p in pairs)
            prec = tp / (tp + fp) if tp + fp else None
            rec = tp / (tp + fn) if tp + fn else None
            f1 = 2 * prec * rec / (prec + rec) if prec and rec else 0.0
            per[CATEGORIES.get(c, c)] = {'support_per_run': (tp + fn) // len(repeats),
                                         'precision': None if prec is None else round(prec, 3),
                                         'recall': None if rec is None else round(rec, 3), 'f1': round(f1, 3)}
        out[variant] = {'repeats': len(repeats), 'macro_f1': round(sum(v['f1'] for v in per.values()) / len(per), 3),
                        'classes': per}
    return out


def repeats_of(out_dir, variant):
    return sorted(int(p.name[1:]) for p in (Path(out_dir) / variant).glob('r*') if p.is_dir())


def stability(out_dir, variant, conditions):
    """Format failures and run-to-run agreement — no answer key needed.
    conditions: {job_id: [condition_id, ...]}. A condition in a failed batch has no label in that run."""
    repeats = repeats_of(out_dir, variant)
    preds = {k: {j: predictions(Path(out_dir) / variant / f'r{k}' / f'{j}.json') for j in conditions} for k in repeats}
    failed_batches, kinds = [], collections.Counter()
    for k in repeats:
        n = 0
        for j in conditions:
            path = Path(out_dir) / variant / f'r{k}' / f'{j}.json'
            if path.exists():
                bad = [b for b in json.loads(path.read_text(encoding='utf-8'))['batches'].values() if b['status'] != 'ok']
                n += len(bad)
                kinds.update(f"{b.get('error')}/{b.get('validation_code')}" for b in bad)   # format vs throttle/timeout
        failed_batches.append(n)
    answers = [[preds[k][j].get(cid, {}).get('category') for k in repeats] for j in conditions for cid in conditions[j]]
    complete = [a for a in answers if None not in a]
    return {'failed_batches_per_run': failed_batches, 'failure_kinds': dict(kinds),
            'unlabeled_conditions_per_run': [sum(a[i] is None for a in answers) for i in range(len(repeats))],
            'same_answer_when_labeled': round(sum(len(set(a)) == 1 for a in complete) / len(complete), 3) if complete else None,
            'labeled_every_run': len(complete)}


def score_fresh(jobs, out_dir=RUNS / 'fresh'):
    """Fresh postings have no answer key: report format failures and stability only."""
    cls = live_module().QuestionConditionReviewer
    conditions = {j: [c['condition_id'] for b in cls.plan(job, 'bounded') for c in b] for j, job in jobs.items()}
    out = {'postings': len(jobs), 'conditions': sum(map(len, conditions.values()))}
    for variant in VARIANTS:
        repeats = repeats_of(out_dir, variant)
        if repeats:
            answers = [[predictions(Path(out_dir) / variant / f'r{k}' / f'{j}.json').get(cid, {}).get('category')
                        for k in repeats] for j in conditions for cid in conditions[j]]
            out[variant] = {'repeats': len(repeats),
                            'same_answer_every_run': round(sum(len(set(a)) == 1 for a in answers) / len(answers), 3),
                            **stability(out_dir, variant, conditions)}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('command', choices=('plan', 'run', 'score', 'diagnose'))
    ap.add_argument('--variant', choices=VARIANTS)
    ap.add_argument('--repeat', type=int, default=1)
    ap.add_argument('--live', action='store_true')
    ap.add_argument('--set', choices=('test', 'fresh'), default='test',
                    help='test = 봉인 정답 20건 · fresh = 정답 없는 새 공고 20건(형식 실패·일관성만)')
    ap.add_argument('--mode', choices=MODES, default='bounded',
                    help='bounded = 6개씩 · adaptive = 서비스처럼 공고 하나를 한 번에 (결과는 adaptive/ 아래)')
    args = ap.parse_args(argv)
    gold = json.loads(GOLD.read_text(encoding='utf-8'))
    fresh = fresh_jobs(gold) if args.set == 'fresh' else None
    out = runs_dir(fresh is not None, args.mode)
    if args.command == 'plan':
        cls = live_module().QuestionConditionReviewer
        target = fresh if fresh is not None else jobs_of(gold)
        calls = sum(len(cls.plan(job, args.mode)) for job in target.values())
        print(json.dumps({'set': args.set, 'mode': args.mode, 'postings': len(target), 'calls_per_run': calls,
                          'per_variant': plan(gold, mode=args.mode) if fresh is None else None}, ensure_ascii=False, indent=1))
    elif args.command == 'run':
        if not args.variant or not args.live:
            raise SystemExit('--variant 와 --live 가 필요합니다 (Bedrock 호출).')
        made = sum(run(args.variant, gold, k, jobs=fresh, out_dir=out, mode=args.mode) for k in range(1, args.repeat + 1))
        print(json.dumps({'set': args.set, 'mode': args.mode, 'variant': args.variant, 'repeats': args.repeat,
                          'calls_made': made}))
    elif args.command == 'diagnose':
        variant = args.variant or 'C2'
        rows = diagnose(variant, gold, out_dir=out, jobs=fresh)
        report = {'set': args.set, 'mode': args.mode, 'variant': variant, 'rejected_batches': len(rows),
                  'answer_kept': sum(r['answer_kept'] for r in rows),
                  'only_miscopied_ids': sum(bool(r.get('passes_with_true_ids')) for r in rows),
                  'errors': dict(collections.Counter(f"{r['error']}/{r['validation_code']}" for r in rows)),
                  'batches': [{k: v for k, v in r.items() if k != 'labels'} for r in rows]}
        if fresh is None and rows:
            report['if_ids_were_right'] = if_ids_were_right(variant, gold, rows, out_dir=out)
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        report = score_fresh(fresh, out_dir=out) if fresh is not None else score(gold, out_dir=out)
        out.mkdir(parents=True, exist_ok=True)
        (out / 'score.json').write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
