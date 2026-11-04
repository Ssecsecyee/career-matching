"""Conservative source spans for conditions, with no source rewriting or inferred eligibility."""
import hashlib
import re

PARSER_VERSION='condition-split-v3'
BULLET=re.compile(r'^(?:[-*•●▪·ㆍ‧◦○]\s*|\d{1,3}[.)](?!\d))')
CONTINUATION=re.compile(r'^(?:또는|혹은|및(?:\s|$)|그리고(?:\s|$)|AND\b|OR\b|\(|（|※)',re.I)
HEADINGS={'학력','경력','자격요건','자격조건','필수조건','우대사항','우대조건','필수','우대'}
COLLECTIONS={'추가 기술스택','기술스택','추가 기술 스택','추가 스킬','추가 역량'}
SOURCE_KEYS=('parser_version','section_hash','source_spans','offset_unit','parse_status','parse_notes')


def source_binding(value):
    return {key:value[key] for key in SOURCE_KEYS if key in value}


def source_notice(value):
    notes=value.get('parse_notes',[])
    if 'technical_collection' in notes:
        return {'source_notice':'여러 기술이 나열된 원문 묶음입니다. 일부만 해당하면 미확인으로 선택하고 보충 설명을 남겨 주세요. 개별 기술을 모두 검증한 것으로 해석하지 않습니다.'}
    if any(note in notes for note in ('nested_items','unmarked_multiline','unbalanced_delimiter','fallback_whole_section')):
        return {'source_notice':'원문에서 연결 관계가 명확하지 않은 내용을 함께 표시했습니다. 일부만 해당하거나 판단이 어려우면 미확인으로 남겨 주세요.'}
    return {}


def _depth(text):
    depth=0
    for char in text:
        if char in '(（': depth+=1
        elif char in ')）': depth=max(0,depth-1)
    return depth


def _numbered_ranges(content):
    """Split only explicit consecutive inline numbering outside parentheses.

    Offsets refer to the untouched source. Decimal/version numbers and OR
    alternatives are not semantic condition boundaries.
    """
    matches=list(re.finditer(r'(?<!\S)([1-9][0-9]{0,2})[.)](?![0-9])',content))
    if not matches or content[:matches[0].start()].strip():return [(0,len(content))]
    selected=[]
    for match in matches:
        if _depth(content[:match.start()]):continue
        selected.append(match)
    if len(selected)<2 or [int(m.group(1)) for m in selected]!=list(range(1,len(selected)+1)):
        return [(0,len(content))]
    if any(CONTINUATION.match(content[m.end():].lstrip()) for m in selected[1:]):
        return [(0,len(content))]
    starts=[0]+[m.start() for m in selected[1:]]
    return list(zip(starts,starts[1:]+[len(content)]))


def _lines(text):
    offset=0
    for raw in text.splitlines(keepends=True):
        content=raw.rstrip('\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029')
        for begin,end in _numbered_ranges(content):
            piece=content[begin:end]
            stripped=piece.strip()
            match=BULLET.match(stripped)
            body=BULLET.sub('',stripped,count=1)
            label=body.rstrip(':：').strip().strip('[]【】').strip()
            yield {'start':offset+begin,'end':offset+end,'after':offset+end if end<len(content) else offset+len(raw),
                   'text':stripped,'body':body,'marked':bool(match),
                   'indent':len(content[:len(content)-len(content.lstrip())].expandtabs(4)),
                   'heading':label if label in HEADINGS or label in COLLECTIONS else None}
        offset+=len(raw)


def _item(text,kind,source_id,version,index,spans,notes,section_hash):
    quote=''.join(text[span['start']:span['end']] for span in spans)
    if not quote.strip(): raise ValueError('Empty source condition')
    key=hashlib.sha256((PARSER_VERSION+':'+section_hash+':'+kind+':'+quote).encode('utf-8')).hexdigest()
    set_hash=hashlib.sha256((PARSER_VERSION+':'+section_hash).encode()).hexdigest()[:16]
    return {'id':f'{source_id}:{version}:{kind}:{set_hash}:{index}',
            'type':kind,'section':'qualifications' if kind=='required' else 'preferred_requirements',
            'quote':quote,'key':key,'parser_version':PARSER_VERSION,'section_hash':section_hash,
            'source_spans':spans,'offset_unit':'unicode_codepoint_start_inclusive_end_exclusive',
            'parse_status':'needs_review' if notes else 'validated_boundaries','parse_notes':sorted(notes)}


def validate_conditions(text,conditions):
    """Validate exact source slices and body coverage, allowing shared heading context."""
    expected=hashlib.sha256(text.encode('utf-8')).hexdigest()
    covered=bytearray(len(text));body_covered=bytearray(len(text));seen=set()
    for item in conditions:
        if item['id'] in seen or item.get('section_hash')!=expected:
            raise ValueError('Condition identity or source hash mismatch')
        seen.add(item['id'])
        pieces=[];last_end=0
        for span in item['source_spans']:
            start,end=span['start'],span['end']
            if type(start) is not int or type(end) is not int or not 0<=start<end<=len(text) or start<last_end:
                raise ValueError('Invalid source span')
            if span['kind'] not in {'heading','body'}: raise ValueError('Invalid span kind')
            if span['kind']=='body' and any(body_covered[start:end]):
                raise ValueError('Duplicate condition body')
            if span['kind']=='body': body_covered[start:end]=b'1'*(end-start)
            covered[start:end]=b'1'*(end-start)
            pieces.append(text[start:end]);last_end=end
        if ''.join(pieces)!=item['quote']:
            raise ValueError('Condition quote differs from source')
    if any(not char.isspace() and not covered[i] for i,char in enumerate(text)):
        raise ValueError('Unaccounted source content')
    return True


def structure_conditions(text,kind,source_id,version):
    if not isinstance(text,str) or kind not in {'required','preferred'}:
        raise ValueError('Invalid condition source')
    if not text.strip(): return []
    lines=list(_lines(text))
    headings=[];groups=[];current=None;heading_used=True
    section_hash=hashlib.sha256(text.encode('utf-8')).hexdigest()
    for line in lines:
        if not line['text']: continue
        opened=_depth(text[current['start']:current['end']]) if current else 0
        if line['heading'] and not opened:
            if heading_used: headings=[]
            headings.append(line)
            current=None;heading_used=False
            continue
        collection=any(h['heading'] in COLLECTIONS for h in headings)
        continued=bool(CONTINUATION.match(line['body']))
        nested=bool(current and line['marked'] and line['indent']>current['indent'])
        append=bool(current and (opened or continued or nested or collection or not line['marked']))
        if append:
            current['end']=line['end']
            if nested: current['notes'].add('nested_items')
            if not collection and not line['marked'] and not continued and not current['marked']:
                current['notes'].add('unmarked_multiline')
            continue
        current={'start':line['start'],'end':line['end'],'indent':line['indent'],
                 'marked':line['marked'],'headings':list(headings),'notes':set()}
        if collection: current['notes'].add('technical_collection')
        groups.append(current);heading_used=True
    rows=[]
    for group in groups:
        if _depth(text[group['start']:group['end']]): group['notes'].add('unbalanced_delimiter')
        spans=[{'start':h['start'],'end':h['after'],'kind':'heading'} for h in group['headings']]
        spans.append({'start':group['start'],'end':group['end'],'kind':'body'})
        rows.append(_item(text,kind,source_id,version,len(rows),spans,group['notes'],section_hash))
    if len(rows)>40: raise ValueError('Too many source conditions')
    try:
        validate_conditions(text,rows)
    except ValueError:
        # Preserve all source text instead of silently discarding a dangling heading.
        rows=[_item(text,kind,source_id,version,0,[{'start':0,'end':len(text),'kind':'body'}],
                    {'fallback_whole_section'},section_hash)]
        validate_conditions(text,rows)
    return rows
