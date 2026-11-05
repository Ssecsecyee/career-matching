import unittest
from src.services.training_groups import grouped,identity,group_key
from src.services.training_review import signatures
from src.repositories.mysql_training import card
from datetime import datetime,timezone

class TrainingGroupTests(unittest.TestCase):
    def course(self,course='A',institution='I',round='1',address='Seoul'):
        return card({'source':'goyong24_training','source_id':course+institution+round+address,
            'source_version':1,'course_key':'card:'+course,'cohort_name':round,'title':'Same title',
            'addresses':[address],'delivery_mode':'online','additional_sections':{
            'collection_metadata':{'institution_id':institution},'date_precision':{'starts_at':{'raw':'2099-12-01'}}}},[],now=datetime(2026,11,5,tzinfo=timezone.utc))

    def test_rounds_group_but_institution_course_and_campus_remain_distinct(self):
        a=self.course();b=self.course(round='2')
        result=grouped([a,b,self.course(institution='J'),self.course(course='B'),self.course(address='Busan')],limit=10)
        self.assertEqual(len(result),4);self.assertEqual(len(result[0]['cohorts']),2)
        self.assertEqual([v['source_id'] for v in result[0]['cohorts']],[a['source_id'],b['source_id']])

    def test_next_page_excludes_unseen_rounds_of_already_shown_course(self):
        a=self.course();b=self.course(round='2');other=self.course(course='B')
        self.assertEqual([x['source_id'] for x in grouped([b,other],exclude_groups=[group_key(a)])],[other['source_id']])

    def test_no_identity_never_merges_same_title_and_variants_are_bounded(self):
        a={'source':'boottent','source_id':'1','title':'Same'};b=dict(a,source_id='2')
        self.assertEqual(len(grouped([a,b])),2)
        result=grouped([self.course(round=str(i)) for i in range(10)])[0]
        self.assertEqual(len(result['cohorts']),5);self.assertTrue(result['cohorts_truncated'])

    def test_confirm_signature_covers_every_displayed_round(self):
        result=grouped([self.course(),self.course(round='2')])
        before=signatures(result);result[0]['cohorts'][1]['source_version']=2
        self.assertNotEqual(signatures(result),before)

    def test_elastic_pages_past_same_course_rounds_to_fill_distinct_courses(self):
        from unittest.mock import MagicMock
        from src.repositories.elasticsearch_training import ElasticsearchTrainingRepository
        source=[]
        for i in range(102):
            source.append({'offering_id':i,'source':'goyong24_training','source_id':str(i),
              'source_version':1,'course_key':'card:'+('A' if i<100 else str(i)),
              'title':'Synthetic','delivery_mode':'online','additional_sections':{
              'collection_metadata':{'institution_id':'I'},'date_precision':{'starts_at':{'raw':'2099-12-01'}}}})
        conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value
        cur.fetchall.side_effect=[source[:100],source[100:]]
        def page(rows):return {'hits':{'total':{'value':102,'relation':'eq'},'hits':[
            {'_source':{k:r[k] for k in ('source','source_id','source_version')},'sort':[1,r['source_id']]} for r in rows]}}
        request=MagicMock(side_effect=[page(source[:100]),page(source[100:])])
        courses=ElasticsearchTrainingRepository(lambda:conn,request).search(['React'],candidates_only=True)
        self.assertEqual(len(courses),3);self.assertEqual(request.call_count,2)
        self.assertEqual(len(courses[0]['cohorts']),5);self.assertTrue(courses[0]['cohorts_truncated'])
