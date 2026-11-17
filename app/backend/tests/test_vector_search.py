import hashlib
import json
import unittest
from unittest.mock import patch
from src.services.vector_search import run, audit_payload, validate_text, local_query
from src.services.dialogue import FlowError
from src.handlers.dialogue import validate_payload

class Jobs:
 def __init__(self,row):self.row=row
 def get(self,identity):return self.row

class VectorSearchTests(unittest.TestCase):
 def setUp(self):
  self.row={'source':'jumpit','source_id':'00123','source_version':2,'title':'Backend','qualifications':'Python 또는 Java','preferred_requirements':'Docker','recruitment_status':'unknown'}
  self.candidate={'source':'jumpit','source_id':'00123','source_version':'2','scores':{'qualifications':.8},'section_hashes':{s+'_hash':hashlib.sha256(self.row[s].encode()).hexdigest() for s in ('qualifications','preferred_requirements')}}
 def query(self,text):return {'results':[self.candidate],'input_tokens':50}
 def test_preserves_selection_and_no_raw_text_in_state(self):
  state={'selected':{'source_id':'older'},'checks':[{'assessment':'met'}],'search_context':{'old':True}}
  state,result,_=run(state,'private experience',Jobs(self.row),include_unverified=True,query=self.query)
  self.assertEqual(state['selected']['source_id'],'older');self.assertEqual(state['candidate_ids'],['00123'])
  self.assertNotIn('private experience',json.dumps(state));self.assertEqual(result['total'],1)
  self.assertNotIn('search_context',state)
 def test_changed_version_or_content_excluded(self):
  for field,value in [('source_version',3),('qualifications','Changed')]:
   row=dict(self.row,**{field:value})
   self.assertEqual(run({},'Python',Jobs(row),include_unverified=True,query=self.query)[1]['total'],0)
 def test_closed_or_expired_excluded(self):
  for extra in ({'recruitment_status':'closed'},{'deadline_at':'2020-01-01T00:00:00Z'}):
   self.assertEqual(run({},'Python',Jobs(dict(self.row,**extra)),include_unverified=True,query=self.query)[1]['total'],0)
 def test_audit_contains_only_digest_and_size(self):
  p=audit_payload({'action':'vector_search','text':'비공개 경험','request_id':'id'})
  self.assertNotIn('text',p);self.assertEqual(len(p['text_sha256']),64)
  self.assertNotEqual(p['text_sha256'],audit_payload({'action':'vector_search','text':'다른 경험'})['text_sha256'])
 def test_payload_and_size_validation(self):
  self.assertEqual(validate_payload({'action':'vector_search','text':'Python','request_id':'00000000-0000-4000-8000-000000000001'})['action'],'vector_search')
  for text in ('','  ','a\0b','가'*7000):
   with self.assertRaises(ValueError):validate_text(text)
 def test_feature_disabled_does_not_invoke_model(self):
  with patch.dict('os.environ',{'ENABLE_TXT_VECTOR_SEARCH':'false'}),patch('subprocess.run') as process:
   with self.assertRaises(FlowError):local_query('Python')
   process.assert_not_called()

if __name__=='__main__':unittest.main()
