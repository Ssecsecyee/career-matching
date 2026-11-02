"""Explicit loopback-only mapping update; default prints a no-op plan."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'app/backend'))
from src.repositories.job_search_factory import LocalElasticTransport

def main():
    p=argparse.ArgumentParser();p.add_argument('--alias',default='career-jobs-local-read');p.add_argument('--apply',action='store_true');a=p.parse_args()
    if not a.alias.startswith('career-') or not a.alias.endswith('-read') or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-_' for c in a.alias):p.error('Invalid alias')
    mapping=json.loads((ROOT/'infra/elasticsearch/config/conditions.mapping.json').read_text(encoding='utf-8'))
    if not a.apply:print(json.dumps({'status':'planned_not_applied','fields':list(mapping['properties'])}));return
    request=LocalElasticTransport('http://127.0.0.1:19200')
    if len(request('GET','/_alias/'+a.alias,None))!=1:raise ValueError('Expected one index alias')
    request('PUT','/'+a.alias+'/_mapping',mapping)
    print(json.dumps({'status':'mapping_updated'}))
if __name__=='__main__':main()
