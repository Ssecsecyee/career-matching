"""Transient stdin adapter, installed beside the isolated embedding model."""
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace

def main():
    from pilot import search, es
    value=json.loads(__import__('sys').stdin.read(22000))
    text=value['text']
    if not isinstance(text,str) or not text.strip() or len(text.encode('utf-8'))>20000:
        raise ValueError('invalid_input')
    available=int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')))//1024
    if available<1200:
        print(json.dumps({'error':'vector_capacity_busy'}));return
    index='career-job-vectors-pilot-20261114-full'
    name=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir='/dev/shm',prefix='career-query-',delete=False) as f:
            name=f.name;f.write(text)
        result=search(SimpleNamespace(resume_file=name,model_dir=str(Path(__file__).parent/'model'),index=index,k=20))
        # Bind candidates to the indexed raw sections for the authoritative DB recheck.
        for item in result['results']:
            response=es('POST','/'+index+'/_search',{'size':1,'_source':['qualifications_hash','preferred_requirements_hash'], 'query':{'bool':{'filter':[{'term':{'source':item['source']}},{'term':{'source_id':item['source_id']}}]}}})
            hits=response['hits']['hits']
            item['section_hashes']=hits[0]['_source'] if hits else {}
        print(json.dumps(result))
    finally:
        if name:os.unlink(name)

if __name__=='__main__':
    try:main()
    except ValueError:
        print(json.dumps({'error':'vector_input_or_contract_invalid'}))
    except Exception:
        print(json.dumps({'error':'vector_search_unavailable'}))
