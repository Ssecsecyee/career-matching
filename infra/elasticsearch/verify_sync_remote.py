"""Post-install checks with no model invocation or user conversation writes."""
import json,os,sys
sys.path.insert(0,'/opt/career/app')
import worker
worker.configure()
from src.repositories.mysql_connection import connect_mysql
from src.repositories.job_search_factory import create_job_repository
from src.repositories.elasticsearch_training import create_training_repository
from src.repositories.search_failover import SearchUnavailable
from src.schemas.search import SearchPlan
jobs=create_job_repository(connect_mysql,include_unverified=True)
training=create_training_repository(connect_mysql)
assert type(jobs.primary).__name__=='VerifiedElasticJobs'
assert type(training.primary).__name__=='ElasticsearchTrainingRepository'
plan=SearchPlan(skills=('React',))
total,rows=jobs.search(plan)
assert total>0 and rows and not jobs.search_degraded
courses=training.search(['React']);assert courses and not training.search_degraded
primary=jobs.primary.search
def unavailable(_):raise SearchUnavailable('integration_test_outage')
jobs.primary.search=unavailable
fallback_total,fallback_rows=jobs.search(plan)
assert fallback_total>0 and fallback_rows and jobs.search_degraded
jobs.primary.search=primary
recovered,_=jobs.search(plan);assert recovered==total and not jobs.search_degraded
zero,_=jobs.search(SearchPlan(skills=('NonexistentSkillXYZ918',)))
assert zero==0 and not jobs.search_degraded
print(json.dumps({'job_backend':'elasticsearch','training_backend':'elasticsearch','react_matches':total,'training_cards':len(courses),'mysql_failover':'passed_injected_transport_failure','next_request_recovery':True,'normal_zero_does_not_failover':True,'model_calls':0}))
