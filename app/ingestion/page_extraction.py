"""Preserve observed page sections and date precision without inventing timestamps."""
from datetime import date
import re


def apply_page_metadata(row):
    page=row.get('raw_detail',{}).get('_page_extraction')
    if not isinstance(page,dict):return row
    if page.get('source_url')!=row['source_url']:raise ValueError('page_source_url_mismatch')
    # Structured observations stay in raw_detail. Only stable source content below
    # contributes to business revision hashes; observation times do not.
    stable={'method':'page_extraction','original_sections':[]}
    sections=page.get('original_sections',[])
    if not isinstance(sections,list):raise ValueError('invalid_page_sections')
    combined=[]
    for section in sections:
        if not isinstance(section,dict):raise ValueError('invalid_page_section')
        if section.get('status')!='확인됨':continue
        if section.get('source_url')!=row['source_url']:raise ValueError('section_source_url_mismatch')
        heading,text=section.get('original_heading'),section.get('original_text')
        if not isinstance(heading,str) or not isinstance(text,str):raise ValueError('invalid_original_section_text')
        topics=section.get('combined_topics',[])
        if not isinstance(topics,list) or any(not isinstance(x,str) for x in topics):raise ValueError('invalid_section_topics')
        stable['original_sections'].append({'original_heading':heading,'original_text':text,
            'is_combined':section.get('is_combined') is True,'combined_topics':topics})
        if section.get('is_combined') is True and '채용절차' in heading and '유의사항' in heading and text.strip():
            combined.append(text)
    if combined:
        # Both columns deliberately reference the same combined source, not invented sub-sections.
        text='\n\n'.join(combined)
        if row.get('hiring_process') and row['hiring_process'].strip()!=text.strip():
            raise ValueError('combined_process_source_conflict')
        row['hiring_process']=text;row['application_notes']=text
        row['field_status']['hiring_process']='present_combined_source'
        row['field_status']['application_notes']='present_combined_source'
        stable['combined_process_and_notes']=True
    dates=page.get('dates',{})
    if not isinstance(dates,dict):raise ValueError('invalid_page_dates')
    deadline=dates.get('deadline',{})
    if not isinstance(deadline,dict):raise ValueError('invalid_page_deadline')
    if deadline.get('precision')=='date_only' and deadline.get('status')=='확인됨':
        raw=deadline.get('raw')
        if not isinstance(raw,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',raw):raise ValueError('invalid_date_only_deadline')
        day=date.fromisoformat(raw).isoformat()
        stable['deadline']={'date':day,'raw':raw,'precision':'date_only','exact_time':None,'timezone':None}
        row['field_status']['deadline_display']='date_only'
        # Do not manufacture closedAt/deadline_at, active status, or a timezone.
    if stable['original_sections'] or 'deadline' in stable:
        row['additional_sections']=dict(row.get('additional_sections') or {},page_extraction=stable)
    return row
