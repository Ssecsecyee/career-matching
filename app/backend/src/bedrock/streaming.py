"""Extract only the top-level chat reply while retaining full final JSON validation."""
import json
from time import perf_counter
from src.bedrock.model_json import ModelOutputFormatError,usage_metadata

def string_prefix(value):
    """Decode the complete Unicode prefix of an unfinished JSON string."""
    result=[];i=1
    while i<len(value):
        c=value[i]
        if c=='"':break
        if c=='\\':
            if i+1>=len(value):break
            n=value[i+1]
            if n=='u':
                if i+6>len(value):break
                fragment=value[i:i+6]
                try:code=int(fragment[2:],16)
                except ValueError:break
                if 0xD800<=code<=0xDBFF:
                    if i+12>len(value):break
                    fragment=value[i:i+12]
                try:decoded=json.loads('"'+fragment+'"')
                except ValueError:break
                if any(0xD800<=ord(ch)<=0xDFFF for ch in decoded):break
                result.append(decoded);i+=len(fragment);continue
            try:result.append(json.loads('"\\'+n+'"'))
            except ValueError:break
            i+=2;continue
        if ord(c)<32:break
        result.append(c);i+=1
    return ''.join(result)[:4000]

def reply_prefix(text):
    text=text.lstrip('\ufeff').strip()
    if text.startswith('```'):
        if '\n' not in text:return ''
        header,text=text.split('\n',1)
        if header.lower() not in {'```json','```'}:return ''
    if not text.startswith('{'):return ''
    decoder=json.JSONDecoder();index=1;intent=None
    try:
        while True:
            while index<len(text) and text[index].isspace():index+=1
            key,index=decoder.raw_decode(text,index)
            if not isinstance(key,str):return ''
            while index<len(text) and text[index].isspace():index+=1
            if text[index]!=':':return ''
            index+=1
            while index<len(text) and text[index].isspace():index+=1
            if key=='reply' and intent=='chat' and text[index]=='"':return string_prefix(text[index:])
            value,index=decoder.raw_decode(text,index)
            if key=='intent':intent=value
            while index<len(text) and text[index].isspace():index+=1
            if text[index]!=',':return ''
            index+=1
    except (ValueError,IndexError):return ''

def converse_response(client,arguments,on_partial,*,model_id,region):
    if on_partial is None:return client.converse(**arguments)
    started=perf_counter();raw='';last=''
    response=client.converse_stream(**arguments);stream=response['stream']
    result={'ResponseMetadata':response.get('ResponseMetadata',{}),'usage':{},'stopReason':None}
    try:
        for event in stream:
            for name in event:
                if name.endswith('Exception'):
                    raise RuntimeError('Bedrock stream interrupted')
            if 'contentBlockDelta' in event:
                raw+=event['contentBlockDelta']['delta'].get('text','')
                if len(raw)>20000 or perf_counter()-started>65:raise ModelOutputFormatError({})
                partial=reply_prefix(raw)
                if len(partial)>len(last) and partial.startswith(last):
                    on_partial(partial);last=partial
            if 'messageStop' in event:result['stopReason']=event['messageStop'].get('stopReason')
            if 'metadata' in event:result['usage']=event['metadata'].get('usage',{})
        result['output']={'message':{'content':[{'text':raw}]}}
        return result
    except Exception as exc:
        # Preserve usage if metadata was received before a late stream failure.
        exc.usage=usage_metadata(result,model_id=model_id,region=region,prompt_version='conversation-training-v4',started=started)
        raise
    finally:
        if hasattr(stream,'close'):stream.close()
