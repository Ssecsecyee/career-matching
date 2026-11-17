import json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
from src.schemas.search import SearchPlan
from src.schemas.intent import IntentDecision
from src.repositories.jobs import JsonJobRepository
from src.repositories.elasticsearch_jobs import build_query
from src.repositories.elasticsearch_training import build_training_query
from src.repositories.search_failover import SearchFailover,SearchUnavailable
from src.services.search_sql import structured_clauses

class AndPolicyTests(unittest.TestCase):
 def test_different_conditions_require_all_and_spelling_aliases_still_work(self):
  rows=[{'source_id':'1','source':'jumpit','recruitment_status':'unknown','title':'백엔드 데이터 엔지니어','addresses':['경기도 수원'],'tech_stacks':['Python','Docker']},
        {'source_id':'2','source':'jumpit','recruitment_status':'unknown','title':'백엔드 개발자','addresses':['경기도 수원'],'tech_stacks':['Python']}]
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'jobs.json';path.write_text(json.dumps(rows),encoding='utf-8')
   repo=JsonJobRepository(path,include_unverified=True)
   plan=SearchPlan(regions=['경기'],roles=['백엔드','데이터 엔지니어'],required_skills=['Python','Docker'])
   total,found=repo.search(plan);self.assertEqual(total,1);self.assertEqual(found[0]['source_id'],'1')
   self.assertEqual(repo.search(SearchPlan(regions=['경기','부산']))[0],0)
  clauses,_,_,_=structured_clauses(plan);self.assertEqual(len(clauses),5)
  filters=build_query(plan)['query']['bool']['filter'];self.assertEqual(len(filters),7)
 def test_training_model_has_no_or_value_and_missing_operator_means_and(self):
  with self.assertRaises(ValueError):IntentDecision(target='training',action='search',reason='test',topics=['A','B'],topic_operator='or')
  for options in ({},{'topic_operator':'and'},{'topic_operator':'or'}):
   query=build_training_query(['Python','포트폴리오'],**options)['query']['bool']
   self.assertEqual(query['minimum_should_match'],2)
 def test_training_fallback_cannot_reintroduce_legacy_or(self):
  primary=Mock();primary.search.side_effect=SearchUnavailable();fallback=Mock();fallback.search.return_value=[]
  SearchFailover(primary,fallback,entity='training').search(['A','B'],topic_operator='or')
  fallback.search.assert_called_once_with(['A','B'],topic_operator='and')
