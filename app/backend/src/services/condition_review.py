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

def source_parts(condition):
    """Lossless line/range partition. These ranges preserve text, not semantic truth."""
    quote=condition['quote'];result=[];offset=0
    for line in quote.splitlines(keepends=True):
        for start in range(0,len(line),500):
            text=line[start:start+500];begin=offset+start;end=begin+len(text)
            identity=hashlib.sha256((review_key(condition)+':'+str(begin)+':'+str(end)).encode()).hexdigest()[:16]
            result.append({'part_id':identity,'start':begin,'end':end,'quote':text})
        offset+=len(line)
    if not result or len(result)>128:raise ValueError('Source part budget exceeded')
    return result

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
            if node.operator=='atom':
                if node.evidence not in original['quote']:raise ValueError('Evidence differs from source')
                if node.term.casefold() not in node.evidence.casefold():raise ValueError('Term not extracted from evidence')
            for child in node.children:check(child,depth+1)
        check(item.logic)
        originals=source_parts(original);part_map={p['part_id']:p for p in originals}
        returned=[p.part_id for p in item.parts]
        if len(returned)!=len(set(returned)) or set(returned)!=set(part_map):
            raise ValueError('Incomplete or duplicate source parts')
        supplied={p.part_id:p for p in item.parts};parts=[]
        for part in originals:
            terms=supplied[part['part_id']].terms
            if len(terms)!=len(set(terms)) or any(not t.strip() or t not in part['quote'] for t in terms):
                raise ValueError('Part terms must be exact source substrings')
            parts.append(dict(part,terms=terms))
        if ''.join(p['quote'] for p in parts)!=original['quote']:raise ValueError('Source coverage mismatch')
        data=item.model_dump(mode='json');data['parts']=parts
        result.append(dict(data,requirement_type=original['type'],quote=original['quote'],section=original['section'],source_spans=original['source_spans']))
    # Stable original order, regardless of model order.
    by_id={c['condition_id']:c for c in result}
    return {'policy_version':POLICY_VERSION,'parser_version':PARSER_VERSION,'condition_hash':condition_hash(job),
            'conditions':[by_id[review_key(c)] for c in source_conditions(job)]}

def validated_envelope(job,envelope):
    if not isinstance(envelope,dict) or envelope.get('policy_version')!=POLICY_VERSION or envelope.get('parser_version')!=PARSER_VERSION or envelope.get('condition_hash')!=condition_hash(job):
        raise ValueError('Stale condition review')
    fields={'condition_id','treatment','category','reason_code','reason','logic','parts'}
    proposals=[]
    for c in envelope['conditions']:
        item={k:v for k,v in c.items() if k in fields}
        item['parts']=[{k:v for k,v in p.items() if k in {'part_id','terms'}} for p in c.get('parts',[])]
        proposals.append(item)
    result=validate_review(job,{'conditions':proposals})
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
        # Flat extraction is independent of logical tree arity; unresolved lists retain every term.
        for part in item['parts']:
            evidence.extend({'term':term,'quote':part['quote']} for term in part['terms'])
        evidence=list({(x['term'],x['quote']):x for x in evidence}.values())
        # Only skill-classified, source-evidenced terms are ranking hints, never eligibility verdicts.
        if item['category']=='skill' and item['treatment']!='reference':terms[item['requirement_type']]+=[a['term'] for a in evidence]
        entries.append({k:item[k] for k in ('condition_id','requirement_type','treatment','category','reason_code','reason','quote')}|{
            'logic':item['logic'],'atoms':evidence,'source_parts':item['parts']})
    return {'condition_classification':{'condition_hash':review['condition_hash'],'policy_version':POLICY_VERSION,'parser_version':PARSER_VERSION},
            'classified_conditions':entries,'required_condition_terms':list(dict.fromkeys(terms['required'])),
            'preferred_condition_terms':list(dict.fromkeys(terms['preferred']))}

def attach_selection(state,result):
    status=state.get('condition_review')
    if status:
        result['condition_review']=status
        result['reference_conditions']=[{'condition_id':c['id'],'type':c['type'],'quote':c['quote'],
            'reason':c['ai_review']['reason'],'reason_code':c['ai_review']['reason_code']} for c in state.get('reference_conditions',[])]
        result['condition_source_url']=(state.get('selected') or {}).get('source_url')
    return result
