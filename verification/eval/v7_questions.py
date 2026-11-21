"""V7 — everyday questions to the teammate's chatbot about a selected posting.

    python -m eval.v7_questions plan                 # calls and token estimate — no call
    python -m eval.v7_questions run --live           # 20 postings x 3 questions, variants B / T / C
    python -m eval.v7_questions score

The teammate's own dialogue code runs unchanged (DialogueFlow + ContextRouter, read-only import),
with an in-memory posting store and a fixed question generator in place of MySQL and the questioner,
as the teammate's own tests do. The router call (context-intent-v7), the selected-posting condition
labels (selected-question-v1) and the answer (consultation-text-v1 / context-response-v1) are real
Bedrock calls. Each question is routed once and the same route is answered three ways:

  B  the chatbot as it is
  T  the answer model also gets the posting's qualifications and preferred_requirements text
  C  T + eval/prompts/answer_rules.md in the answer system prompt (the user's rules for this step)

so T − B is what passing the requirement text does and C − T is what the rules add.
Answers are scored against the sealed V3·V4 answer key: the skill names a person wrote for the
required / preferred sections, and the years written in experience lines.
"""
import argparse
import contextlib
import copy
import json
import os
import random
import re
from pathlib import Path

from eval.bc_run import MODEL, REGION, teammate
from eval.condition_gold import GOLD, SNAPSHOT, conditions_of, is_sealed, load_parser, parse_terms

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / 'data' / 'real' / 'jumpit' / 'v7_runs'
ANSWER_RULES = ROOT / 'eval' / 'prompts' / 'answer_rules.md'
SKILLS = ROOT / 'data' / 'skills.json'
QUESTIONS = {'required': '이 공고에서 필수로 요구하는 기술 스택이 뭐야?',
             'preferred': '이 공고에서 우대하는 기술이나 조건은 뭐가 있어?',
             'experience': '이 공고는 경력이 몇 년 필요해?'}
VARIANTS = ('B', 'T', 'C')
ANSWER_SYSTEMS = ('한국어 커리어 상담입니다', '한국어 커리어 도우미로')
SEED = 20261117


# ---- stand-ins for the teammate's storage and questioner (as in their tests) -------------------------

class Jobs:
    def __init__(self, job):
        self.job = job

    def search(self, plan, exclude_ids=()):
        return 1, [copy.deepcopy(self.job)]

    def get(self, source_id):
        return copy.deepcopy(self.job) if str(source_id) == self.job['source_id'] else None


class Questioner:
    model_id, region = 'fixed-question', 'local'

    def question(self, condition, profile):
        return {'question': '원문의 조건에 해당하시나요?', 'quote': condition['quote']}, {}


class LabelCache:
    """In-memory stand-in for job_condition_question_cache: one selected-question-v1 call per posting."""

    def __init__(self):
        self.saved = {}

    def get(self, job):
        return self.saved.get((job['source_id'], job['source_version']))

    @contextlib.contextmanager
    def claim(self, job):
        yield True

    def save(self, job, review, usage):
        self.saved[(job['source_id'], job['source_version'])] = review
        return review


class AnswerRulesClient:
    """Passes calls to the real Bedrock client; adds the rules only to the two answer prompts."""

    def __init__(self, real, extra=None):
        self.real, self.extra = real, extra

    def _with_rules(self, kw):
        system = kw.get('system') or []
        if self.extra and system and system[0].get('text', '').startswith(ANSWER_SYSTEMS):
            kw = dict(kw, system=[{'text': system[0]['text'] + '\n\n' + self.extra}])
        return kw

    def converse(self, **kw):
        return self.real.converse(**self._with_rules(kw))

    def converse_stream(self, **kw):
        return self.real.converse_stream(**self._with_rules(kw))


def make_job(row):
    """A posting row as the teammate's MySQL repository returns it, kept selectable for the test."""
    return {'job_id': row.get('job_id') or int(row['source_id']), 'source_id': str(row['source_id']),
            'source_url': row.get('source_url'), 'source_version': row.get('source_version') or 1,
            'title': row.get('title') or '', 'company_name': row.get('company_name') or '',
            'qualifications': row.get('qualifications') or '', 'preferred_requirements': row.get('preferred_requirements') or '',
            'responsibilities': row.get('responsibilities') or '', 'tech_stacks': row.get('tech_stacks') or [],
            # The snapshot postings have closed since 11/08; the test keeps them selectable.
            'recruitment_status': 'unknown', 'deadline_at': None, 'deadline_type': None}


@contextlib.contextmanager
def requirement_text_passed():
    """Variant T/C: the answer model's history also carries the posting's two requirement sections."""
    mods = [__import__(name, fromlist=['x']) for name in
            ('src.services.memory', 'src.services.context_router', 'src.services.consultation')]
    original = mods[0].consultation_context

    def with_requirements(state):
        result = original(state)
        selected = state.get('selected') or {}
        if selected:
            result['selected_job'] = dict(result['selected_job'], qualifications=selected.get('qualifications'),
                                          preferred_requirements=selected.get('preferred_requirements'))
        return result
    for m in mods:
        if hasattr(m, 'consultation_context'):
            m.consultation_context = with_requirements
    try:
        yield
    finally:
        for m in mods:
            if hasattr(m, 'consultation_context'):
                m.consultation_context = original


# ---- the run ---------------------------------------------------------------------------------------

def run(gold, *, client=None, snapshot_path=SNAPSHOT, out_dir=RUNS, log=print, limit=None):
    if not is_sealed(gold):
        raise SystemExit('정답이 봉인되지 않았습니다.')
    teammate()
    os.environ['ENABLE_LIVE_BEDROCK'] = 'true'
    from src.bedrock.client import BedrockPlanner, runtime_client
    from src.bedrock.question_reviewer import QuestionConditionReviewer
    from src.schemas.intent import IntentDecision
    from src.services.context_router import ContextRouter
    from src.services.dialogue import DialogueFlow
    from src.services.intent_context import routing_context
    from src.services.selected_condition_review import SelectedConditionReview

    real = client or runtime_client(REGION)
    planners = {'B': BedrockPlanner(MODEL, REGION, client=AnswerRulesClient(real)),
                'T': BedrockPlanner(MODEL, REGION, client=AnswerRulesClient(real)),
                'C': BedrockPlanner(MODEL, REGION, client=AnswerRulesClient(real, ANSWER_RULES.read_text(encoding='utf-8')))}
    reviewer = QuestionConditionReviewer(MODEL, REGION, client=real)
    cache = LabelCache()
    rows = {f"jumpit-{r['source_id']}": r for r in json.loads(Path(snapshot_path).read_text(encoding='utf-8'))['postings']}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    made = 0
    for job_id in list(gold['jobs'])[:limit]:
        path = out_dir / f'{job_id}.json'
        record = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'job_id': job_id, 'model': MODEL, 'answers': {}}
        if all(q in record['answers'] and all(v in record['answers'][q].get('variants', {}) for v in VARIANTS) for q in QUESTIONS):
            continue
        usage = []

        def invoke(purpose, function, *args):
            result, used = function(*args)
            usage.append({'purpose': purpose, 'input_tokens': (used or {}).get('input_tokens'),
                          'output_tokens': (used or {}).get('output_tokens')})
            return result

        job = make_job(rows[job_id])
        resolver = SelectedConditionReview(Jobs(job), cache, reviewer)

        def flow(variant):
            return DialogueFlow(Jobs(job), planners[variant], Questioner(), include_unverified=True, condition_resolver=resolver)

        try:
            state, _, _ = flow('B').advance({}, {'action': 'search', 'search_plan': {'skills': ['Java']}}, invoke)
            state, selected, _ = flow('B').advance(state, {'action': 'select', 'source_id': job['source_id']}, invoke)
            record['selection'] = {'stage': selected.get('stage'), 'review': (state.get('condition_review') or {}).get('status')
                                   or (state.get('condition_review') or {}).get('source')}
        except Exception as exc:          # noqa: BLE001
            record['selection'] = {'error': type(exc).__name__}
            path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding='utf-8')
            log(f'{job_id}: 공고 선택 실패 {type(exc).__name__}')
            continue
        for qkey, question in QUESTIONS.items():
            entry = record['answers'].setdefault(qkey, {'question': question, 'variants': {}})
            if 'route' not in entry:
                try:
                    value = invoke('intent_classification', planners['B'].classify, question, routing_context(copy.deepcopy(state)))
                    entry['route'] = value['decision']
                except Exception as exc:  # noqa: BLE001
                    entry['route'] = {'error': type(exc).__name__}
                made += 1
            if 'error' in entry['route']:
                continue
            decision = IntentDecision.model_validate(entry['route'])
            for variant in VARIANTS:
                if variant in entry['variants']:
                    continue
                payload = {'action': 'search', 'message': question}
                try:
                    ctx = requirement_text_passed() if variant in ('T', 'C') else contextlib.nullcontext()
                    with ctx:
                        _, result, _ = ContextRouter(flow(variant)).execute(copy.deepcopy(state), payload, decision, invoke)
                    entry['variants'][variant] = {'message': result.get('message') or '', 'stage': result.get('stage')}
                except Exception as exc:  # noqa: BLE001
                    entry['variants'][variant] = {'error': type(exc).__name__}
                made += 1
        record['usage'] = record.get('usage', []) + usage
        path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding='utf-8')
        log(f"{job_id}: 경로 {[(record['answers'][q]['route'].get('target'), record['answers'][q]['route'].get('action')) for q in QUESTIONS]}")
    return made


# ---- scoring ---------------------------------------------------------------------------------------

def norm(text):
    return re.sub(r'\s+', ' ', text or '').strip().casefold()


def mentioned(name, answer):
    n, a = norm(name), norm(answer)
    if not n:
        return False
    if re.fullmatch(r'[a-z0-9.+#/ -]+', n):        # ASCII names: whole-word match, so "C" is not found in "CI/CD"
        return re.search(r'(?<![a-z0-9])' + re.escape(n) + r'(?![a-z0-9])', a) is not None
    return n in a


def vocabulary(gold):
    names = {t for l in gold['labels'].values() for g in parse_terms(l.get('terms')) for t in g}
    if SKILLS.exists():
        for key, value in json.loads(SKILLS.read_text(encoding='utf-8')).items():
            if key.startswith('_'):
                continue
            names.add(key)
            names.update(a for a in (value.get('aliases') if isinstance(value, dict) else []) or [] if len(a) > 1)
    return {n for n in names if len(norm(n)) > 1}


def expectations(gold, snapshot_path=SNAPSHOT):
    """Per posting: skill names a person wrote for each section, and the years in experience lines."""
    rows = {f"jumpit-{r['source_id']}": r for r in json.loads(Path(snapshot_path).read_text(encoding='utf-8'))['postings']}
    parser, _ = load_parser()
    out = {}
    for job_id, job in gold['jobs'].items():
        quotes = {c['key']: c['quote'] for c in conditions_of(rows[job_id], parser)}
        names = {'required': set(), 'preferred': set()}
        years = set()
        for c in job['conditions']:
            label = gold['labels'][c['key']]
            names[c['type']] |= {t for g in parse_terms(label.get('terms')) for t in g}
            # Years come from any required line that talks about career, whatever its category
            # (11/17: lines like "Python 경력 3~10년" were labeled skill, so category alone missed them).
            if c['type'] == 'required' and re.search(r'경력|연차|년차|이상|이하', quotes[c['key']]):
                years |= set(re.findall(r'(\d+)\s*년', quotes[c['key']]))
        out[job_id] = {'required': names['required'], 'preferred': names['preferred'], 'years': years,
                       'tags': set(rows[job_id].get('tech_stacks') or [])}
    return out


def score_answer(qkey, answer, exp, vocab):
    if qkey == 'experience':
        # Only "did the answer give the posting's years". Whether it made years up where the posting has
        # none cannot be told from the text alone ("예: 3년 이상 등은 명시되어 있지 않습니다" is correct).
        claimed = set(re.findall(r'(\d+)\s*년', answer or ''))
        if exp['years']:
            return {'kind': 'years', 'correct': exp['years'] <= claimed}
        return {'kind': 'no_years_in_posting', 'correct': None}
    target, other = exp[qkey], exp['preferred' if qkey == 'required' else 'required']
    found = {n for n in target if mentioned(n, answer)}
    extra = {n for n in vocab if mentioned(n, answer)} - {n for n in target}
    mixed = {n for n in extra if any(norm(n) == norm(o) for o in other)}
    from_tags = {n for n in extra - mixed if any(norm(n) == norm(t) for t in exp['tags'])}
    made_up = extra - mixed - from_tags
    # A name inside another name the answer gives (e.g. "Spring" in "Spring Boot") is not an extra claim.
    made_up = {n for n in made_up if not any(norm(n) != norm(m) and norm(n) in norm(m) for m in found | mixed | from_tags)}
    return {'kind': 'names', 'gold': len(target), 'found': len(found),
            'recall': len(found) / len(target) if target else None,
            'mixed_up_section': len(mixed), 'from_tags': len(from_tags), 'not_in_posting': len(made_up)}


def score(gold, out_dir=RUNS, snapshot_path=SNAPSHOT, allow_unsealed=False):
    if not allow_unsealed and not is_sealed(gold):
        raise SystemExit('정답이 봉인되지 않았습니다.')
    exp, vocab = expectations(gold, snapshot_path), vocabulary(gold)
    per = {v: {q: {} for q in QUESTIONS} for v in VARIANTS}
    routes = {q: {} for q in QUESTIONS}
    for job_id in gold['jobs']:
        path = Path(out_dir) / f'{job_id}.json'
        if not path.exists():
            continue
        record = json.loads(path.read_text(encoding='utf-8'))
        for qkey, entry in record.get('answers', {}).items():
            r = entry.get('route', {})
            label = r.get('error') or f"{r.get('target')}/{r.get('action')}" + (f"/{r['task']}" if r.get('task') else '')
            routes[qkey][label] = routes[qkey].get(label, 0) + 1
            for variant, ans in entry.get('variants', {}).items():
                per[variant][qkey][job_id] = (score_answer(qkey, ans.get('message', ''), exp[job_id], vocab)
                                              if 'error' not in ans else {'error': ans['error']})
    report = {'routes': routes}
    for variant in VARIANTS:
        report[variant] = {}
        for qkey in QUESTIONS:
            items = [x for x in per[variant][qkey].values() if 'error' not in x]
            errors = sum(1 for x in per[variant][qkey].values() if 'error' in x)
            if qkey == 'experience':
                with_years = [x for x in items if x['kind'] == 'years']
                without = [x for x in items if x['kind'] == 'no_years_in_posting']
                report[variant][qkey] = {
                    'answered': len(items), 'errors': errors,
                    'years_correct': f"{sum(x['correct'] for x in with_years)}/{len(with_years)}",
                    'postings_without_years': len(without)}
            else:
                scored = [x for x in items if x['recall'] is not None]
                report[variant][qkey] = {
                    'answered': len(items), 'errors': errors,
                    'recall_mean': round(sum(x['recall'] for x in scored) / len(scored), 3) if scored else None,
                    'names_found': f"{sum(x['found'] for x in scored)}/{sum(x['gold'] for x in scored)}",
                    # Not a measure of mistakes: answers often name the other section correctly labelled
                    # ("참고로 우대 조건은 …") or list examples the posting does not require (checked 11/17).
                    'other_section_names_mentioned': sum(x['mixed_up_section'] for x in items),
                    'names_outside_answer_key_mentioned': sum(x['not_in_posting'] for x in items)}
    report['differences'] = {}
    for a, b in (('B', 'T'), ('T', 'C'), ('B', 'C')):
        for qkey in ('required', 'preferred'):
            pairs = [(per[a][qkey][j]['recall'], per[b][qkey][j]['recall']) for j in per[a][qkey]
                     if j in per[b][qkey] and 'error' not in per[a][qkey][j] and 'error' not in per[b][qkey][j]
                     and per[a][qkey][j]['recall'] is not None]
            if not pairs:
                continue
            rng = random.Random(SEED)
            diffs = sorted(sum(pairs[i][1] - pairs[i][0] for i in draw) / len(draw)
                           for draw in ([rng.randrange(len(pairs)) for _ in pairs] for _ in range(4000)))
            report['differences'][f'{b}-{a} {qkey} recall'] = {
                'diff': round(sum(y - x for x, y in pairs) / len(pairs), 3), 'ci95': [round(diffs[100], 3), round(diffs[3899], 3)],
                'postings': len(pairs)}
    return report


def plan():
    gold = json.loads(GOLD.read_text(encoding='utf-8'))
    n = len(gold['jobs'])
    return {'postings': n, 'questions': len(QUESTIONS),
            'calls': {'condition_labels (selected-question-v1)': n, 'routing (context-intent-v7)': n * len(QUESTIONS),
                      'answers': n * len(QUESTIONS) * len(VARIANTS)},
            'total_calls': n + n * len(QUESTIONS) * (1 + len(VARIANTS))}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('command', choices=('plan', 'run', 'score'))
    ap.add_argument('--live', action='store_true')
    ap.add_argument('--limit', type=int)
    args = ap.parse_args(argv)
    if args.command == 'plan':
        print(json.dumps(plan(), ensure_ascii=False, indent=1))
        return
    gold = json.loads(GOLD.read_text(encoding='utf-8'))
    if args.command == 'run':
        if not args.live:
            raise SystemExit('--live 가 필요합니다 (Bedrock 호출).')
        print(json.dumps({'calls_made': run(gold, limit=args.limit)}))
    else:
        report = score(gold)
        RUNS.mkdir(parents=True, exist_ok=True)
        (RUNS / 'score.json').write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
