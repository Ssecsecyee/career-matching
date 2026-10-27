import copy
import json
import unittest
from src.services.memory import memory, record, consultation_context, restore_user_statements
from src.services.dialogue import DialogueFlow
from test_dialogue import Jobs, Questioner, invoke

class Router:
    def __init__(self):self.history=None
    def route(self,message,history):
        self.history=copy.deepcopy(history)
        return {'intent':'chat','reply':'저장된 답변을 기준으로 정리할게요.'},{}

class CounselingTests(unittest.TestCase):
    def fixture(self):
        state={'stage':'gap_guidance','selected':{'source_id':'42','source_version':1,'company_name':'test','title':'프론트엔드'},'conditions':[{}]*13,'checks':[]}
        record(state,'포토샵과 일러스트 경험이 있어요')
        record(state,'신입이고 패션 프리랜서 경험이 있어요. 지역은 무관해요')
        record(state,'React 사용 가능해요')
        for i in range(13):
            state['checks'].append({'condition_id':str(i),'type':'required' if i<6 else 'preferred','assessment':'unmet','quote':'React 경험' if i==1 else '조건 '+str(i),'detail':''})
            record(state,'조건 '+str(i)+' 미충족','answer')
        return state

    def test_all_required_and_preferred_reach_counseling_not_only_last_four(self):
        state=self.fixture();router=Router()
        _,result,_=DialogueFlow(Jobs(),router,Questioner()).advance(state,{'action':'search','message':'지금까지 뭐가 부족한지 정리해줘'},invoke)
        self.assertEqual(len(router.history['condition_answers']),13)
        self.assertEqual(router.history['assessment_summary']['counts']['required']['unmet'],6)
        self.assertEqual(router.history['selected_job']['source_id'],'42')
        self.assertTrue(any('신입' in x['text'] for x in router.history['user_statements']))
        self.assertTrue(any('React 사용 가능' in x['text'] for x in router.history['user_statements']))
        self.assertEqual(router.history['condition_answers'][1]['assessment'],'unmet')
        self.assertEqual(result['stage'],'conversation')

    def test_user_statements_survive_eighty_checklist_records(self):
        state={};record(state,'신입입니다')
        for i in range(80):record(state,'답변 '+str(i),'answer')
        self.assertFalse(any('신입' in x['text'] for x in memory(state)['statements']))
        self.assertIn('신입',consultation_context(state)['user_statements'][0]['text'])

    def test_existing_session_restores_original_user_payloads_only(self):
        state={}
        restore_user_statements(state,[(1,{'action':'search','message':'신입이고 포토샵을 사용합니다'}),
            (3,{'action':'select','source_id':'42'}),(5,{'action':'answer_batch','answers':[{'assessment':'unmet','detail':'React는 기초만 알아요'}]}),
            (7,{'action':'remember','message':'정정할게요. 실무 경험은 없어요'})])
        rows=consultation_context(state)['user_statements']
        self.assertEqual(len(rows),3)
        self.assertEqual(rows[-1]['kind'],'correction')
        self.assertNotIn('source_id',json.dumps(rows))

    def test_general_chat_never_reuses_no_results_or_candidate_screen(self):
        for stage in ('no_results','choose_job'):
            state={'stage':stage,'candidate_ids':['42'],'candidate_jobs':[{'source_id':'42'}],'total':1}
            _,result,_=DialogueFlow(Jobs(),Router(),Questioner()).advance(state,{'action':'search','message':'안녕'},invoke)
            self.assertEqual(result['stage'],'conversation')
            self.assertNotIn('candidate_jobs',result)
            self.assertEqual(state['candidate_ids'],['42'])

    def test_large_input_keeps_all_statuses_and_marks_shortened_text(self):
        state=self.fixture()
        state['checks']*=6
        for row in state['checks']:row.update(quote='긴 원문'*200,detail='긴 설명'*500)
        result=consultation_context(state)
        self.assertEqual(len(result['condition_answers']),78)
        self.assertTrue(result['context_limits']['condition_text_shortened'])
        self.assertLessEqual(len(json.dumps(result,ensure_ascii=False)),60000)
        self.assertEqual(memory({})['statements'],[])
