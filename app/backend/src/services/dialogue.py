"""Source-item questions with bounded session memory and explicit user assessments."""
from datetime import datetime, timezone

from src.schemas.search import SearchPlan
from src.services.search_continuation import is_more_request, mark_shown
from src.services.consultation import legacy_task, counseling_context
from src.services.search_review import is_confirmation, needs_review, remember_search, review_response
from src.services.conversation_policy import preferences, assessment_request, search_target, respect_preferences
from src.services.condition_display import display_condition
from src.services.condition_structure import source_binding, source_notice
from src.services.assessment_summary import build_summary, summary_requested
from src.services.learning import retrieve as retrieve_learning, attach as attach_learning
from src.services.memory import memory, record, context, apply_facts, condition_key, split_conditions, public_memory, consultation_context


class FlowError(Exception):
    def __init__(self, code, status=400):
        self.code, self.status = code, status
        super().__init__(code)


def ensure_selectable(job, include_unverified):
    if not job or job.get('recruitment_status') not in ({'active', 'unknown'} if include_unverified else {'active'}):
        raise FlowError('job_not_available', 409)
    from src.services.deadlines import expired
    if expired(job):
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
        # Upgrade an already-confirmed pre-navigation session from its stored plan.
        if (not state.get('search_navigation') and state.get('search_context')
                and state['search_context'].get('confirmed_at')):
            state['search_navigation'] = {
                'plan': state['search_context']['executed_plan'],
                'shown_ids': list(dict.fromkeys(c['source_id'] for c in state.get('candidate_jobs', [])))}
        if (action == 'search' and payload.get('search_plan') is None and not payload.get('profile')
                and state.get('search_navigation') and state.get('stage') != 'search_review'
                and state.get('conversation_target') != 'training'
                and is_more_request(payload.get('message', ''))):
            record(state, payload['message'], 'search_continuation')
            return state, self.more_jobs(state), evidence
        if action == 'consult':
            return state, self.consult(state,payload,invoke), evidence
        if (action == 'search' and payload.get('search_plan') is None and state.get('selected')
                and hasattr(self.planner,'consult')):
            task=legacy_task(payload.get('message',''),state.get('consultation_focus'))
            if task:
                return state, self.consult(state,dict(payload,task=task),invoke), evidence
        if action == 'confirm_search':
            return state, self.confirm_search(state, payload), evidence
        if action == 'search' and state.get('stage') == 'search_review' and is_confirmation(payload.get('message', '')):
            record(state, payload['message'], 'search_confirmation')
            return state, self.confirm_search(state, {'search_id': state['search_context']['search_id']}), evidence
        if action == 'remember' and assessment_request(payload.get('message','')) is False:
            preferences(state)['ask_assessment'] = False
            record(state, payload['message'], 'statement')
            return state, self.paused_response(state), evidence
        if action == 'search':
            # Same-session searches retain user memory; a new session starts empty.
            state['profile'].update({k: v for k, v in payload.get('profile', {}).items() if k != 'memory'})
            text = payload.get('message', '')
            record(state, text, 'search')
            target = search_target(state, text)
            consent = assessment_request(text)
            if consent is not None:
                preferences(state)['ask_assessment'] = consent
                if not consent:
                    state['stage'] = 'conversation'
                    if target not in {'jobs', 'training'}:
                        return state, self.paused_response(state), evidence
                elif state.get('selected'):
                    self.validate_selected(state)
                    selected = state['selected']
                    if not state.get('conditions'):
                        state['conditions'] = sum((split_conditions(selected.get(section) or '', kind, selected['source_id'], selected['source_version']) for kind, section in (('required','qualifications'),('preferred','preferred_requirements'))), [])
                    return state, self.next_question(state, invoke, evidence), evidence
                else:
                    return state, {'stage':'conversation','message':'역량 확인 질문을 다시 허용했습니다. 공고를 선택하면 확인할 수 있습니다.','memory':public_memory(state)}, evidence
            if payload.get('search_plan') is None and state.get('selected') and summary_requested(text):
                return state, self.summary_response(state), evidence
            if target == 'clarify':
                state['stage'] = 'conversation'
                return state, {'stage':'conversation','message':'채용공고와 교육 과정 중 어떤 것을 먼저 찾아드릴까요?','memory':public_memory(state)}, evidence
            if target:
                state['conversation_target'] = target

            statement = payload.get('profile', {}).get('user_statement')
            if isinstance(statement, str):
                record(state, statement)
            if payload.get('search_plan') is not None:
                plan = SearchPlan.parse(payload['search_plan'])
            else:
                # Search uses the user's current query; past skills must not become unwanted filters.
                if hasattr(self.planner, 'route'):
                    history = consultation_context(state)
                    learning = retrieve_learning(state, text, self.training, target=target)
                    if target == 'training' and learning is None:
                        learning = {'status':'unavailable','topics':[],'courses':[],'basis':'training_repository_not_configured','limitations':['교육 조회 연결을 사용할 수 없습니다.']}
                    if learning is not None:
                        state['learning_context'] = learning
                        history['training_retrieval'] = learning
                        history['conversation_focus'] = {'kind':'training','source_ids':[c.get('source_id') for c in learning['courses']],
                            'basis':'displayed_education_list' if learning.get('reference_resolution') else 'education_lookup'}
                    else:
                        state.pop('learning_context', None)
                    routed = invoke('conversation', self.planner.route, text, history)
                    if learning is not None and routed['intent'] != 'chat':
                        if learning['status']=='unavailable':
                            reply='교육 검색 연결을 사용할 수 없습니다. 채용공고로 바꾸어 검색하지 않고 교육 요청으로 유지하겠습니다.'
                        elif learning['status']=='no_match':
                            reply='저장된 교육 자료에서 해당 분야의 과정을 찾지 못했습니다. 현재 신청 가능한 과정이 없다는 뜻은 아니며, 모집 여부는 확인하지 못했습니다.'
                        elif learning['status']=='need_topic':
                            reply='어떤 분야의 교육을 찾으시나요? 관심 있는 기술이나 직무를 알려주세요. 현재 모집 여부는 별도 확인이 필요합니다.'
                        else:
                            reply='교육 조회 결과를 확인해 주세요. 미확인 과정은 학습 참고용으로만 안내합니다.'
                        routed = {'intent':'chat','reply':reply}
                    if routed['intent'] == 'chat':
                        reply = respect_preferences(routed['reply'], state)
                        record(state, reply, 'assistant')
                        state.setdefault('stage', 'conversation')
                        result = {'stage':'conversation','memory':public_memory(state)}
                        if learning is not None or not preferences(state)['ask_assessment']:
                            state['stage'] = 'conversation'
                        if state.get('stage') in {'checking_required', 'checking_preferred'}:
                            result = self.batch_response(state) if state.get('grouped') else self.question_response(state)
                        elif state.get('stage') == 'search_review':
                            result = review_response(state)
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
            raw_plan = payload.get('search_plan') or (routed.get('raw_plan', routed['plan']) if 'routed' in locals() else plan.to_dict())
            # Superseded review IDs must not reveal the new search's candidates.
            previous_search = state.pop('search_context', None)
            total, jobs = self.jobs.search(plan)
            state['search_backend'] = getattr(self.jobs, 'last_search_backend', 'mysql')
            state['search_degraded'] = getattr(self.jobs, 'search_degraded', False)
            cards = [{key: row.get(key) for key in
                      ('source_id', 'title', 'company_name', 'tech_stacks', 'addresses', 'source_url',
                       'source_version', 'recruitment_status', 'last_seen_at')} for row in jobs]
            state['search_navigation'] = {'plan': plan.to_dict(), 'shown_ids': []}
            state.pop('answer_summary', None)
            state.update(stage='choose_job' if jobs else 'no_results', candidate_ids=[j['source_id'] for j in jobs],
                         candidate_jobs=cards, total=total, selected=None, checks=[], conditions=[])
            if plan.schema_version == 2:
                remember_search(state, plan, raw_plan, payload, total, jobs)
                state['pending_candidate_jobs'] = cards
                state['candidate_ids'] = []
                if not jobs:
                    state['candidate_jobs'] = []
                    return state, review_response(state), evidence
                if needs_review(plan, text, changing=bool(previous_search)):
                    state['stage'] = 'search_review'
                    state['candidate_jobs'] = []
                    return state, review_response(state), evidence
                state['candidate_ids'] = [j['source_id'] for j in jobs]
            mark_shown(state)
            return state, self.search_response(state), evidence

        if action == 'select':
            state.pop('answer_summary', None)
            if payload['source_id'] not in state.get('candidate_ids', []):
                raise FlowError('job_not_in_session_candidates', 409)
            job = self.jobs.get(payload['source_id'])
            ensure_selectable(job, self.include_unverified)
            if not preferences(state)['ask_assessment']:
                state['selected'] = {key:job.get(key) for key in ('job_id','source_id','source_url','source_version','title','company_name','recruitment_status','qualifications','preferred_requirements')}
                state.update(stage='conversation', checks=[], conditions=[], grouped=payload.get('grouped',False))
                result = self.paused_response(state)
                result['message'] = f"{job['company_name']} · {job['title']} 공고입니다. 역량 확인 질문은 생략하고 원문 조건만 안내합니다."
                result['job_overview'] = {key:job.get(key) for key in ('title','company_name','source_url','qualifications','preferred_requirements')}
                return state, result, evidence
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
            state.pop('answer_summary', None)
            # Explicit corrections invalidate previous confirmations, rather than retaining stale eligibility.
            memory(state)['facts'] = []
            memory(state)['confirmed'] = {}
            record(state, payload['message'], 'correction')
            if state.get('selected'):
                self.validate_selected(state)
                self.ensure_conditions(state)
                state['checks'] = []
                result = self.next_question(state, invoke, evidence)
                result['message'] = ('경험을 수정했습니다. 이전 조건 답변은 다시 확인합니다.' if preferences(state)['ask_assessment'] else '경험을 수정했습니다. 역량 확인 질문 중단은 유지합니다.')
            else:
                result = self.search_response(state)
                result['message'] = '말씀하신 내용을 기억했습니다. 공고를 선택하면 질문에 반영합니다.'
            return state, result, evidence

        if action in {'answer', 'answer_batch'} and not preferences(state)['ask_assessment']:
            return state, self.paused_response(state), evidence

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

    def consult(self,state,payload,invoke):
        if not state.get('selected'):
            raise FlowError('consultation_requires_selected_job',409)
        summary=build_summary(state)
        if payload.get('summary_id') and (not summary or payload['summary_id']!=summary['summary_id']):
            raise FlowError('consultation_summary_changed',409)
        consent=assessment_request(payload['message'])
        if consent is False:preferences(state)['ask_assessment']=False
        record(state,payload['message'],'consult')
        task=payload['task']
        summary=build_summary(state)
        if summary:state['answer_summary']=summary
        if task=='defer':
            result=self.summary_response(state)
            result['message']='미확인 조건은 그대로 남겨 두겠습니다. 기존 답변을 보존하며 문답을 자동으로 다시 시작하지 않습니다.'
            result['consultation']={'task':task,'generation':'stored_summary','source_version':state['selected']['source_version']}
            return result
        answer=invoke('consultation',self.planner.consult,payload['message'],counseling_context(state,task),task)
        reply=respect_preferences(answer['reply'],state)
        record(state,reply,'assistant')
        state.update(stage='conversation',conversation_target='jobs',
                     consultation_focus={'task':task,'source_id':state['selected']['source_id'],
                                         'source_version':state['selected']['source_version']})
        if summary:state['answer_summary']=summary
        return {'stage':'conversation','message':reply,'memory':public_memory(state),
                'assessment_paused':not preferences(state)['ask_assessment'],
                'consultation':{'task':task,'generation':'text_model',
                    'source_id':state['selected']['source_id'],'source_version':state['selected']['source_version']}}

    def more_jobs(self, state):
        page = state['search_navigation']
        if len(page['shown_ids']) >= 1000:
            return {'stage':'conversation', 'message':'현재 탐색 한도에 도달했습니다. 검색 조건을 좁혀 새로 찾아주세요.'}
        plan = SearchPlan.parse(page['plan'])
        total, jobs = self.jobs.search(plan, exclude_ids=page['shown_ids'])
        cards = [{key: row.get(key) for key in
                  ('source_id','title','company_name','tech_stacks','addresses','source_url',
                   'source_version','recruitment_status','last_seen_at')} for row in jobs]
        # A next-page request must never erase the selected snapshot or saved assessments.
        state.update(candidate_jobs=cards, candidate_ids=[row['source_id'] for row in jobs],
                     total=total, stage='choose_job' if jobs else 'conversation',
                     search_backend=getattr(self.jobs,'last_search_backend','mysql'),
                     search_degraded=getattr(self.jobs,'search_degraded',False))
        mark_shown(state)
        result = self.search_response(state)
        result.update(search_continuation=True, remaining_total=total,
                      message=(f'앞서 보여드린 공고를 제외한 후보 {total}건 중 {len(cards)}건입니다.' if cards else
                               '같은 조건에서 아직 보여드리지 않은 공고가 없습니다. 원하시면 검색 조건을 바꿔주세요.'))
        return result

    def confirm_search(self, state, payload):
        search = state.get('search_context') or {}
        if state.get('stage') != 'search_review' or payload.get('search_id') != search.get('search_id'):
            raise FlowError('search_confirmation_changed', 409)
        cards = state.get('pending_candidate_jobs', [])
        for card in cards:
            current = self.jobs.get(card['source_id'])
            try:
                ensure_selectable(current, self.include_unverified)
            except FlowError:
                current = None
            if not current or str(current['source_version']) != str(card['source_version']):
                # Do not silently replace a reviewed snapshot with a new list.
                state.update(stage='no_results', candidate_jobs=[], candidate_ids=[])
                state.pop('pending_candidate_jobs', None)
                return {'stage':'no_results', 'message':'검색 후 공고가 변경되거나 노출이 종료됐습니다. 같은 조건으로 다시 검색해 주세요.',
                        'search_summary':search['summary'], 'search_changed':True, 'candidate_jobs':[]}
        state.update(stage='choose_job', candidate_jobs=cards,
                     candidate_ids=[c['source_id'] for c in cards])
        mark_shown(state)
        search['confirmed_at'] = datetime.now(timezone.utc).isoformat()
        return self.search_response(state)

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
                'reused': reused, **display_condition(condition['quote']), **source_binding(condition), **source_notice(condition)}

    @staticmethod
    def batch_conditions(state):
        answered = {c.get('condition_id') for c in state.get('checks', [])}
        remaining = [c for c in state.get('conditions', []) if c['id'] not in answered]
        if not remaining:
            return []
        return [c for c in remaining if c['type'] == remaining[0]['type']][:5]

    def batch_response(self, state):
        pending = self.batch_conditions(state)
        return {'stage':state['stage'], 'grouped':True,
                'questions':[dict(question_id=c['id'], quote=c['quote'], **display_condition(c['quote']), **source_notice(c)) for c in pending],
                'question':'각 원문 조건에 답해 주세요. 판단하기 어려운 조건은 미확인으로 남겨도 됩니다.',
                'requirement_type':pending[0]['type'], 'source_url':state['selected']['source_url'],
                'progress':{'answered':len(state['checks']), 'total':len(state['conditions'])},
                'memory':public_memory(state), 'generation':'source_checklist'}

    @staticmethod
    def attach_summary(state, result):
        summary=build_summary(state)
        if summary:
            state['answer_summary']=summary
            result['answer_summary']=summary
            result['checks']=list(state.get('checks', []))
            result['unconfirmed_count']=sum(c['assessment']=='unknown' for c in state.get('checks', []))
        return result

    @staticmethod
    def summary_response(state):
        state['stage']='conversation'
        result=DialogueFlow.attach_summary(state, {'stage':'conversation','memory':public_memory(state)})
        result['message']=result['answer_summary']['headline']
        if not preferences(state)['ask_assessment']:
            result['assessment_paused']=True
        return result

    @staticmethod
    def paused_response(state):
        state['stage'] = 'conversation'
        result={'stage':'conversation','assessment_paused':True,'message':'역량 확인 질문을 중단했습니다. 다시 허용하기 전까지 묻지 않고, 이미 알려주신 내용으로 안내하겠습니다.','memory':public_memory(state)}
        return DialogueFlow.attach_summary(state,result) if state.get('conditions') or state.get('checks') else result

    def next_question(self, state, invoke, evidence):
        state.pop('answer_summary', None)
        if not preferences(state)['ask_assessment']:
            return self.paused_response(state)
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
                    known['source_version'] == state['selected']['source_version'] and
                    known.get('parser_version') == condition.get('parser_version') and
                    known.get('section_hash') == condition.get('section_hash')):
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
        result=self.attach_summary(state,result)
        result['message']=result['answer_summary']['headline']
        # Education retrieval runs only on an explicit education request.
        state.pop('learning_context',None)
        return result

    def search_response(self, state):
        return {'stage': state.get('stage', 'no_results'), 'candidate_jobs': state.get('candidate_jobs', []),
                'total': state.get('total', 0), 'memory': public_memory(state),
                'search_backend':state.get('search_backend','mysql'), 'search_degraded':state.get('search_degraded',False),
                'snapshot_warning': self.include_unverified,
                **({'search_id':state['search_context']['search_id'], 'search_summary':state['search_context']['summary']}
                   if state.get('search_context') else {})}

    @staticmethod
    def question_response(state):
        return {'stage': state['stage'], 'question_id': state['condition']['id'],
                'question': state['question']['question'], 'quote': state['condition']['quote'],
                'requirement_type': state['condition']['type'], 'source_url': state['selected']['source_url'],
                'source_version': state['selected']['source_version'],
                'recruitment_status': state['selected']['recruitment_status'], 'assessment_basis': 'user_statement',
                'progress': {'answered': len(state['checks']), 'total': len(state['conditions'])},
                'generation': state['question'].get('generation', 'model'), **source_notice(state['condition']),
                'memory': public_memory(state)}
