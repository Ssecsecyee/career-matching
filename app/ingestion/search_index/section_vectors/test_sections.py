import json,math,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
import local_sections as local
import pilot
class ContractTests(unittest.TestCase):
 def setUp(self):self.row={'source':'jumpit','source_id':'00123','source_version':'2','qualifications':'Python 또는 R 활용 가능\n학사 또는 동등 경력','preferred_requirements':'AWS 배포 경험'}
 def test_two_whole_sections_keep_or_and_lines(self):
  r=local.section_records(self.row,'key');self.assertEqual(len(r),2);self.assertEqual(r[0]['text'],self.row['qualifications']);self.assertEqual(r[1]['section'],'preferred_requirements')
 def test_external_id_stays_string(self):self.assertEqual(local.section_records(self.row,'key')[0]['source_id'],'00123')
 def test_empty_section_not_zero_vector(self):
  self.row['preferred_requirements']=' ';self.assertEqual(len(local.section_records(self.row,'key')),1)
 def test_cache_changes_when_original_changes(self):
  old=local.section_records(self.row,'key')[0];self.row['qualifications']+=' 수정';new=local.section_records(self.row,'key')[0];self.assertNotEqual(old['cache_key'],new['cache_key'])
 def test_vectors_are_finite_and_normalized(self):
  v=[1.0]+[0.0]*767;self.assertEqual(local.valid_vector(v),v)
  for bad in ([0.0]*768,[float('nan')]+[0.0]*767,[1.0]*10):
   with self.assertRaises(ValueError):local.valid_vector(bad)
 def test_vector_mapping_does_not_change_live_keyword_index(self):
  m=pilot.mapping();self.assertEqual(m['mappings']['properties']['qualifications_vector']['dims'],768);self.assertTrue(m['mappings']['_meta']['pilot']);self.assertFalse(m['mappings']['properties']['qualifications']['index'])
 def test_stale_or_deleted_source_excluded(self):
  current={'found':True,'_source':dict(self.row,source_version='3')}
  with patch.object(pilot,'es',return_value={'docs':[current]}):self.assertEqual(pilot.verify_source([('id',self.row)]),[])
  with patch.object(pilot,'es',return_value={'docs':[{'found':False}]}):self.assertEqual(pilot.verify_source([('id',self.row)]),[])
 def test_whole_input_limit_no_session_call(self):
  e=local.LocalEmbedder.__new__(local.LocalEmbedder);e.max_tokens=3
  class Tokenizer:
   def encode(self,text):
    class Tokens:ids=[1,2,3,4]
    return Tokens()
  e.tokenizer=Tokenizer()
  with self.assertRaisesRegex(ValueError,'input_exceeds_token_limit'):e.encode('긴 원문은 잘라내면 안 됩니다')
if __name__=='__main__':unittest.main()
