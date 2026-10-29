import copy
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'ingestion'))
from page_extraction import apply_page_metadata

class AlternatePageTests(unittest.TestCase):
    def row(self):
        url='https://jumpit.saramin.co.kr/position/123'
        heading='채용절차 및 기타 지원 유의사항'
        return {'source_url':url,'hiring_process':'원문','field_status':{},'raw_detail':{'_page_extraction':{
            'source_url':url,'sections':{heading:'원문','마감일':'2026-11-27'},
            'original_sections':[{'original_heading':heading,'original_text':'원문','is_combined':True,
                                  'source_url':url,'pointer':'dt='+heading+'/dd'}],
            'dates':{'deadline':{'precision':'date_only','raw':'2026-11-27'}},
            'deadline_display_raw':'2026-11-27',
            'field_status':{'deadline_display':{'status':'확인됨','source_url':url,'pointer':'dt=마감일/dd'}}}}}
    def test_alternate_preserves_combined_and_date_without_inference(self):
        row=apply_page_metadata(self.row())
        self.assertEqual(row['application_notes'],'원문')
        self.assertEqual(row['additional_sections']['page_extraction']['deadline']['precision'],'date_only')
        self.assertNotIn('deadline_at',row)
        self.assertNotIn('recruitment_status',row)
    def test_conflicting_section_does_not_map(self):
        row=self.row();row['raw_detail']['_page_extraction']['sections'].clear()
        row=apply_page_metadata(row)
        self.assertNotIn('application_notes',row)
    def test_unverified_date_does_not_map(self):
        row=self.row();row['raw_detail']['_page_extraction']['field_status']['deadline_display']['status']='미검증'
        row=apply_page_metadata(row)
        self.assertNotIn('deadline',row['additional_sections']['page_extraction'])
