"""Source-item questions with bounded session memory and explicit user assessments."""
from datetime import datetime, timezone

from src.schemas.search import SearchPlan
from src.services.learning import retrieve as retrieve_learning, attach as attach_learning
from src.services.memory import memory, record, context, apply_facts, condition_key, split_conditions, public_memory, consultation_context


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
    def __init__(self, jobs, planner, questioner, *, include_unverified=False, training=None):
        self.jobs, self.planner, self.questioner = jobs, planner, questioner
        self.include_unverified = include_unverified
        self.training = training

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
                if hasattr(self.planner, 'route'):
                    history = consultation_context(state)
                    learning = retrieve_learning(state, text, self.training)
                    if learning is not None:
                        state['learning_context'] = learning
                        history['training_retrieval'] = learning
                        history['conversation_focus'] = {'kind':'training','source_ids':[c.get('source_id') for c in learning['courses']],
                            'basis':'displayed_education_list' if learning.get('reference_resolution') else 'education_lookup'}
                    else:
                        state.pop('learning_context', None)
                    routed = invoke('conversation', self.planner.route, text, history)
                    if learning is not None and routed['intent'] != 'chat':
                        if learning['status']=='no_match':
                            reply='저장된 교육 자료에서 해당 분야의 과정을 찾지 못했습니다. 현재 신청 가능한 과정이 없다는 뜻은 아니며, 모집 여부는 확인하지 못했습니다.'
                        elif learning['status']=='need_topic':
                            reply='어떤 분야의 교육을 찾으시나요? 관심 있는 기술이나 직무를 알려주세요. 현재 모집 여부는 별도 확인이 필요합니다.'
                        else:
                            reply='교육 조회 결과를 확인해 주세요. 미확인 과정은 학습 참고용으로만 안내합니다.'
                        routed = {'intent':'chat','reply':reply}
                    if routed['intent'] == 'chat':
                        reply = routed['reply']
                        record(state, reply, 'assistant')
                        state.setdefault('stage', 'conversation')
                        result = {'stage':'conversation','memory':public_memory(state)}
                        if state.get('stage') in {'checking_required', 'checking_preferred'}:
                            result = self.batch_response(state) if state.get('grouped') else self.question_response(state)
                        elif state.get('stage') in {'completed', 'gap_guidance'}:
                            result = {'stage':'conversation','memory':public_memory(state)}
                        result['message'] = reply
                        attach_learning(result, learning)
                        if learning is not None and any(not c['recommendation_eligible'] for c in learning['courses']):
                            result['message'] = '아래 교육은 과거 회차 또는 모집 미확인 자료로, 학습 내용 참고용입니다.\n\n' + reply
                        return state, result, evidence
                    plan = SearchPlan.parse(routed['plan'])
                else:
                    plan = invoke('search_plan', self.planner.plan, text)
            state.pop('learning_context', None)
            total, jobs = self.jobs.search(plan)
            state['search_backend'] = getattr(self.jobs, 'last_search_backend', 'mysql')
            state['search_degraded'] = getattr(self.jobs, 'search_degraded', False)
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
            state['grouped'] = payload.get('grouped', False)
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

        if action == 'answer_batch':
            if not state.get('grouped') or state.get('stage') not in {'checking_required', 'checking_preferred'}:
                raise FlowError('no_pending_question', 409)
            self.validate_selected(state)
            pending = self.batch_conditions(state)
            answers = payload['answers']
            identities = [a['question_id'] for a in answers]
            if len(set(identities)) != len(identities) or set(identities) != {c['id'] for c in pending}:
                raise FlowError('question_changed', 409)
            by_id = {a['question_id']: a for a in answers}
            for condition in pending:
                item = by_id[condition['id']]
                check = self.make_check(condition, item['assessment'], item.get('detail', ''))
                state['checks'].append(check)
                evidence.append({'job':state['selected'], 'check':check, 'section':condition['section']})
                record(state, f"조건: {condition['quote']}\n답변: {check['assessment']}", 'answer')
                record(state, check['detail'], 'answer_detail')
                if check['assessment'] != 'unknown':
                    memory(state)['confirmed'][condition['key']] = dict(check, source_id=state['selected']['source_id'], source_version=state['selected']['source_version'])
            return state, self.next_question(state, invoke, evidence), evidence

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

    @staticmethod
    def batch_conditions(state):
        answered = {c.get('condition_id') for c in state.get('checks', [])}
        remaining = [c for c in state.get('conditions', []) if c['id'] not in answered]
        if not remaining:
            return []
        return [c for c in remaining if c['type'] == remaining[0]['type']]

    def batch_response(self, state):
        pending = self.batch_conditions(state)
        return {'stage':state['stage'], 'grouped':True,
                'questions':[{'question_id':c['id'], 'quote':c['quote']} for c in pending],
                'question':'각 원문 조건에 답해 주세요. 판단하기 어려운 조건은 미확인으로 남겨도 됩니다.',
                'requirement_type':pending[0]['type'], 'source_url':state['selected']['source_url'],
                'progress':{'answered':len(state['checks']), 'total':len(state['conditions'])},
                'memory':public_memory(state), 'generation':'source_checklist'}

    def next_question(self, state, invoke, evidence):
        if state.get('grouped'):
            pending = self.batch_conditions(state)
            if pending:
                state['stage'] = 'checking_required' if pending[0]['type'] == 'required' else 'checking_preferred'
                return self.batch_response(state)
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
        result = {'stage': state['stage'], 'checks': state['checks'], 'memory': public_memory(state),
                'unconfirmed_count': sum(c['assessment'] == 'unknown' for c in state['checks']),
                'message': '원문 조건 확인을 마쳤습니다. 미확인 조건은 충족으로 판단하지 않습니다. 합격 판단은 아닙니다.',
                'learning_opportunities': [], 'limitations': [
                  '원문 목록 항목 기준이며 AND·OR 관계를 임의로 나누지 않습니다.', '조건 충족 여부는 사용자 진술에 근거합니다.']}
        if self.training is not None and any(c['assessment'] == 'unmet' for c in state['checks']):
            learning = retrieve_learning(state, '부족한 역량 학습', self.training)
            attach_learning(result, learning)
            state['learning_context'] = learning
        return result

    def search_response(self, state):
        return {'stage': state.get('stage', 'no_results'), 'candidate_jobs': state.get('candidate_jobs', []),
                'total': state.get('total', 0), 'memory': public_memory(state),
                'search_backend':state.get('search_backend','mysql'), 'search_degraded':state.get('search_degraded',False),
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
