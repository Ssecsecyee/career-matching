"""Synthetic source layouts only; no collected job data or model calls."""
import copy
import json
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

from src.services.condition_structure import structure_conditions, validate_conditions, source_notice
from src.services.memory import memory, condition_key, consultation_context
from src.services.condition_display import display_condition
from src.services.dialogue import DialogueFlow, FlowError
from src.repositories.mysql_chat import MySQLChatStore
from test_dialogue import Jobs, Questioner, invoke


SOURCE=('ㆍ외국어 문서 읽기 경험\n'
        'ㆍ분석 플랫폼 A 경험\n'
        'ㆍ로그 도구 B 또는 C 경험\n'
        'ㆍ시각화 도구 활용 경험\n'
        'ㆍHTML / SQL 이해\n'
        'ㆍ문서 작성 도구 활용\n'
        'ㆍ협업 및 정보 공유 경험\n'
        'ㆍ관련 프로젝트 참여 경험\n\n'
        '* 추가 기술스택\n\nPython\nSQL\nGit')


class ConditionStructureTests(unittest.TestCase):
    def split(self,text=SOURCE):
        return structure_conditions(text,'preferred','42',2)

    def test_araea_bullets_are_individual_but_additional_stack_stays_a_collection(self):
        rows=self.split()
        self.assertEqual(len(rows),9)
        self.assertTrue(all(r['quote'].startswith('ㆍ') for r in rows[:8]))
        self.assertIn('B 또는 C',rows[2]['quote'])
        self.assertIn('Python\nSQL\nGit',rows[-1]['quote'])
        self.assertEqual(rows[-1]['parse_notes'],['technical_collection'])
        self.assertIn('개별 기술',source_notice(rows[-1])['source_notice'])
        self.assertTrue(validate_conditions(SOURCE,rows))

    def test_exact_crlf_indentation_blank_lines_and_unicode_offsets_survive(self):
        text='  ㆍ분석 경험😀\r\n    (도구 A 또는 B)\r\n\r\n  ㆍ경력 3년 이상\r\n'
        rows=self.split(text)
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['quote'],'  ㆍ분석 경험😀\r\n    (도구 A 또는 B)')
        self.assertTrue(validate_conditions(text,rows))
        for row in rows:
            self.assertEqual(row['quote'],''.join(text[s['start']:s['end']] for s in row['source_spans']))

    def test_alternative_and_parenthesized_subitems_are_not_independent_requirements(self):
        text='ㆍPython 개발 경험\nㆍ또는 Java 개발 경험\nㆍ관련 경력 3년 이상 또는 이에 준하는 역량\nㆍ도구 경험 (다음 중 하나:\nㆍ도구 A\nㆍ도구 B)\nㆍ협업 경험'
        rows=self.split(text)
        self.assertEqual(len(rows),4)
        self.assertIn('ㆍ또는 Java',rows[0]['quote'])
        self.assertIn('이에 준하는 역량',rows[1]['quote'])
        self.assertIn('ㆍ도구 B)',rows[2]['quote'])
        self.assertTrue(validate_conditions(text,rows))

    def test_indented_child_bullets_keep_the_parent_and_do_not_merge_next_peer(self):
        text='ㆍ도구 경험\n  - 도구 A\n  - 도구 B\nㆍ협업 경험'
        rows=self.split(text)
        self.assertEqual(len(rows),2)
        self.assertIn('  - 도구 B',rows[0]['quote'])
        self.assertIn('nested_items',rows[0]['parse_notes'])

    def test_shared_headings_are_exact_context_not_new_questions(self):
        text='* 자격요건\n* 학력\n- 학사 또는 이에 준하는 경력\n* 경력\n- 신입 또는 경력 2년 이하\n- 관련 프로젝트 경험'
        rows=self.split(text)
        self.assertEqual(len(rows),3)
        self.assertTrue(rows[0]['quote'].startswith('* 자격요건\n* 학력\n'))
        self.assertTrue(rows[-1]['quote'].startswith('* 경력\n'))
        self.assertTrue(validate_conditions(text,rows))

    def test_unmarked_paragraph_is_conservatively_grouped_and_inline_dots_not_split(self):
        text='도구 AㆍB 경험\n프로젝트를 수행한 경험'
        rows=self.split(text)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['quote'],text)
        self.assertIn('unmarked_multiline',rows[0]['parse_notes'])

    def test_heading_only_or_dangling_heading_falls_back_without_losing_text(self):
        for text in ('* 학력','ㆍ분석 경험\n* 경력'):
            rows=self.split(text)
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['quote'],text)
            self.assertEqual(rows[0]['parse_notes'],['fallback_whole_section'])

    def test_unclosed_parenthesis_keeps_ambiguous_source_together(self):
        rows=self.split('ㆍ개발 경험 (도구 A\nㆍ또 다른 항목')
        self.assertEqual(len(rows),1)
        self.assertIn('unbalanced_delimiter',rows[0]['parse_notes'])

    def test_source_mutation_missing_duplicate_and_overlapping_bodies_are_rejected(self):
        original=self.split('ㆍ조건 A\nㆍ조건 B')
        changed=copy.deepcopy(original);changed[0]['quote']='변경된 조건'
        duplicate=copy.deepcopy(original);duplicate[1]['source_spans']=copy.deepcopy(duplicate[0]['source_spans']);duplicate[1]['quote']=duplicate[0]['quote']
        for rows in (changed,duplicate,original[:1]):
            with self.assertRaises(ValueError):validate_conditions('ㆍ조건 A\nㆍ조건 B',rows)
        with self.assertRaises(ValueError):validate_conditions('ㆍ조건 C\nㆍ조건 B',original)

    def test_ids_are_stable_and_change_for_parser_source_or_version(self):
        first=self.split('ㆍ조건 A')
        self.assertEqual(first,self.split('ㆍ조건 A'))
        self.assertNotEqual(first[0]['id'],structure_conditions('ㆍ조건 A','preferred','42',3)[0]['id'])
        self.assertNotEqual(first[0]['id'],self.split('ㆍ조건 A\nㆍ조건 B')[0]['id'])
        with patch('src.services.condition_structure.PARSER_VERSION','future-parser'):
            self.assertNotEqual(first[0]['id'],self.split('ㆍ조건 A')[0]['id'])

    def test_numbered_conditions_without_spaces_are_individual_and_lossless(self):
        items=['1.프런트엔드 실무 경력 3~4년','2.React 기반 개발 경험',
               '3.Next.js(12~13+) 기반 SSR/CSR 개발 경험','4.Typescript 기반 개발 능력',
               '5.REST API 연동 및 상태관리(Recoil/Redux/React-Query 중 1개 이상)',
               '6.MUI 또는 styled-components 기반 UI 개발 경험','7.HTML/CSS/반응형 UI 구현 능력',
               '8.Git 기반 협업 경험','9.WebView 기반 모바일 앱 화면 구현 경험',
               '10.모바일 UI/UX 및 반응형 구조 설계 경험']
        for separator in ('\n','\r\n',' '):
            text=separator.join(items);rows=self.split(text)
            self.assertEqual(len(rows),10)
            self.assertEqual([r['quote'].strip() for r in rows],items)
            self.assertTrue(validate_conditions(text,rows))

    def test_inline_numbers_do_not_split_versions_or_parenthesized_choices(self):
        for text in ('Python 3.12 및 Node 20.1 경험',
                     '1.React 경험 (예: 1.웹 2.앱) 2.Git 경험',
                     '1.Python 개발 2.또는 Java 개발'):
            rows=self.split(text)
            self.assertTrue(validate_conditions(text,rows))
            self.assertEqual(len(rows),2 if '2.Git' in text else 1)

    def test_empty_and_guarded_large_source(self):
        self.assertEqual(self.split(' \r\n'),[])
        with self.assertRaises(ValueError):self.split('\n'.join('ㆍ조건 '+str(i) for i in range(41)))

    def test_compact_display_removes_bullet_without_modifying_original(self):
        row=self.split('ㆍPython 또는 Java 경험')[0]
        self.assertEqual(display_condition(row['quote'])['summary'],'Python 또는 Java 경험')
        self.assertEqual(row['quote'],'ㆍPython 또는 Java 경험')


class ConditionAnswerBindingTests(unittest.TestCase):
    def setUp(self):
        self.jobs=Jobs()
        self.jobs.job['qualifications']='ㆍ관련 경험'
        self.jobs.job['preferred_requirements']=SOURCE
        self.flow=DialogueFlow(self.jobs,None,Questioner(),include_unverified=True)

    def select(self,state=None):
        state=state or {}
        state['candidate_ids']=['42']
        return self.flow.advance(state,{'action':'select','source_id':'42','grouped':True},invoke)

    def test_batch_check_and_evidence_keep_source_binding_and_unknown_detail(self):
        state,result,_=self.select()
        answers=[{'question_id':q['question_id'],'assessment':'met','detail':''} for q in result['questions']]
        state,result,_=self.flow.advance(state,{'action':'answer_batch','answers':answers},invoke)
        self.assertEqual(len(result['questions']),5)
        answers=[{'question_id':q['question_id'],'assessment':'unknown','detail':'일부만 해당됩니다.'} for q in result['questions']]
        state,_,evidence=self.flow.advance(state,{'action':'answer_batch','answers':answers},invoke)
        self.assertEqual(evidence[0]['check']['assessment'],'unknown')
        self.assertEqual(evidence[0]['check']['detail'],'일부만 해당됩니다.')
        self.assertIn('source_spans',evidence[0]['check'])
        self.assertTrue(all('parser_version' in c for c in state['checks']))

    def test_old_grouped_and_even_identical_legacy_answers_are_not_inherited(self):
        old={'source_id':'42','source_version':1,'assessment':'met','detail':'일부 경험',
             'quote':'ㆍ관련 경험','type':'required'}
        state={}
        memory(state)['confirmed'][condition_key('required','ㆍ관련 경험')]=old
        memory(state)['confirmed'][condition_key('preferred',SOURCE)]=dict(old,quote=SOURCE,type='preferred')
        state,result,_=self.select(state)
        self.assertEqual(state['checks'],[])
        self.assertEqual(result['progress']['answered'],0)
        self.assertEqual(result['progress']['total'],10)

    def test_old_question_ids_are_rejected_after_reselection(self):
        state,_,_=self.select()
        with self.assertRaises(FlowError):
            self.flow.advance(state,{'action':'answer_batch','answers':[{'question_id':'42:1:required:0','assessment':'met','detail':''}]},invoke)

    def test_existing_legacy_session_finishes_its_own_original_without_reparsing(self):
        original='ㆍ조건 A\nㆍ조건 B'
        state={'stage':'checking_preferred','selected':copy.deepcopy(self.jobs.job),'grouped':True,
            'conditions':[{'id':'legacy-p','key':condition_key('preferred',original),'type':'preferred','section':'preferred_requirements','quote':original}], 'checks':[]}
        state,result,_=self.flow.advance(state,{'action':'answer_batch','answers':[{'question_id':'legacy-p','assessment':'unknown','detail':'일부만 해당'}]},invoke)
        self.assertEqual(len(state['conditions']),1)
        self.assertEqual(state['checks'][0]['condition_id'],'legacy-p')
        self.assertEqual(state['checks'][0]['assessment'],'unknown')
        self.assertEqual(result['answer_summary']['total'],1)

    def test_same_new_parser_confirmation_can_still_be_reused(self):
        state,result,_=self.select()
        state,_,_=self.flow.advance(state,{'action':'answer_batch','answers':[{'question_id':q['question_id'],'assessment':'met','detail':'확인'} for q in result['questions']]},invoke)
        # Switch to individual mode so the existing reuse path is exercised.
        state['candidate_ids']=['42']
        state,result,_=self.flow.advance(state,{'action':'select','source_id':'42'},invoke)
        self.assertTrue(state['checks'][0]['reused'])
        self.assertEqual(result['requirement_type'],'preferred')

    def test_collection_notice_reaches_the_counseling_context(self):
        row=structure_conditions('* 추가 기술스택\nPython\nSQL','preferred','42',1)[0]
        check=self.flow.make_check(row,'met','')
        state={'checks':[check]}
        context=consultation_context(state)
        self.assertIn('개별 기술',context['condition_answers'][0]['source_notice'])

    def test_evidence_snapshot_persists_span_and_rule_metadata_in_same_transaction(self):
        state,result,_=self.select()
        state,result,evidence=self.flow.advance(state,{'action':'answer_batch','answers':[{'question_id':q['question_id'],'assessment':'met','detail':''} for q in result['questions']]},invoke)
        cursor=MagicMock();cursor.__enter__.return_value=cursor;cursor.fetchone.return_value={'n':1}
        connection=MagicMock();connection.cursor.return_value=cursor
        store=MySQLChatStore(lambda:connection,retention_hours=24)
        ticket={'session_id':'test-session','request_id':'test-request','owner':'test-owner','state_version':0,
                'fingerprint':'test','cache_key':'test','expires_at':datetime.utcnow()+timedelta(hours=24)}
        with patch.object(store,'_lock_ticket'):
            store.finish(ticket,{'action':'answer_batch'},state,result,evidence)
        args=next(c.args[1] for c in cursor.execute.call_args_list if c.args[0].startswith('INSERT INTO recommendation_evidence'))
        snapshot=json.loads(args[5])
        self.assertEqual(snapshot['source_binding']['parser_version'],'condition-split-v3')
        self.assertTrue(snapshot['source_binding']['source_spans'])
        self.assertEqual(snapshot['quote'],evidence[0]['check']['quote'])
        connection.commit.assert_called_once()
