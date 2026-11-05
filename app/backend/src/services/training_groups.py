"""Group proven course/provider identities; never infer identity from titles."""
import hashlib,json


def group_key(course):
    return course.get('course_group_key') or 'offering:'+course['source']+':'+course['source_id']


def identity(row,extra):
    meta=extra.get('collection_metadata') or {}
    course=row.get('course_key');institution=meta.get('institution_id')
    if row.get('source')!='goyong24_training' or not course or not institution:return None
    addresses=row.get('addresses') or []
    if isinstance(addresses,str):addresses=json.loads(addresses)
    fields=[row['source'],course,institution,row.get('delivery_mode'),addresses]
    return hashlib.sha256(json.dumps(fields,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def exclusions(values):
    if not isinstance(values,(list,tuple)) or len(values)>1000 or any(not isinstance(x,str) or not 1<=len(x)<=300 for x in values):
        raise ValueError('Invalid training group exclusions')
    return set(values)


VARIANT_FIELDS=('source','source_id','source_version','content_hash','source_url','cohort_name',
                'dates','starts_at','ends_at','schedule_status','schedule_label','recruitment_status',
                'recruitment_display_status','recruitment_label','recommendation_eligible',
                'application_deadline','tuition','currency','cost_description','warning')


def grouped(courses,*,exclude_groups=(),limit=3):
    excluded=exclusions(exclude_groups);groups={}
    for course in courses:
        key=group_key(course)
        if key in excluded:continue
        if key not in groups:
            if len(groups)>=limit:continue
            groups[key]=dict(course,course_group_key=key,cohorts=[],cohorts_truncated=False)
        result=groups[key]
        if any(c['source_id']==course['source_id'] for c in result['cohorts']):continue
        if len(result['cohorts'])>=5:
            result['cohorts_truncated']=True;continue
        result['cohorts'].append({k:course.get(k) for k in VARIANT_FIELDS})
    return list(groups.values())
