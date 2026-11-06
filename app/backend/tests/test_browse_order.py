import unittest
from unittest.mock import patch
from src.schemas.search import SearchPlan
from src.repositories.browse_order import unfiltered_jobs,shuffle_browse

class BrowseOrderTests(unittest.TestCase):
 def test_randomization_is_only_for_unfiltered_browse(self):
  empty=SearchPlan.parse({'keyword':'','region':'','skills':[],'limit':20})
  rows=[{'source_id':'1'},{'source_id':'2'}]
  with patch('src.repositories.browse_order.random.SystemRandom') as rng:
   rng.return_value.shuffle.side_effect=lambda values:values.reverse()
   self.assertEqual(shuffle_browse(rows.copy(),empty),list(reversed(rows)))
   for data in ({'keyword':'React'},{'region':'Seoul'},{'skills':['Python']},{'roles':['backend']},{'owned_skills':['Python']},{'career':{'levels':['entry']}}):
    plan=SearchPlan.parse(data);self.assertFalse(unfiltered_jobs(plan));self.assertEqual(shuffle_browse(rows.copy(),plan),rows)
   self.assertEqual(rng.return_value.shuffle.call_count,1)
