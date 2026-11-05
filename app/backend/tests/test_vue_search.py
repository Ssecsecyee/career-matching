"""Spelling equivalence in structured search; no live model or source changes."""
import json,tempfile,unittest
from pathlib import Path
from src.services.search_terms import skill_terms,matches_skill
from src.services.search_sql import structured_clauses
from src.schemas.search import SearchPlan
from src.repositories.elasticsearch_jobs import build_query
from src.repositories.jobs import JsonJobRepository

class VueSearchTests(unittest.TestCase):
    def test_spellings_are_symmetric_case_insensitive_but_not_other_technologies(self):
        for term in ('Vue','vue','VUE','Vue.js','vuejs','VueJs'):
            self.assertEqual(skill_terms(term),('Vue','Vue.js','VueJs'))
            for tag in ('Vue','Vue.js','VueJs'):self.assertTrue(matches_skill([tag],term))
            for tag in ('Vuex','Nuxt.js','React'):self.assertFalse(matches_skill([tag],term))

    def test_owned_required_and_preferred_use_same_expansion_in_es_and_sql(self):
        for field in ('owned_skills','required_skills','preferred_skills'):
            baseline=None
            for term in ('Vue','Vue.js','VueJs'):
                plan=SearchPlan(**{field:[term]})
                current=(build_query(plan),structured_clauses(plan))
                if baseline is None:baseline=current
                else:self.assertEqual(current,baseline)

    def test_required_skills_stay_and_owned_skills_stay_or(self):
        rows=[{'source':'jumpit','source_id':str(i),'job_id':i,'source_version':1,
               'title':'Developer','company_name':'Synthetic','tech_stacks':tags,
               'recruitment_status':'unknown'}
              for i,tags in enumerate([['Vue.js'],['VueJs','Python'],['React'],['Vuex']],1)]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'jobs.json';path.write_text(json.dumps(rows),encoding='utf-8')
            repo=JsonJobRepository(path,include_unverified=True)
            self.assertEqual(repo.search(SearchPlan(owned_skills=['Vue']))[0],2)
            self.assertEqual(repo.search(SearchPlan(required_skills=['Vue','Python']))[0],1)
            self.assertEqual(repo.search(SearchPlan(owned_skills=['Vue','React']))[0],3)
