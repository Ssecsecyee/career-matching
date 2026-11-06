"""A single free-text intent gateway. Models propose, server state authorizes execution."""
from src.schemas.intent import IntentDecision, merge_search
from src.services.intent_context import routing_context, assessment_facts
from src.services.search_constraints import guard_required_skills
from src.services.dialogue import FlowError
from src.services.memory import record, consultation_context, public_memory
from src.services.conversation_policy import preferences, respect_preferences
from src.services.learning import attach
from src.services.search_review import review_response


class ContextRouter:
    def __init__(self, flow):self.flow=flow

    def advance(self,state,payload,invoke,on_decision=None):
        if payload['action']=='confirm_search' and payload.get('search_id') and payload.get('search_id')==(state.get('training_search_context') or {}).get('search_id'):
            if on_decision:on_decision(None,{'direct_action':'confirm_search','target':'training'})
            return self.confirm_training(state,payload['search_id'])
        if payload['action']=='explain_training':
            courses=list((state.get('training_displayed') or {}).values())+(state.get('learning_context') or {}).get('courses',[])
            course=next((c for c in courses if c['source']==payload['source'] and c['source_id']==payload['source_id']
                         and str(c.get('source_version'))==payload['source_version']),None)
            if course is None:raise FlowError('training_reference_changed',409)
            state['training_focus']={k:payload[k] for k in ('source','source_id','source_version')}
            if on_decision:on_decision(None,{'direct_action':'explain_training','target':'training',**state['training_focus']})
            message=f"{course.get('provider_name','')} · {course['title']} 교육을 설명해줘. 저장된 회차 일정·비용·모집 상태·지원 자격을 구분하고, 없는 상세 정보는 추측하지 말아줘."
            return self.execute(state,{'message':message},IntentDecision(target='training',action='chat',reason='Explicit displayed education explanation button'),invoke)
        state.setdefault('stage','conversation')
        if payload['action']=='next_results':
            decision=IntentDecision(target=payload['target'],action='next_results',reason='Explicit result navigation button')
        elif payload['action']=='assessment_control':
            decision=IntentDecision(target='selected',action='assessment_control',control=payload['control'],reason='Explicit assessment control button')
        elif payload['action']=='search' and payload.get('search_plan') is None:
            # Do not run expression matching, retrieval or legacy route() before classification.
            value=invoke('intent_classification',self.flow.planner.classify,payload['message'],routing_context(state))
            decision=IntentDecision.model_validate(value['decision'])
            if on_decision:on_decision(value.get('raw_output',''),decision.to_dict())
        else:
            if on_decision:on_decision(None,{'direct_action':payload['action']})
            result=self.flow.advance(state,payload,invoke)
            if payload['action']=='select':state['conversation_target']='jobs'
            return result
        if on_decision and payload['action'] in {'next_results','assessment_control'}:
            on_decision(None,decision.to_dict())
        return self.execute(state,payload,decision,invoke)

    @staticmethod
    def clarify(state,question):
        # Preserve selected job, review ID, visible candidates and answers.
        state['intent_clarification']={'question':question}
        record(state,question,'assistant')
        return state,{'stage':'conversation','message':question,'clarification_required':True,'memory':public_memory(state)},[]

    def execute(self,state,payload,d,invoke):
        action,target=d.action,d.target
        if d.ask_assessment is not None:preferences(state)['ask_assessment']=d.ask_assessment
        text=payload.get('message','')
        if action not in {'search','refine_search','consult'} or (target=='training' and action in {'search','refine_search'}):record(state,text,'statement')
        if action=='clarify':
            result=self.clarify(state,d.question)
            state['intent_clarification']['target']=target
            if target in {'jobs','training'}:state['conversation_target']=target
            return result
        state.pop('intent_clarification',None)
        if action in {'search','refine_search'}:
            if target=='training':
                return self.training(state,d,reset=True)
            if action=='refine_search':
                plan=(state.get('search_navigation') or {}).get('plan')
                if not plan:return self.clarify(state,'바꿀 기존 검색이 없습니다. 어떤 공고를 찾으시나요?')
                try:plan=merge_search(plan,d.changes)
                except ValueError:return self.clarify(state,'이전 검색 형식과 바로 합칠 수 없습니다. 새 검색 조건을 알려주세요.')
            else:plan=d.plan.as_search_plan()
            raw_plan=plan.to_dict()
            facts=assessment_facts(state)
            previous=(state.get('search_navigation') or {}).get('plan') or (state.get('search_context') or {}).get('executed_plan')
            plan,guard=guard_required_skills(plan,previous,d,text)
            if plan is None:
                return self.clarify(state,'모두 필요한 기술로 제안된 조건의 요청 근거를 확인하지 못했습니다. 반드시 포함할 기술과 참고할 경험을 구분해서 알려주세요.')
            if d.search_basis=='assessment' and not any(c['assessment']=='met' for c in facts['items']):
                return self.clarify(state,'추천에 사용할 충족 답변을 확인하지 못했습니다. 기준으로 삼을 경험을 알려주세요.')
            excluded=[state['selected']['source_id']] if d.search_basis=='assessment' and state.get('selected') else []
            state['conversation_target']='jobs'
            # A schema-validated plan enters the existing search executor, never legacy classification.
            record(state,text,'search')
            result=self.flow.execute_search(state,plan,raw_plan,payload,require_review=True,exclude_ids=excluded)
            context=state.get('search_context')
            if context:
                context['constraint_guard']=guard
                context['assessment_basis']=facts if d.search_basis=='assessment' else None
                if d.search_basis=='assessment':
                    context['summary']['limitations'].append('문답 결과는 자기보고 경험으로 참고했습니다. 선택했던 공고는 제외하며, 지원 자격 충족을 보장하지 않습니다.')
                if guard['unsupported_required_skills']:
                    context['summary']['limitations'].append('문답에서 추론한 조건은 필수 제외 조건으로 쓰지 않고 선호 순위에 반영했습니다: '+', '.join(guard['unsupported_required_skills']))
            return result
        if action=='next_results':
            if target=='training':return self.training(state,d,reset=False)
            if not state.get('search_navigation') and (state.get('search_context') or {}).get('confirmed_at'):
                state['search_navigation']={'plan':state['search_context']['executed_plan'],
                    'shown_ids':list(dict.fromkeys(c['source_id'] for c in state.get('candidate_jobs',[])))}
            if not state.get('search_navigation'):
                return self.clarify(state,'이어서 볼 채용 검색이 없습니다. 먼저 원하는 공고를 알려주세요.')
            if state.get('stage')=='search_review' or (state.get('pending_candidate_jobs') and not (state.get('search_context') or {}).get('confirmed_at')):
                state['stage']='search_review'
                result=review_response(state)
                result['message']='아직 공고 목록을 표시하기 전입니다. 검색 기준을 확인하면 첫 목록을 보여드리겠습니다.'
                return state,result,[]
            state['conversation_target']='jobs'
            return state,self.flow.more_jobs(state),[]
        if action=='confirm_search':
            if target=='training':
                return self.confirm_training(state,(state.get('training_search_context') or {}).get('search_id'))
            if state.get('stage')!='search_review' or not state.get('search_context'):
                return self.clarify(state,'현재 확인을 기다리는 검색 기준이 없습니다. 어떤 검색을 원하시나요?')
            return state,self.flow.confirm_search(state,{'search_id':state['search_context']['search_id']}),[]
        if action=='remember':
            # Free-text corrections never silently erase all existing answers.
            result={'stage':'conversation','message':'이전 답변을 바로 초기화하지 않았습니다. 내 답변 보기·수정에서 해당 조건을 수정하거나, 경험 전체 정정을 확인해 주세요.',
                    'correction_confirmation_required':True,'memory':public_memory(state)}
            return state,result,[]
        if action in {'consult','summary','assessment_control'}:
            if action=='assessment_control' and d.control=='stop':
                preferences(state)['ask_assessment']=False
                return state,self.flow.paused_response(state),[]
            if action=='assessment_control' and d.control=='resume' and not state.get('selected'):
                preferences(state)['ask_assessment']=True
                return state,{'stage':'conversation','message':'역량 질문을 다시 허용했습니다. 공고를 선택하면 확인할 수 있습니다.'},[]
            if not state.get('selected'):
                return self.clarify(state,'현재 선택한 공고가 없습니다. 먼저 공고를 선택해 주세요.')
            if action=='summary':return state,self.flow.summary_response(state),[]
            if action=='consult':
                return state,self.flow.consult(state,dict(payload,task=d.task),invoke),[]
            self.flow.validate_selected(state)
            self.flow.ensure_conditions(state)
            self.flow.apply_condition_review(state,state['selected'],invoke)
            if self.flow.condition_resolver is not None:self.flow.validate_selected(state)
            if d.control=='preferred':
                answered={c.get('condition_id') for c in state.get('checks',[])}
                if any(c['type']=='required' and c['id'] not in answered for c in state.get('conditions',[])):
                    return self.clarify(state,'필수조건 답변이 아직 남아 있습니다. 먼저 필수조건을 마치거나 현재 답변으로 상담해 주세요.')
                state['preferred_approved']=True
            preferences(state)['ask_assessment']=True
            evidence=[]
            return state,self.flow.next_question(state,invoke,evidence),evidence
        if action=='chat':
            if target=='selected' and not state.get('selected'):
                return self.clarify(state,'상담할 공고를 먼저 선택해 주세요.')
            history=consultation_context(state)
            if target=='training':
                from src.services.training_dates import refresh_card_status
                learning=state.get('learning_context')
                if learning is not None:
                    learning=dict(learning,courses=[refresh_card_status(c) for c in learning.get('courses',[])])
                    state['learning_context']=learning
                retrieval=learning or {'status':'unavailable','courses':[],'topics':[]}
                focus=state.get('training_focus')
                if focus and learning:
                    focused=[c for c in list((state.get('training_displayed') or {}).values())+learning.get('courses',[]) if c['source']==focus['source'] and c['source_id']==focus['source_id'] and str(c.get('source_version'))==focus['source_version']]
                    if focused:retrieval=dict(learning,courses=[refresh_card_status(focused[0])])
                history['training_retrieval']=retrieval
                history['conversation_focus']={'kind':'training'}
                state['conversation_target']='training'
            state.pop('training_focus',None)
            reply=invoke('context_response',self.flow.planner.respond,text,history)['reply']
            reply=respect_preferences(reply,state)
            record(state,reply,'assistant')
            # Keep a pending checklist/review resumable; do not turn a chat into a new search.
            result={'stage':'conversation','message':reply,'memory':public_memory(state)}
            if target=='training':
                learning=state.get('learning_context')
                # Retain retrieval in state/model context, not as a new result list.
                if learning and learning.get('courses'):
                    result['training_navigation_available']=True
            return state,result,[]
        raise FlowError('unsupported_intent_action')

    def preview_training(self,state,d):
        state.pop('training_catalog_filters',None)
        from src.services.training_review import remember_review
        previous=(state.get('training_search_context') if state.get('stage') in {'training_search_review','training_no_results'} else None) or state.get('training_navigation') or state.get('learning_context') or {}
        topics=list(d.topics) if d.topics is not None else (previous.get('topics',[]) if d.action=='refine_search' else [])
        operator=d.topic_operator if d.topic_operator is not None else (previous.get('topic_operator','or') if d.action=='refine_search' else 'or')
        goals=list(d.learning_goals) if d.learning_goals is not None else (previous.get('learning_goals',[]) if d.action=='refine_search' else [])
        mode=d.delivery_mode if d.delivery_mode is not None else (previous.get('delivery_mode') if d.action=='refine_search' else None)
        mode=None if mode=='any' else mode
        if not topics:
            state['conversation_target']='training'
            return self.clarify(state,'배우고 싶은 분야·기술 또는 찾는 교육기관명을 알려주세요.')
        repository=self.flow.training
        if repository is None:return self.clarify(state,'현재 교육 검색 연결을 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.')
        options={'topic_operator':operator} if operator!='or' else {}
        if state.get('training_browse'):options['browse_all']=True
        courses=repository.search(topics,exclude_ids=[],delivery_mode=mode,candidates_only=True,**options)
        result=remember_review(state,topics,mode,courses,repository,learning_goals=goals,topic_operator=operator)
        record(state,result['message'],'assistant')
        return state,result,[]

    def confirm_training(self,state,search_id):
        from src.services.training_review import remember_review,signatures
        context=state.get('training_search_context') or {}
        if state.get('stage')!='training_search_review' or not search_id or search_id!=context.get('search_id'):
            raise FlowError('stale_training_search',409)
        repository=self.flow.training
        if repository is None:return self.clarify(state,'현재 교육 검색 연결을 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.')
        options={'topic_operator':context['topic_operator']} if context.get('topic_operator','or')!='or' else {}
        if state.get('training_browse'):options['browse_all']=True
        courses=repository.search(context['topics'],exclude_ids=[],delivery_mode=context['delivery_mode'],candidates_only=True,**options)
        expected=[tuple(x) for x in context['candidate_versions']]
        if signatures(courses)!=expected:
            result=remember_review(state,context['topics'],context['delivery_mode'],courses,repository,learning_goals=context.get('learning_goals',[]),topic_operator=context.get('topic_operator','or'))
            result['search_changed']=True
            result['message']='확인하는 동안 교육 정보나 노출 대상이 바뀌었습니다. 갱신된 기준을 다시 확인해 주세요.'
            record(state,result['message'],'assistant')
            return state,result,[]
        from datetime import datetime,timezone
        context['confirmed_at']=datetime.now(timezone.utc).isoformat()
        state['training_navigation']={'topics':context['topics'],'delivery_mode':context['delivery_mode'],'shown_ids':[],'topic_operator':context.get('topic_operator','or'),'learning_goals':context.get('learning_goals',[])}
        state['stage']='conversation'
        state,result,evidence=self.training(state,None,reset=False,confirmed=courses)
        result.update(search_id=search_id,search_target='training',training_continuation=False,search_summary=context['summary'])
        return state,result,evidence

    def training(self,state,d,*,reset,confirmed=None):
        if reset:return self.preview_training(state,d)
        if state.get('stage') in {'training_search_review','training_no_results'} and confirmed is None:
            from src.services.training_review import review_response
            result=review_response(state)
            if state['stage']=='training_search_review':result['message']='아직 교육 목록을 표시하기 전입니다. 검색 기준을 확인하면 첫 목록을 보여드리겠습니다.'
            return state,result,[]
        state.pop('training_focus',None)
        previous=state.get('learning_context') or {}
        navigation=state.get('training_navigation') or {}
        if not reset and not navigation and previous.get('topics'):
            navigation={'topics':previous['topics'],'topic_operator':previous.get('topic_operator','or'),'learning_goals':previous.get('learning_goals',[]),'delivery_mode':previous.get('delivery_mode'),
                'shown_ids':[c['source']+':'+c['source_id'] for c in previous.get('courses',[])]}
        if not reset and not navigation:
            return self.clarify(state,'이어서 볼 교육 검색이 없습니다. 먼저 배우고 싶은 주제를 알려주세요.')
        topics=navigation['topics'];mode=navigation.get('delivery_mode')
        if len(navigation['shown_ids'])>=1000:
            return state,{'stage':'conversation','message':'교육 탐색 한도에 도달했습니다. 주제를 좁혀주세요.','learning_search':{'status':'no_match'},'learning_opportunities':[],'training_continuation':True,'training_has_more':False},[]
        repository=self.flow.training
        if repository is None:
            courses=[];status='unavailable'
        else:
            kwargs={'exclude_groups':navigation['shown_groups']} if navigation.get('shown_groups') else {}
            if state.get('training_catalog_filters') is not None:
                filters=state['training_catalog_filters']
                if filters.get('region') or filters.get('field')=='ncs_code':repository=getattr(repository,'fallback',repository)
                kwargs['catalog_filters']=state['training_catalog_filters']

            if not topics or state.get('training_browse'):kwargs['browse_all']=True
            if navigation.get('topic_operator','or')!='or':kwargs['topic_operator']=navigation['topic_operator']
            courses=confirmed if confirmed is not None else repository.search(topics,exclude_ids=navigation['shown_ids'],delivery_mode=mode,candidates_only=True,**kwargs)
            status='found' if courses else 'no_match'
        if confirmed is not None:state['training_displayed']={}
        displayed=state.setdefault('training_displayed',{})
        for course in courses:displayed[course['source']+':'+course['source_id']]=course
        ids=[c['source']+':'+c['source_id'] for c in courses]
        if set(ids).intersection(navigation['shown_ids']) or len(set(ids))!=len(ids):
            raise FlowError('training_navigation_duplicate',502)
        navigation['shown_ids']=list(dict.fromkeys(navigation['shown_ids']+ids))
        from src.services.training_groups import group_key
        navigation['shown_groups']=list(dict.fromkeys(navigation.get('shown_groups',[])+[group_key(c) for c in courses if c.get('cohorts')]))
        state['training_navigation']=navigation
        learning={'status':status,'topics':topics,'topic_operator':navigation.get('topic_operator','or'),'learning_goals':navigation.get('learning_goals',[]),'delivery_mode':mode,'courses':courses,
                  'basis':'validated_context_intent_and_stored_training', 'visibility_policy':'before_training_start_kst',
                  'limitations':['현재 모집 여부·지원 자격은 원문에서 확인해야 합니다.','미확인/과거 자료는 학습 참고용입니다.','교육 수료로 경력·학위·면허를 대체하지 않습니다.']}
        state['learning_context']=learning;state['conversation_target']='training';state['stage']='conversation'
        message=('시작일이 지나지 않은 교육 자료를 조회했습니다. 신청 기간·모집 여부·지원 자격은 고용24 또는 교육기관에서 확인해 주세요.' if courses else
                 '교육 검색 연결을 사용할 수 없습니다.' if status=='unavailable' else
                 '같은 조건에서 아직 보여드리지 않은 교육 자료가 없습니다. 실제 개설·모집 과정이 없다는 뜻은 아닙니다.' if not reset else
                 '저장된 자료에서 해당 주제·수강 방식에 맞는 교육을 찾지 못했습니다. 실제 개설·모집 과정이 없다는 뜻은 아닙니다.')
        if getattr(repository,'search_limited',False) is True:
            learning['search_limited']=True
            message+=' 조회 범위 제한이 있어 다른 과정이 더 있을 수 있습니다. 검색 조건을 좁혀 주세요.'
        record(state,message,'assistant')
        result={'stage':'conversation','message':message,'memory':public_memory(state),'training_continuation':confirmed is None,'training_has_more':bool(courses),'training_candidate_total':getattr(repository,'last_candidate_total',None),'catalog_filters':state.get('training_catalog_filters')}
        attach(result,learning)
        return state,result,[]
