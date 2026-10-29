import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'app/backend'),str(ROOT/'app/ingestion')]
from src.config import load_local_settings
from src.repositories.mysql_connection import connect_mysql
from ingest_training import prepare,insert_new
load_local_settings()
if os.getenv('MYSQL_HOST')!='127.0.0.1' or os.getenv('MYSQL_PORT')!='3308':
    raise ValueError('Expected local development database only')
records={}
for name in ['boottent_20261028_real01','boottent_20261028_real02']:
    data=json.loads((ROOT/'workspace/incoming/boottent'/name/'input.json').read_text(encoding='utf-8-sig'))
    for row in prepare(data):records[row['source'],row['source_id']]=row
if len(records)!=7:raise ValueError('Expected seven preserved source records')
conn=connect_mysql(credentials=('root',os.environ['MYSQL_ADMIN_PASSWORD']))
conn.autocommit(False)
try:
    result=insert_new(list(records.values()),conn)
    conn.commit()
finally:conn.close()
print(json.dumps({'local_training_import':result,'aws_operations':0,'source_status':'unknown'}))
