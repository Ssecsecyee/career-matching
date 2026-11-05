import unittest
from datetime import datetime, timedelta, timezone
from src.services.training_dates import effective_start, start_visibility
from src.repositories.mysql_training import card, MySQLTrainingRepository
from src.repositories.elasticsearch_training import build_training_query, ElasticsearchTrainingRepository

UTC=timezone.utc
NOW=datetime(2026,11,4,15,tzinfo=UTC)  # Nov 5, 00:00 KST

def row(raw='2026-11-05'):
    return {'offering_id':1,'source':'goyong24_training','source_id':'one','source_version':1,
            'title':'React','recruitment_status':'active','additional_sections':{
                'recommendation_eligible':True,'date_precision':{'starts_at':{'raw':raw}}},
            'application_deadline':datetime(2027,1,1), 'learning_topics':['React']}

class TrainingDatesTests(unittest.TestCase):
    def test_kst_boundary_and_missing_invalid_start(self):
        course=row()
        self.assertTrue(start_visibility(course,now=NOW-timedelta(microseconds=1))[0])
        self.assertEqual(start_visibility(course,now=NOW),(False,'training_started'))
        for raw in ['2026-11-04','bad','']:
            self.assertFalse(start_visibility(row(raw),now=NOW)[0])
        self.assertEqual(start_visibility({},now=NOW),(False,'start_unknown'))

    def test_timestamp_timezone_and_db_utc(self):
        self.assertEqual(effective_start({'starts_at':datetime(2026,11,4,15)}),NOW)
        self.assertFalse(start_visibility({'starts_at':NOW.astimezone(timezone(timedelta(hours=9)))},now=NOW)[0])
        with self.assertRaises(ValueError):start_visibility({},now=NOW.replace(tzinfo=None))

    def test_open_deadline_does_not_override_started_training(self):
        result=card(row(),['React'],now=NOW)
        self.assertFalse(result['recommendation_eligible'])
        self.assertFalse(result['start_window_eligible'])
        self.assertEqual(result['recruitment_status'],'active')
        self.assertEqual(result['usage'],'learning_reference')
        self.assertTrue(card(row('2026-11-06'),['React'],now=NOW)['recommendation_eligible'])

    def test_future_unknown_is_not_confirmed_recruitment(self):
        course=row('2026-11-06');course['recruitment_status']='unknown'
        result=card(course,['React'],now=NOW)
        self.assertTrue(result['start_window_eligible'])
        self.assertFalse(result['recommendation_eligible'])

    def test_schedule_and_recruitment_are_independent(self):
        course=row('2026-11-14');course['recruitment_status']='unknown'
        course['additional_sections']['date_precision']['ends_at']={'raw':'2026-12-19'}
        result=card(course,['React'],now=NOW)
        self.assertEqual(result['schedule_status'],'upcoming')
        self.assertEqual(result['recruitment_display_status'],'unknown')
        self.assertNotIn('과거',result['warning'])
        self.assertFalse(result['recommendation_eligible'])
        course['recruitment_status']='closed'
        result=card(course,['React'],now=NOW)
        self.assertEqual(result['schedule_status'],'upcoming')
        self.assertEqual(result['recruitment_display_status'],'closed')

    def test_end_date_includes_entire_korean_calendar_day(self):
        from src.services.training_dates import training_status
        course=row('2026-11-01')
        course['additional_sections']['date_precision']['ends_at']={'raw':'2026-11-05'}
        self.assertEqual(training_status(course,now=NOW)['schedule_status'],'ongoing')
        self.assertEqual(training_status(course,now=NOW+timedelta(days=1))['schedule_status'],'ended')
        course['additional_sections']['date_precision'].pop('ends_at')
        self.assertEqual(training_status(course,now=NOW)['schedule_status'],'unknown')

    def test_deadline_elapsed_is_not_provider_closed_and_refresh_keeps_source(self):
        from src.services.training_dates import refresh_card_status
        course=row('2026-11-14');course['application_deadline']=datetime(2026,11,4)
        result=card(course,['React'],now=NOW)
        self.assertEqual(result['recruitment_status'],'active')
        self.assertEqual(result['recruitment_display_status'],'deadline_elapsed')
        self.assertFalse(result['recommendation_eligible'])
        old=dict(result,warning='과거 회차 또는 모집 미확인',dates={'starts_at':{'raw':'2026-11-14'},'ends_at':{'raw':'2026-12-19'}})
        fresh=refresh_card_status(old,now=NOW+timedelta(days=60))
        self.assertEqual(fresh['schedule_status'],'ended')
        self.assertEqual(fresh['usage'],'historical_learning_reference')
        self.assertNotEqual(old['warning'],fresh['warning'])

    def test_candidate_es_filter_and_reference_mode(self):
        filters=build_training_query(['React'],candidates_only=True)['query']['bool']['filter']
        self.assertIn({'range':{'training_start_at':{'gt':'now'}}},filters)
        self.assertNotIn({'range':{'training_start_at':{'gt':'now'}}},build_training_query(['React'])['query']['bool']['filter'])

    def test_stale_es_candidate_is_rechecked_in_mysql(self):
        class Cursor:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def execute(self,sql,params):pass
            def fetchall(self):return [row('2000-01-01')]
        class DB:
            def cursor(self):return Cursor()
            def close(self):pass
        hits={'hits':{'total':{'value':1,'relation':'eq'},'hits':[{'_source':{'source':'goyong24_training','source_id':'one','source_version':1}}]}}
        repo=ElasticsearchTrainingRepository(DB,lambda *args:hits)
        self.assertEqual(repo.search(['React'],candidates_only=True),[])
        self.assertEqual(len(repo.search(['React'])),1)
        self.assertEqual(MySQLTrainingRepository(DB).search(['React'],candidates_only=True),[])

if __name__=='__main__':unittest.main()
