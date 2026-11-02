"""Source-bound derived classification; never mutate source or user assessments."""
import hashlib,json
from src.schemas.condition_review import ConditionReview,POLICY_VERSION
from src.services.condition_structure import structure_conditions,PARSER_VERSION

def source_conditions(job):
    result=[]
    for kind,section in [('required','qualifications'),('preferred','preferred_requirements')]:
        text=job.get(section) or ''
        if not isinstance(text,str) or len(text)>18000:raise ValueError('Condition source budget exceeded')
        result+=structure_conditions(text,kind,str(job['source_id']),job['source_version'])
    return result

def review_key(condition):
    raw=[condition['key'],condition['source_spans']]
    return hashlib.sha256(json.dumps(raw,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def condition_hash(job):
    raw=[PARSER_VERSION,job.get('qualifications') or '',job.get('preferred_requirements') or '']
    return hashlib.sha256(json.dumps(raw,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

def validate_review(job,proposal):
    model=ConditionReview.model_validate(proposal)
    source={review_key(c):c for c in source_conditions(job)}
    ids=[c.condition_id for c in model.conditions]
    if len(ids)!=len(set(ids)) or set(ids)!=set(source):raise ValueError('Incomplete or unknown source identities')
    result=[]
    for item in model.conditions:
        original=source[item.condition_id];nodes=0
        def check(node,depth=0):
            nonlocal nodes
            nodes+=1
            if depth>4 or nodes>32:raise ValueError('Logic budget exceeded')
            if node.operator=='atom' and node.evidence not in original['quote']:raise ValueError('Evidence differs from source')
            for child in node.children:check(child,depth+1)
        check(item.logic)
        result.append(dict(item.model_dump(mode='json'),requirement_type=original['type'],quote=original['quote'],section=original['section'],source_spans=original['source_spans']))
    # Stable original order, regardless of model order.
    by_id={c['condition_id']:c for c in result}
    return {'policy_version':POLICY_VERSION,'parser_version':PARSER_VERSION,'condition_hash':condition_hash(job),
            'conditions':[by_id[review_key(c)] for c in source_conditions(job)]}

def validated_envelope(job,envelope):
    if not isinstance(envelope,dict) or envelope.get('policy_version')!=POLICY_VERSION or envelope.get('parser_version')!=PARSER_VERSION or envelope.get('condition_hash')!=condition_hash(job):
        raise ValueError('Stale condition review')
    fields={'condition_id','treatment','category','reason_code','reason','logic'}
    result=validate_review(job,{'conditions':[{k:v for k,v in c.items() if k in fields} for c in envelope['conditions']]})
    # Never accept a cached/indexed quote as authority; reconstruct it from current source.
    return result

def question_selection(job,envelope):
    review=validated_envelope(job,envelope);by_id={c['condition_id']:c for c in review['conditions']}
    questions=[];references=[];all_conditions=source_conditions(job)
    for original in all_conditions:
        item=by_id[review_key(original)]
        entry=dict(original,ai_review={k:item[k] for k in ('treatment','category','reason_code','reason')})
        (references if item['treatment']=='reference' else questions).append(entry)
    return questions,references,all_conditions

def projection(job,envelope):
    review=validated_envelope(job,envelope)
    entries=[];terms={'required':[],'preferred':[]}
    for item in review['conditions']:
        evidence=[]
        def collect(node):
            if node['operator']=='atom':evidence.append({'term':node['term'],'quote':node['evidence']})
            for child in node.get('children',[]):collect(child)
        collect(item['logic'])
        # Only skill-classified, source-evidenced terms are ranking hints, never eligibility verdicts.
        if item['category']=='skill':terms[item['requirement_type']]+=[a['term'] for a in evidence]
        entries.append({k:item[k] for k in ('condition_id','requirement_type','treatment','category','reason_code','reason','quote')}|{
            'logic':item['logic'],'atoms':evidence})
    return {'condition_classification':{'condition_hash':review['condition_hash'],'policy_version':POLICY_VERSION,'parser_version':PARSER_VERSION},
            'classified_conditions':entries,'required_condition_terms':list(dict.fromkeys(terms['required'])),
            'preferred_condition_terms':list(dict.fromkeys(terms['preferred']))}
