import copy,json,os,unittest
from unittest.mock import Mock,patch
from test_condition_review import fixture,FakeRuntime
from src.services.condition_review import source_conditions,source_parts,review_key,validate_review,projection
from src.bedrock.condition_classifier import ConditionClassifier
from src.bedrock.model_json import ModelOutputFormatError

class ExtractionV2Tests(unittest.TestCase):
    def test_full_part_coverage_cannot_drop_duplicate_or_invent_units(self):
        job,proposal=fixture()
        for kind in ('missing','duplicate','unknown','term'):
            p=copy.deepcopy(proposal)
            if kind=='missing':p['conditions'][1]['parts']=[]
            if kind=='duplicate':p['conditions'][1]['parts']*=2
            if kind=='unknown':p['conditions'][1]['parts'][0]['part_id']='0'*16
            if kind=='term':p['conditions'][1]['parts'][0]['terms']=['AWS']
            with self.assertRaises(ValueError):validate_review(job,p)
    def test_thirteen_terms_survive_unresolved_logic_and_es_projection(self):
        job,p=fixture();terms=['R','PostgreSQL','PL/SQL','Pandas','OracleDB','Node.js','Kotlin','Objective-C','jQuery','ECMAScript','iOS','HTML5','AWS']
        job['qualifications']='';job['preferred_requirements']='* 추가 기술스택\n'+'\n'.join(terms)
        condition=source_conditions(job)[0]
        item=dict(p['conditions'][2],condition_id=review_key(condition),treatment='review',reason_code='ambiguous',logic={'operator':'unresolved'})
        item['parts']=[{'part_id':part['part_id'],'terms':[t for t in terms if part['quote'].strip()==t]} for part in source_parts(condition)]
        review=validate_review(job,{'conditions':[item]});parts=review['conditions'][0]['parts']
        self.assertEqual(''.join(x['quote'] for x in parts),condition['quote'])
        self.assertEqual(projection(job,review)['preferred_condition_terms'],terms)
        self.assertEqual(len(projection(job,review)['classified_conditions'][0]['atoms']),13)
    def test_language_skill_cannot_be_hidden_as_subjective_trait(self):
        job,p=fixture();p['conditions'][2].update(treatment='reference',reason_code='subjective_trait',category='skill')
        with self.assertRaises(ValueError):validate_review(job,p)

    def test_forced_tool_contract_and_no_text_fallback(self):
        job,p=fixture();runtime=FakeRuntime(json.dumps(p))
        with patch.dict(os.environ,{'ENABLE_LIVE_BEDROCK':'true'}):ConditionClassifier('offline','test',client=runtime).classify(job)
        self.assertEqual(runtime.calls[0]['toolConfig']['toolChoice'],{'tool':{'name':'submit_condition_review'}})
        bad=Mock();bad.converse.return_value={'stopReason':'end_turn','output':{'message':{'content':[{'text':json.dumps(p)}]}},'usage':{}}
        with patch.dict(os.environ,{'ENABLE_LIVE_BEDROCK':'true'}),self.assertRaises(ModelOutputFormatError):ConditionClassifier('offline','test',client=bad).classify(job)
    def test_late_batch_failure_does_not_return_partial_review_and_keeps_usage(self):
        job,p=fixture();job['qualifications']='\n'.join('- Python 경험' for _ in range(7));job['preferred_requirements']=''
        runtime=Mock();calls=[]
        def respond(**kw):
            batch=json.loads(kw['messages'][0]['content'][0]['text'])['conditions'];calls.append(batch)
            if len(calls)==2:return {'stopReason':'end_turn','usage':{'inputTokens':5,'outputTokens':2},'output':{'message':{'content':[]}}}
            items=[]
            for source in batch:
                item=dict(p['conditions'][2],condition_id=source['condition_id'],logic={'operator':'atom','term':'Python','evidence':'Python'})
                item['parts']=[{'part_id':part['part_id'],'terms':['Python']} for part in source['parts']];items.append(item)
            return {'stopReason':'tool_use','usage':{'inputTokens':5,'outputTokens':2},'output':{'message':{'content':[{'toolUse':{'name':'submit_condition_review','input':{'conditions':items}}}]}}}
        runtime.converse.side_effect=respond
        with patch.dict(os.environ,{'ENABLE_LIVE_BEDROCK':'true'}),self.assertRaises(ModelOutputFormatError) as caught:ConditionClassifier('offline','test',client=runtime).classify(job)
        self.assertEqual(len(calls),2);self.assertEqual(caught.exception.usage['input_tokens'],10)
