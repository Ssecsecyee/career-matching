"""Source-item questions with bounded session memory and explicit user assessments."""
from datetime import datetime, timezone

from src.schemas.search import SearchPlan
from src.services.memory import memory, record, context, apply_facts, condition_key, split_conditions, public_memory


class FlowError(Exception):
    def __init__(self, code, status=400):
        self.code, self.status = code, status
        super().__init__(code)


def ensure_selectable(job, include_unverified):
    if not job or job.get('recruitment_status') not in ({'active', 'unknown'} if include_unverified else {'active'}):
        raise FlowError('job_not_available', 409)
    deadline = job.get('deadline_at')
    if deadline and job.get('deadline_type') != 'always_open':
        if isinstance(deadline, str):
            deadline = datetime.fromisoformat(deadline.replace('Z', '+00:00'))
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        if deadline <= datetime.now(timezone.utc):
            raise FlowError('job_deadline_passed', 409)


class DialogueFlow:
    def __init__(self, jobs, planner, questioner, *, include_unverified=False):
        self.jobs, self.planner, self.questioner = jobs, planner, questioner
        self.include_unverified = include_unverified

    def advance(self, state, payload, invoke):
        action = payload['action']
        evidence = []
        memory(state)
        if action == 'search':
            # Same-session searches retain user memory; a new session starts empty.
            state['profile'].update({k: v for k, v in payload.get('profile', {}).items() if k != 'memory'})
            text = payload.get('message', '')
            record(state, text, 'search')
            statement = payload.get('profile', {}).get('user_statement')
            if isinstance(statement, str):
                record(state, statement)
            if payload.get('search_plan') is not None:
                plan = SearchPlan.parse(payload['search_plan'])
            else:
                # Search uses the user's current query; past skills must not become unwanted filters.
                plan = invoke('search_plan', self.planner.plan, text)
            total, jobs = self.jobs.search(plan)
            cards = [{key: row.get(key) for key in
                      ('source_id', 'title', 'company_name', 'tech_stacks', 'addresses', 'source_url',
                       'source_version', 'recruitment_status', 'last_seen_at')} for row in jobs]
            state.update(stage='choose_job' if jobs else 'no_results', candidate_ids=[j['source_id'] for j in jobs],
                         candidate_jobs=cards, total=total, selected=None, checks=[], conditions=[])
            return state, self.search_response(state), evidence

        if action == 'select':
            if payload['source_id'] not in state.get('candidate_ids', []):
                raise FlowError('job_not_in_session_candidates', 409)
            job = self.jobs.get(payload['source_id'])
            ensure_selectable(job, self.include_unverified)
            if not job.get('qualifications'):
                raise FlowError('qualification_source_missing', 409)
            if any(len(job.get(field) or '') > 18000 for field in ('qualifications', 'preferred_requirements')):
                raise FlowError('source_section_too_long', 413)
            state['selected'] = {key: job.get(key) for key in
                                 ('job_id', 'source_id', 'source_url', 'source_version', 'title',
                                  'company_name', 'recruitment_status', 'qualifications', 'preferred_requirements')}
            try:
                state['conditions'] = sum((split_conditions(job.get(section) or '', kind, job['source_id'], job['source_version'])
                    for kind, section in (('required', 'qualifications'), ('preferred', 'preferred_requirements'))), [])
            except ValueError as exc:
                raise FlowError('too_many_source_conditions', 413) from exc
            state['checks'] = []
            record(state, f"선택한 공고: {job['company_name']} / {job['title']}", 'selection')
            result = self.next_question(state, invoke, evidence)
            return state, result, evidence

        if action == 'remember':
            # Explicit corrections invalidate previous confirmations, rather than retaining stale eligibility.
            memory(state)['facts'] = []
            memory(state)['confirmed'] = {}
            record(state, payload['message'], 'correction')
            if state.get('selected'):
                self.validate_selected(state)
                self.ensure_conditions(state)
                state['checks'] = []
                result = self.next_question(state, invoke, evidence)
                result['message'] = '경험을 수정했습니다. 이전 조건 답변은 다시 확인합니다.'
            else:
                result = self.search_response(state)
                result['message'] = '말씀하신 내용을 기억했습니다. 공고를 선택하면 질문에 반영합니다.'
            return state, result, evidence

        if action == 'answer':
            if not state.get('selected') or state.get('stage') not in {'checking_required', 'checking_preferred'}:
                raise FlowError('no_pending_question', 409)
            self.validate_selected(state)
            self.ensure_conditions(state)
            condition = state['condition']
            if payload['question_id'] != condition['id']:
                raise FlowError('question_changed', 409)
            status = payload['assessment']
            detail = payload.get('detail', '')
            check = self.make_check(condition, status, detail)
            state['checks'] = [c for c in state['checks'] if c.get('condition_id') != condition['id']] + [check]
            evidence.append({'job': state['selected'], 'check': check, 'section': condition['section']})
            record(state, f"조건: {condition['quote']}\n답변: {status}" + (f'\n설명: {detail}' if detail else ''), 'answer')
            record(state, detail, 'answer_detail')
            if status != 'unknown':
                memory(state)['confirmed'][condition['key']] = dict(check, source_id=state['selected']['source_id'],
                                                                   source_version=state['selected']['source_version'])
            # Unknown is recorded and advanced; it is never silently treated as unmet.
            result = self.next_question(state, invoke, evidence)
            if status == 'unknown':
                result['message'] = '이 조건은 미확인으로 남기고 다음 항목으로 넘어갑니다.'
            return state, result, evidence
        raise FlowError('unsupported_action')

    def validate_selected(self, state):
        current = self.jobs.get(state['selected']['source_id'])
        ensure_selectable(current, self.include_unverified)
        if current['source_version'] != state['selected']['source_version']:
            raise FlowError('source_changed_reselect_job', 409)

    @staticmethod
    def ensure_conditions(state):
        # An already-open pre-upgrade session can finish its existing section question safely.
        if not state.get('conditions'):
            old = state['condition']
            old['key'] = condition_key(old['type'], old['quote'])
            state['conditions'] = [old]
            if old['type'] == 'required':
                selected = state['selected']
                state['conditions'] += split_conditions(selected.get('preferred_requirements') or '', 'preferred',
                                                          selected['source_id'], selected['source_version'])

    @staticmethod
    def make_check(condition, status, detail, reused=False):
        explanation = {'met': '사용자가 이 원문 조건을 충족한다고 답변했습니다.',
                       'unmet': '사용자가 이 원문 조건을 충족하지 못한다고 답변했습니다.',
                       'unknown': '사용자가 판단하기 어렵다고 답변하여 미확인으로 남겼습니다.'}[status]
        return {'condition_id': condition['id'], 'type': condition['type'], 'assessment': status,
                'detail': detail, 'quote': condition['quote'], 'explanation': explanation,
                'reused': reused}

    def next_question(self, state, invoke, evidence):
        answered = {c.get('condition_id') for c in state['checks']}
        for condition in state['conditions']:
            if condition['id'] in answered:
                continue
            known = memory(state)['confirmed'].get(condition['key'])
            # Reuse only for the same original criterion in the same verified source version.
            if (known and known['source_id'] == state['selected']['source_id'] and
                    known['source_version'] == state['selected']['source_version']):
                check = self.make_check(condition, known['assessment'], known['detail'], reused=True)
                state['checks'].append(check)
                evidence.append({'job': state['selected'], 'check': check, 'section': condition['section']})
                continue
            state['condition'] = condition
            question = invoke('question_' + condition['type'], self.questioner.question, condition, context(state))
            apply_facts(state, question.get('memory_updates', []))
            state.update(stage='checking_required' if condition['type'] == 'required' else 'checking_preferred', question=question)
            return self.question_response(state)
        state['stage'] = 'gap_guidance' if any(c['type'] == 'required' and c['assessment'] == 'unmet' for c in state['checks']) else 'completed'
        return {'stage': state['stage'], 'checks': state['checks'], 'memory': public_memory(state),
                'unconfirmed_count': sum(c['assessment'] == 'unknown' for c in state['checks']),
                'message': '원문 조건 확인을 마쳤습니다. 미확인 조건은 충족으로 판단하지 않습니다. 합격 판단은 아닙니다.',
                'learning_opportunities': [], 'limitations': ['교육 데이터는 아직 연결하지 않았습니다.',
                  '원문 목록 항목 기준이며 AND·OR 관계를 임의로 나누지 않습니다.', '조건 충족 여부는 사용자 진술에 근거합니다.']}

    def search_response(self, state):
        return {'stage': state.get('stage', 'no_results'), 'candidate_jobs': state.get('candidate_jobs', []),
                'total': state.get('total', 0), 'memory': public_memory(state),
                'snapshot_warning': self.include_unverified}

    @staticmethod
    def question_response(state):
        return {'stage': state['stage'], 'question_id': state['condition']['id'],
                'question': state['question']['question'], 'quote': state['condition']['quote'],
                'requirement_type': state['condition']['type'], 'source_url': state['selected']['source_url'],
                'source_version': state['selected']['source_version'],
                'recruitment_status': state['selected']['recruitment_status'], 'assessment_basis': 'user_statement',
                'progress': {'answered': len(state['checks']), 'total': len(state['conditions'])},
                'generation': state['question'].get('generation', 'model'),
                'memory': public_memory(state)}
