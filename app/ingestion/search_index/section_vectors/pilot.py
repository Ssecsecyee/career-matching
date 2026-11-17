"""Opt-in separate ES pilot: whole qualifications/preferred vectors, current jobs only."""
import argparse,json,sqlite3,time,re
from pathlib import Path
from urllib.request import Request,urlopen
from local_sections import LocalEmbedder,section_records,model_contract,fingerprint,valid_vector
BASE='http://127.0.0.1:19200'
def es(method,path,body=None):
 data=None if body is None else json.dumps(body,ensure_ascii=False).encode()
 with urlopen(Request(BASE+path,data,{'Content-Type':'application/json'},method=method),timeout=90) as r:return json.load(r)
def visible():
 return [{'terms':{'recruitment_status':['active','unknown']}},{'bool':{'should':[{'term':{'deadline_type':'always_open'}},{'bool':{'must_not':[{'exists':{'field':'deadline_at'}}]}},{'range':{'deadline_at':{'gt':'now'}}}],'minimum_should_match':1}}]
def snapshot(limit=0):
 r=es('POST','/career-jobs-read/_search?scroll=1m',{'size':250,'sort':['_doc'],'query':{'bool':{'filter':visible()}}});sid=r.get('_scroll_id');rows=[]
 try:
  while r['hits']['hits']:
   for h in r['hits']['hits']:
    rows.append((h['_id'],h['_source']))
    if limit and len(rows)>=limit:return rows
   r=es('POST','/_search/scroll',{'scroll':'1m','scroll_id':sid});sid=r.get('_scroll_id',sid)
 finally:
  if sid:es('DELETE','/_search/scroll',{'scroll_id':[sid]})
 return rows
def mapping():
 props={k:{'type':'keyword'} for k in ('source','source_id','source_version','document_key','qualifications_hash','preferred_requirements_hash','model_fingerprint','recruitment_status','deadline_type')}
 props.update({k:{'type':'text','index':False} for k in ('title','company_name','qualifications','preferred_requirements','source_url')})
 props['deadline_at']={'type':'date'}
 for k in ('qualifications_vector','preferred_requirements_vector'):props[k]={'type':'dense_vector','dims':768,'similarity':'cosine','index':True}
 return {'settings':{'number_of_shards':1,'number_of_replicas':0},'mappings':{'dynamic':'strict','_meta':{'embedding':model_contract(),'pilot':True},'properties':props}}
def verify_source(rows):
 current=es('POST','/career-jobs-read/_mget',{'ids':[key for key,_ in rows]})['docs'];ok=[]
 for (key,old),now in zip(rows,current):
  if not now.get('found'):continue
  row=now['_source']
  if all(row.get(k)==old.get(k) for k in ('source','source_id','source_version','qualifications','preferred_requirements')):ok.append((key,row))
 return ok
def build(a):
 if not a.execute:raise ValueError('explicit_execute_required')
 if not re.fullmatch(r'career-job-vectors-pilot-[a-z0-9-]+',a.index):raise ValueError('pilot_index_name_required')
 start=time.monotonic();rows=snapshot(a.limit);embed=LocalEmbedder(a.model_dir);sections=[s for key,row in rows for s in section_records(row,key)]
 counts=[embed.token_count(s['text']) for s in sections]
 if any(n>embed.max_tokens for n in counts):raise ValueError('whole_section_exceeds_limit: count='+str(sum(n>embed.max_tokens for n in counts)))
 cache=sqlite3.connect(a.cache);cache.execute('CREATE TABLE IF NOT EXISTS vectors(cache_key TEXT PRIMARY KEY,vector TEXT NOT NULL,tokens INTEGER NOT NULL)');calls=0;vectors={}
 for s in sections:
  result=cache.execute('SELECT vector,tokens FROM vectors WHERE cache_key=?',(s['cache_key'],)).fetchone()
  if result:v=valid_vector(json.loads(result[0]))
  else:
   v,n=embed.encode(s['text']);calls+=1;cache.execute('INSERT INTO vectors VALUES(?,?,?)',(s['cache_key'],json.dumps(v),n));cache.commit()
  vectors[(s['es_id'],s['section'])]=v
  if calls and calls%50==0:print(json.dumps({'progress_sections':calls}),flush=True)
 valid=verify_source(rows)
 if len(valid)!=len(rows):raise ValueError('source_changed_during_build; rerun_from_cache')
 es('PUT','/'+a.index,mapping());docs=0
 for key,row in valid:
  doc={k:row[k] for k in mapping()['mappings']['properties'] if k in row and row[k] is not None}
  doc['model_fingerprint']=fingerprint()
  for s in section_records(row,key):doc[s['section']+'_hash']=s['section_hash'];doc[s['section']+'_vector']=vectors[(key,s['section'])]
  es('PUT','/'+a.index+'/_doc/'+key,doc);docs+=1
 es('POST','/'+a.index+'/_refresh')
 count=es('GET','/'+a.index+'/_count')['count']
 if count!=docs:raise ValueError('vector_document_count_mismatch')
 return {'status':'pilot_built','index':a.index,'jobs':docs,'sections':len(sections),'new_local_inferences':calls,'max_input_tokens':max(counts,default=0),'seconds':round(time.monotonic()-start,2),'model':model_contract(),'cloud_inference_calls':0,'live_alias_changed':False,'mysql_changes':0}
def search(a):
 # Query is transient: never put resume text/vectors in the document index or cache.
 text=Path(a.resume_file).read_text(encoding='utf-8-sig');embed=LocalEmbedder(a.model_dir);q,n=embed.encode(text)
 meta=es('GET','/'+a.index+'/_mapping')
 if next(iter(meta.values()))['mappings']['_meta']['embedding']!=model_contract():raise ValueError('model_contract_mismatch')
 hits={}
 for section in ('qualifications','preferred_requirements'):
  field=section+'_vector'
  body={'size':a.k,'_source':{'excludes':['*_vector']},'query':{'script_score':{'query':{'bool':{'filter':visible()+[{'exists':{'field':field}},{'term':{'model_fingerprint':fingerprint()}}]}},'script':{'source':"cosineSimilarity(params.q, '"+field+"') + 1.0",'params':{'q':q}}}}}
  for hit in es('POST','/'+a.index+'/_search',body)['hits']['hits']:
   item=hits.setdefault(hit['_id'],{'_source':hit['_source'],'scores':{}});item['scores'][section]=hit['_score']-1
 pairs=[(key,v['_source']) for key,v in hits.items()];valid={key for key,_ in verify_source(pairs)} if pairs else set()
 out=[]
 for key,v in hits.items():
  if key not in valid:continue
  row=v['_source'];out.append({'source':row['source'],'source_id':row['source_id'],'source_version':row['source_version'],'title':row.get('title'),'company_name':row.get('company_name'),'scores':v['scores'],'rank_score':max(v['scores'].values()),'basis':'section_similarity_not_qualification_assessment'})
 out.sort(key=lambda x:(-x['rank_score'],x['source'],x['source_id']))
 return {'status':'pilot_search','input_tokens':n,'ranking':'max_section_cosine_baseline','results':out[:a.k],'stale_candidates_excluded':len(hits)-len(valid),'resume_stored':False}
def main():
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['build','search']);p.add_argument('--model-dir',required=True);p.add_argument('--index',required=True);p.add_argument('--limit',type=int,default=0);p.add_argument('--cache',default='section-vectors.sqlite3');p.add_argument('--execute',action='store_true');p.add_argument('--resume-file');p.add_argument('--k',type=int,default=10);a=p.parse_args()
 if not re.fullmatch(r'career-job-vectors-pilot-[a-z0-9-]+',a.index):raise ValueError('pilot_index_name_required')
 if not 1<=a.k<=50 or a.limit<0 or a.limit>10000:raise ValueError('invalid_bounds')
 print(json.dumps(build(a) if a.mode=='build' else search(a),ensure_ascii=True))
if __name__=='__main__':main()
