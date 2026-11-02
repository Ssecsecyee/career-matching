import copy
import json
import os
import unittest
from uuid import uuid4
from unittest.mock import Mock, MagicMock, patch
from src.schemas.intent import IntentDecision, SearchChanges, merge_search
from src.schemas.search import SearchPlan
from src.services.context_router import ContextRouter
from src.services.dialogue import DialogueFlow
from src.services.intent_context import routing_context, redact
from src.bedrock.client import BedrockPlanner
from src.bedrock.model_json import ModelOutputFormatError
from src.handlers.dialogue import handle_request, validate_payload
from src.repositories.intent_decisions import IntentDecisionStore
from test_backend import FakeRuntime
from test_dialogue import Jobs, Questioner


def invoke(purpose,fn,*args):return fn(*args)[0]

class Planner:
    model_id='offline-model';region='offline-region'
    def __init__(self,decision):self.decision=decision;self.calls=[]
    def classify(self,message,history):
        self.calls.append(('classify',message,copy.deepcopy(history)))
        return {'decision':self.decision,'raw_output':json.dumps(self.decision)},{}
    def respond(self,message,history):
        self.calls.append(('respond',message,copy.deepcopy(history)))
        return {'reply':'저장된 자료와 자기평가를 기준으로 설명합니다.'},{}
    def route(self,*args):raise AssertionError('Legacy route must not run')

class ContextRoutingTests(unittest.TestCase):
    def fixture(self,decision):
        planner=Planner(decision);jobs=Jobs();training=Mock();training.search.return_value=[]
        flow=DialogueFlow(jobs,planner,Questioner(),include_unverified=True,training=training)
        return ContextRouter(flow),planner,jobs,training

    def test_patch_preserves_unspecified_and_explicit_empty_clears_region(self):
        plan=SearchPlan(schema_version=2,regions=['서울'],roles=['백엔드'],owned_skills=['Python','Docker'])
        result=merge_search(plan.to_dict(),SearchChanges(regions=[]))
        self.assertEqual(result.regions,())
        self.assertEqual(result.roles,('백엔드',));self.assertEqual(result.owned_skills,('Python','Docker'))
        result=merge_search(plan.to_dict(),SearchChanges.model_validate({'regions':['부산']}))
        self.assertEqual(result.regions,('부산',))
        for value in [{},{'regions':None},{'sql':'DROP TABLE jobs'},{'regions':'부산'}]:
            with self.assertRaises(ValueError):SearchChanges.model_validate(value)

    def test_action_contract_rejects_mixed_and_executable_fields(self):
        for value in [dict(target='jobs',action='next_results',plan={'schema_version':2}),
                      dict(target='training',action='consult',task='prepare'),
                      dict(target='jobs',action='refine_search'),
                      dict(target='selected',action='assessment_control'),
                      dict(target='jobs',action='search',plan={'keyword':'literal'}),
                      dict(target='jobs',action='next_results',sql='SELECT 1')]:
            with self.assertRaises(ValueError):IntentDecision.model_validate(dict(value,reason='test'))

    def test_identical_text_dispatches_by_validated_target_not_regex(self):
        for target in ['jobs','training']:
            router,planner,jobs,training=self.fixture(dict(target=target,action='next_results',reason='Previous list'))
            jobs.search=Mock(return_value=(1,[]))
            state={'stage':'choose_job','profile':{},'search_navigation':{'plan':{'schema_version':2},'shown_ids':['42']},
                   'training_navigation':{'topics':['ROS 2'],'delivery_mode':'online','shown_ids':['boottent:old']}}
            _,result,_=router.advance(state,{'action':'search','message':'이것 말고 또 볼 만한 건?'},invoke)
            self.assertEqual(planner.calls[0][0],'classify')
            if target=='jobs':
                jobs.search.assert_called_once();training.search.assert_not_called()
            else:
                training.search.assert_called_once_with(['ROS 2'],exclude_ids=['boottent:old'],delivery_mode='online')
                jobs.search.assert_not_called()
                self.assertEqual(state['conversation_target'],'training')

    def test_review_next_keeps_id_and_does_not_query(self):
        router,planner,jobs,training=self.fixture(dict(target='jobs',action='next_results',reason='Review pending'))
        jobs.search=Mock()
        state={'stage':'search_review','search_navigation':{'plan':{'schema_version':2},'shown_ids':[]},
               'search_context':{'search_id':'same','total':120,'summary':{}},'checks':[{'assessment':'unknown'}]}
        _,result,_=router.advance(state,{'action':'search','message':'딴거'},invoke)
        self.assertEqual(result['search_id'],'same');jobs.search.assert_not_called()
        self.assertEqual(state['checks'],[{'assessment':'unknown'}])

    def test_missing_previous_search_clarifies_without_execution(self):
        router,planner,jobs,training=self.fixture(dict(target='jobs',action='next_results',reason='Ambiguous'))
        jobs.search=Mock()
        _,result,_=router.advance({}, {'action':'search','message':'더'},invoke)
        self.assertTrue(result['clarification_required']);jobs.search.assert_not_called()

    def test_clarification_preserves_selected_checks_and_pending_plan(self):
        router,planner,_,_=self.fixture(dict(target='unspecified',action='clarify',reason='Ambiguous target',question='교육과 채용 중 어느 쪽인가요?'))
        state={'stage':'search_review','selected':{'source_id':'42'},'checks':[{'assessment':'unknown'}],
               'search_context':{'search_id':'keep'}}
        _,result,_=router.advance(state,{'action':'search','message':'다른 방향으로'},invoke)
        self.assertTrue(result['clarification_required']);self.assertEqual(state['search_context']['search_id'],'keep')
        self.assertEqual(state['selected']['source_id'],'42');self.assertEqual(state['stage'],'search_review')

    def test_explicit_next_button_has_zero_classifier_calls(self):
        router,planner,jobs,_=self.fixture({});jobs.search=Mock(return_value=(0,[]))
        state={'search_navigation':{'plan':{'schema_version':2},'shown_ids':['42']}}
        _,result,_=router.advance(state,{'action':'next_results','target':'jobs'},invoke)
        self.assertEqual(planner.calls,[]);self.assertTrue(result['search_continuation'])

    def test_chat_responds_without_search_or_legacy_route(self):
        router,planner,jobs,training=self.fixture(dict(target='general',action='chat',reason='Greeting'))
        jobs.search=Mock()
        _,result,_=router.advance({}, {'action':'search','message':'좋은 아침'},invoke)
        self.assertEqual([c[0] for c in planner.calls],['classify','respond'])
        jobs.search.assert_not_called();training.search.assert_not_called()
        self.assertIn('자기평가',result['message'])

    def test_training_next_excludes_source_aware_ids_and_keeps_mode(self):
        router,planner,_,training=self.fixture(dict(target='training',action='search',reason='Learn ROS',topics=['ROS 2'],delivery_mode='online'))
        training.search.side_effect=[[{'source':'boottent','source_id':'one','title':'Course','recommendation_eligible':False}],[]]
        state,first,_=router.advance({}, {'action':'search','message':'ROS2 온라인 교육'},invoke)
        planner.decision=dict(target='training',action='next_results',reason='Another course')
        _,second,_=router.advance(state,{'action':'search','message':'그거 말고'},invoke)
        self.assertEqual(second['learning_opportunities'],[])
        self.assertEqual(second['learning_search']['topics'],['ROS 2'])
        self.assertEqual(training.search.call_args.kwargs,{'exclude_ids':['boottent:one'],'delivery_mode':'online'})
        self.assertIn('없다는 뜻은 아닙니다',second['message'])

    def test_context_is_bounded_and_redacts_basic_secrets(self):
        state={'profile':{'memory':{'statements':[{'kind':'statement','text':'mail a@example.com token=private-value 010-1234-5678'}]*100}},'selected':{'source_id':'42','qualifications':'x'*50000}}
        value=routing_context(state);text=json.dumps(value)
        self.assertNotIn('private-value',text);self.assertNotIn('a@example.com',text);self.assertNotIn('010-1234-5678',text)
        self.assertNotIn('qualifications',value['selected_job']);self.assertEqual(len(value['recent_messages']),8)
        self.assertEqual(redact({'password':'secret'}),{'password':'[REDACTED]'})

class IntentAdapterTests(unittest.TestCase):
    def test_strict_json_classification_has_no_stream_and_explicit_budget(self):
        runtime=FakeRuntime(json.dumps(dict(target='jobs',action='next_results',reason='Previous jobs')))
        partial=Mock()
        with patch.dict(os.environ,{'ENABLE_LIVE_BEDROCK':'true'}):
            result,usage=BedrockPlanner('m','r',client=runtime,on_partial=partial).classify('딴거',{})
        self.assertEqual(result['decision']['action'],'next_results')
        self.assertEqual(runtime.calls[0]['inferenceConfig']['maxTokens'],1536)
        self.assertEqual(usage['prompt_version'],'context-intent-v2');partial.assert_not_called()

    def test_invalid_output_is_available_for_private_audit_only(self):
        runtime=FakeRuntime('not JSON')
        with patch.dict(os.environ,{'ENABLE_LIVE_BEDROCK':'true'}),self.assertRaises(ModelOutputFormatError) as error:
            BedrockPlanner('m','r',client=runtime).classify('안녕',{})
        self.assertEqual(error.exception.intent_raw_output,'not JSON')
        self.assertNotIn('not JSON',str(error.exception))

class IntentAuditTests(unittest.TestCase):
    def test_audit_owner_lease_and_attempt_and_raw_redaction(self):
        ticket={'session_id':'s','request_id':'r','owner':'o','state_version':2,'expires_at':None,'_intent_invocation_id':'i'}
        connection=MagicMock();cur=connection.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect=[{'state_version':2,'requirement_answers':{'_lease':{'request':'r'}}},{'n':3}]
        store=IntentDecisionStore(lambda:connection)
        identity=store.start(ticket,'model',{'stage':'conversation'})
        params=cur.execute.call_args.args[1]
        self.assertEqual(params[3],3);self.assertEqual(params[-2],'context-intent-v2')
        cur.fetchone.side_effect=[{'state_version':2,'requirement_answers':{'_lease':{'request':'r'}}}]
        store.classified(ticket,identity,'token=private-value a@example.com',{'action':'chat'})
        params=cur.execute.call_args.args[1]
        self.assertEqual(params[0],'i');self.assertNotIn('private-value',params[1]);self.assertNotIn('a@example.com',params[1])
        store.finish(ticket,identity,error='ModelOutputFormatError')
        self.assertEqual(cur.execute.call_args.args[1][0],'failed')
        self.assertEqual(cur.execute.call_args.args[1][-1],'o')

    def test_audit_wrong_lease_rolls_back_and_does_not_insert(self):
        connection=MagicMock();cur=connection.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value={'state_version':1,'requirement_answers':{'_lease':{'request':'other'}}}
        with self.assertRaises(Exception):IntentDecisionStore(lambda:connection).start({'session_id':'s','owner':'o','request_id':'r','state_version':1,'expires_at':None},'model',{})
        connection.rollback.assert_called_once();self.assertEqual(cur.execute.call_count,1)

class IntentEndpointTests(unittest.TestCase):
    def run_request(self,fail=False):
        planner=Planner(dict(target='general',action='chat',reason='Greeting'))
        if fail:
            error=ModelOutputFormatError({});error.intent_raw_output='invalid-private-output'
            planner.classify=Mock(side_effect=error)
        store=MagicMock();audit=MagicMock();audit.start.return_value='audit-id'
        sid,rid=str(uuid4()),str(uuid4())
        store.begin.return_value={'state':{},'session_id':sid,'request_id':rid,'owner':'owner','state_version':0}
        store.begin_invocation.return_value='invoke-id'
        store.finish.side_effect=lambda ticket,payload,state,result,evidence:result
        token='test-token-'+'x'*40
        event={'headers':{'Authorization':'Bearer '+token,'X-Client-Token':'a'*64},'body':json.dumps({'action':'search','message':'안녕','request_id':rid})}
        with patch.dict(os.environ,{'CHAT_API_TOKEN':token,'CHAT_RETENTION_HOURS':'24','CONTEXT_ROUTING_ENABLED':'true'}):
            result=handle_request(event,jobs=Jobs(),store=store,planner=planner,questioner=Questioner(),training=Mock(),intent_store=audit)
        return result,store,audit

    def test_endpoint_records_classification_and_execution_separately(self):
        result,store,audit=self.run_request()
        self.assertEqual(result['statusCode'],200)
        self.assertEqual(store.begin_invocation.call_args_list[0].args[1],'intent_classification')
        self.assertEqual(store.begin_invocation.call_args_list[1].args[1],'context_response')
        self.assertEqual(audit.classified.call_args.args[3]['action'],'chat')
        self.assertIn('result',audit.finish.call_args.kwargs)

    def test_failure_audit_survives_chat_abort_and_no_raw_in_public_error(self):
        result,store,audit=self.run_request(fail=True)
        self.assertEqual(result['statusCode'],502);store.abort.assert_called_once()
        self.assertFalse(audit.classified.call_args.kwargs['valid'])
        self.assertIn('error',audit.finish.call_args.kwargs)
        self.assertNotIn('invalid-private-output',result['body'])

    def test_button_request_contracts_are_strict(self):
        base={'request_id':str(uuid4()),'session_id':str(uuid4())}
        validate_payload(dict(base,action='next_results',target='training'))
        validate_payload(dict(base,action='assessment_control',control='stop'))
        for value in [dict(action='next_results',target='other'),dict(action='assessment_control',control='delete'),dict(action='next_results',target='jobs',sql='select')]:
            with self.assertRaises(ValueError):validate_payload(dict(base,**value))


class AdditionalIntentTests(unittest.TestCase):
    fixture = ContextRoutingTests.fixture
    def test_nested_career_patch_does_not_erase_existing_levels(self):
        original=SearchPlan(schema_version=2,career={'levels':['junior'],'max_years':3})
        result=merge_search(original.to_dict(),SearchChanges.model_validate({'career':{'max_years':5}}))
        self.assertEqual(result.career.levels,('junior',));self.assertEqual(result.career.max_years,5)

    def test_stop_before_selection_is_honored_without_questioning(self):
        router,_,_,_=self.fixture(dict(target='selected',action='assessment_control',control='stop',reason='User refuses assessment'))
        state,result,_=router.advance({}, {'action':'search','message':'역량 질문하지마'},invoke)
        self.assertFalse(state['profile']['assistant_preferences']['ask_assessment'])
        self.assertTrue(result['assessment_paused'])

    def test_model_search_cannot_be_overridden_by_legacy_phrase_rules(self):
        router,planner,jobs,_=self.fixture(dict(target='jobs',action='search',reason='Explicit selected intent',plan={'schema_version':2,'owned_skills':['Python']}))
        state,result,_=router.advance({}, {'action':'search','message':'이력서 상담 말고 공고 찾아줘'},invoke)
        self.assertIn('candidate_jobs',result)
        self.assertEqual([c[0] for c in planner.calls],['classify'])

    def test_sensitive_json_raw_output_is_masked_even_on_invalid_contract(self):
        text=redact('{"token":"private-token","email":"a@example.com"}')
        self.assertNotIn('private-token',text);self.assertNotIn('a@example.com',text)
        broken=redact('{"token":"private-token",broken')
        self.assertNotIn('private-token',broken)

    def test_training_exclusions_apply_before_repository_limit_and_fallback(self):
        from src.repositories.mysql_training import MySQLTrainingRepository
        from src.repositories.elasticsearch_training import build_training_query
        from src.repositories.search_failover import SearchFailover, SearchUnavailable
        conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value;cur.fetchall.return_value=[]
        MySQLTrainingRepository(lambda:conn).search(['ROS 2'],exclude_ids=['boottent:old'],delivery_mode='online')
        sql,params=cur.execute.call_args.args
        self.assertIn('AND NOT ((source=%s AND source_id=%s))',sql)
        self.assertEqual(params[-3:],['boottent','old','online'])
        query=build_training_query(['ROS 2'],exclude_ids=['boottent:old'],delivery_mode='online')
        self.assertIn({'term':{'delivery_mode':'online'}},query['query']['bool']['filter'])
        primary,fallback=Mock(),Mock();primary.search.side_effect=SearchUnavailable();fallback.search.return_value=[]
        SearchFailover(primary,fallback,entity='training').search(['ROS 2'],exclude_ids=['boottent:old'],delivery_mode='online')
        fallback.search.assert_called_once_with(['ROS 2'],exclude_ids=['boottent:old'],delivery_mode='online')


class FixedIntentCaseTests(unittest.TestCase):
    def test_fixed_synthetic_case_contracts_and_same_phrase_different_contexts(self):
        from pathlib import Path
        rows=json.loads((Path(__file__).parents[1]/'experiments/context_intent/cases.json').read_text(encoding='utf-8'))
        self.assertEqual(len(rows),21)
        self.assertEqual(len({r['id'] for r in rows}),21)
        for row in rows:IntentDecision.model_validate(row['expected'])
        same=[r for r in rows if r['message']=='딴거']
        self.assertEqual({r['expected']['target'] for r in same},{'jobs','training','unspecified'})


class IntentV2BoundaryTests(unittest.TestCase):
    def test_model_schema_contains_no_legacy_search_fields(self):
        schema=IntentDecision.model_json_schema()
        definition=schema['$defs']['IntentJobPlan']
        self.assertFalse({'keyword','region','skills'} & set(definition['properties']))
        self.assertEqual(definition['properties']['schema_version']['const'],2)
        self.assertFalse(definition['additionalProperties'])
        self.assertNotIn('SearchPlan',schema['$defs'])

    def test_valid_v2_executes_but_mixed_real_failure_shape_is_rejected(self):
        plan={'schema_version':2,'target':'jobs','roles':['백엔드'],'owned_skills':['Python','Docker']}
        value=IntentDecision.model_validate({'target':'jobs','action':'search','reason':'Synthetic QA','plan':plan})
        execution=value.plan.as_search_plan()
        self.assertEqual(execution.keyword,'')
        self.assertEqual(execution.roles,('백엔드',))
        with self.assertRaises(ValueError):
            IntentDecision.model_validate({'target':'jobs','action':'search','reason':'Synthetic QA','plan':dict(plan,keyword='백엔드')})
