"""A single free-text intent gateway. Models propose, server state authorizes execution."""
from src.schemas.intent import IntentDecision, merge_search
from src.services.intent_context import routing_context
from src.services.dialogue import FlowError
from src.services.memory import record, consultation_context, public_memory
from src.services.conversation_policy import preferences, respect_preferences
from src.services.learning import attach
from src.services.search_review import review_response


class ContextRouter:
    def __init__(self, flow):self.flow=flow

    def advance(self,state,payload,invoke,on_decision=None):
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
        if action=='clarify':return self.clarify(state,d.question)
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
            state['conversation_target']='jobs'
            # A schema-validated plan enters the existing search executor, never legacy classification.
            record(state,text,'search')
            return self.flow.execute_search(state,plan,plan.to_dict(),payload,require_review=True)
        if action=='next_results':
            if target=='training':return self.training(state,d,reset=False)
            if not state.get('search_navigation') and (state.get('search_context') or {}).get('confirmed_at'):
                state['search_navigation']={'plan':state['search_context']['executed_plan'],
                    'shown_ids':list(dict.fromkeys(c['source_id'] for c in state.get('candidate_jobs',[])))}
            if not state.get('search_navigation'):
                return self.clarify(state,'이어서 볼 채용 검색이 없습니다. 먼저 원하는 공고를 알려주세요.')
            if state.get('stage')=='search_review':
                result=review_response(state)
                result['message']='아직 공고 목록을 표시하기 전입니다. 검색 기준을 확인하면 첫 목록을 보여드리겠습니다.'
                return state,result,[]
            state['conversation_target']='jobs'
            return state,self.flow.more_jobs(state),[]
        if action=='confirm_search':
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
                history['training_retrieval']=state.get('learning_context') or {'status':'unavailable','courses':[],'topics':[]}
                history['conversation_focus']={'kind':'training'}
                state['conversation_target']='training'
            reply=invoke('context_response',self.flow.planner.respond,text,history)['reply']
            reply=respect_preferences(reply,state)
            record(state,reply,'assistant')
            # Keep a pending checklist/review resumable; do not turn a chat into a new search.
            result={'stage':'conversation','message':reply,'memory':public_memory(state)}
            if target=='training':
                learning=state.get('learning_context')
                if learning is not None:attach(result,learning)
            return state,result,[]
        raise FlowError('unsupported_intent_action')

    def training(self,state,d,*,reset):
        previous=state.get('learning_context') or {}
        navigation=state.get('training_navigation') or {}
        if not reset and not navigation and previous.get('topics'):
            navigation={'topics':previous['topics'],'delivery_mode':previous.get('delivery_mode'),
                'shown_ids':[c['source']+':'+c['source_id'] for c in previous.get('courses',[])]}
        if not reset and not navigation:
            return self.clarify(state,'이어서 볼 교육 검색이 없습니다. 먼저 배우고 싶은 주제를 알려주세요.')
        if reset:
            topics=list(d.topics) if d.topics is not None else (previous.get('topics',[]) if d.action=='refine_search' else [])
            mode=d.delivery_mode if d.delivery_mode is not None else (previous.get('delivery_mode') if d.action=='refine_search' else None)
            if not topics:return self.clarify(state,'어떤 분야나 기술의 교육을 찾으시나요?')
            navigation={'topics':topics,'delivery_mode':None if mode=='any' else mode,'shown_ids':[]}
        topics=navigation['topics'];mode=navigation.get('delivery_mode')
        if len(navigation['shown_ids'])>=1000:
            return self.clarify(state,'교육 탐색 한도에 도달했습니다. 주제를 좁혀 새로 찾아주세요.')
        repository=self.flow.training
        if repository is None:
            courses=[];status='unavailable'
        else:
            courses=repository.search(topics,exclude_ids=navigation['shown_ids'],delivery_mode=mode)
            status='found' if courses else 'no_match'
        ids=[c['source']+':'+c['source_id'] for c in courses]
        if set(ids).intersection(navigation['shown_ids']) or len(set(ids))!=len(ids):
            raise FlowError('training_navigation_duplicate',502)
        navigation['shown_ids']=list(dict.fromkeys(navigation['shown_ids']+ids))
        state['training_navigation']=navigation
        learning={'status':status,'topics':topics,'delivery_mode':mode,'courses':courses,
                  'basis':'validated_context_intent_and_stored_training',
                  'limitations':['현재 모집 여부·지원 자격은 원문에서 확인해야 합니다.','미확인/과거 자료는 학습 참고용입니다.','교육 수료로 경력·학위·면허를 대체하지 않습니다.']}
        state['learning_context']=learning;state['conversation_target']='training'
        message=('저장된 교육 자료를 조회했습니다. 신청 후보와 과거·모집 미확인 참고 자료를 구분해 확인해 주세요.' if courses else
                 '교육 검색 연결을 사용할 수 없습니다.' if status=='unavailable' else
                 '같은 조건에서 아직 보여드리지 않은 교육 자료가 없습니다. 실제 개설·모집 과정이 없다는 뜻은 아닙니다.' if not reset else
                 '저장된 자료에서 해당 주제·수강 방식에 맞는 교육을 찾지 못했습니다. 실제 개설·모집 과정이 없다는 뜻은 아닙니다.')
        record(state,message,'assistant')
        result={'stage':'conversation','message':message,'memory':public_memory(state)}
        attach(result,learning)
        return state,result,[]
