"""Synthetic HTTPS end-to-end check: partial content must arrive before final JSON."""
import argparse
import base64
import json
from pathlib import Path
import sys
import boto3
from botocore.config import Config

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'infra/.build/streaming-smoke-state.json'
SCRIPT="""import json,os,secrets,sys,time,urllib.request,urllib.error,uuid
sys.path.insert(0,'/opt/career/app')
from worker import configure
configure()
base='https://d1elpjlek4sj83.cloudfront.net'
headers={'Content-Type':'application/json','Authorization':'Bearer '+os.environ['CHAT_API_TOKEN'],'X-Client-Token':secrets.token_hex(32)}
def fetch(path,payload=None):
    req=urllib.request.Request(base+path,headers=headers,data=json.dumps(payload,ensure_ascii=False).encode() if payload is not None else None)
    try:
        with urllib.request.urlopen(req,timeout=20) as response:return response.status,json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code,json.load(exc)
started=time.monotonic()
status,data=fetch('/api/chat',{'action':'search','request_id':str(uuid.uuid4()),'message':'React를 배우고 있어. 저장된 교육을 참고해 기초부터 프로젝트까지 공부하는 순서를 5단계로 설명해줘. 전체 450자 이내로 설명해줘.'})
if status!=202:raise RuntimeError('Expected asynchronous submission')
job=data['job_id'];snapshots=[];last='';first_partial=None
for index in range(160):
    time.sleep(0.5)
    status,data=fetch('/api/jobs/'+job)
    if status==202:
        partial=data.get('partial_text','')
        if partial and partial!=last:
            if not partial.startswith(last):raise RuntimeError('Non-monotonic draft')
            last=partial
            elapsed=round(time.monotonic()-started,3)
            if first_partial is None:first_partial=elapsed
            snapshots.append({'seconds':elapsed,'characters':len(partial),'version':data.get('partial_version')})
        continue
    break
final_seconds=round(time.monotonic()-started,3)
ok=status==200 and bool(snapshots) and data.get('message','').startswith(last) and first_partial<final_seconds
if status==200:
    from src.repositories.mysql_connection import connect_mysql
    conn=connect_mysql()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT status,input_tokens,output_tokens FROM model_invocations WHERE session_id=%s ORDER BY started_at',(data['session_id'],))
            invocations=cur.fetchall()
    finally:conn.close()
else:invocations=[]
report={'passed':ok,'http_status':status,'draft_snapshots':snapshots,'first_partial_seconds':first_partial,'final_seconds':final_seconds,'final_characters':len(data.get('message','')),'final_prefix_matches':data.get('message','').startswith(last) if last else False,'invocations':invocations,'error_code':data.get('error_code'),'synthetic_test_only':True,'browser_transport':'owner_scoped_polling','model_transport':'ConverseStream'}
print(json.dumps(report))
raise SystemExit(0 if ok else 1)
"""

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['submit','result']);args=parser.parse_args()
    state=json.loads((ROOT/'infra/.build/backend-state.json').read_text(encoding='utf-8'))
    sess=boto3.Session(profile_name=state['profile'],region_name=state['region'])
    config=Config(connect_timeout=5,read_timeout=30,retries={'mode':'standard','total_max_attempts':2})
    ssm=sess.client('ssm',config=config)
    if args.action=='result':
        saved=json.loads(STATE.read_text(encoding='utf-8'))
        value=ssm.get_command_invocation(CommandId=saved['command_id'],InstanceId=saved['instance_id'])
        result={'status':value['Status'],'output':value.get('StandardOutputContent',''),'stderr_present':bool(value.get('StandardErrorContent'))}
        print(json.dumps(result))
        (ROOT/'infra/.build/streaming-smoke-result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        return
    if STATE.exists():raise ValueError('Already submitted; inspect result')
    stack=sess.client('cloudformation',config=config).describe_stacks(StackName=state['stack'])['Stacks'][0]
    instance=next(x['OutputValue'] for x in stack['Outputs'] if x['OutputKey']=='WorkerInstanceId')
    wrapper='import json\ntry:\n'+''.join('    '+line+'\n' for line in SCRIPT.splitlines())+'\nexcept Exception as exc:\n    print(json.dumps({"error_type":type(exc).__name__,"error_code":getattr(exc,"response",{}).get("Error",{}).get("Code")}))\n    raise SystemExit(1)\n'
    encoded=base64.b64encode(wrapper.encode()).decode()
    command="/opt/career/venv/bin/python -c \"import base64;exec(base64.b64decode('"+encoded+"'))\""
    result=ssm.send_command(InstanceIds=[instance],DocumentName='AWS-RunShellScript',Parameters={'commands':[command]},TimeoutSeconds=180,Comment='Synthetic web API test: real model stream before completion, no token output')
    STATE.write_text(json.dumps({'command_id':result['Command']['CommandId'],'instance_id':instance}),encoding='utf-8')
    print(json.dumps({'submitted':True,'command_id':result['Command']['CommandId']}))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('Streaming smoke stopped: '+getattr(exc,'response',{}).get('Error',{}).get('Code',type(exc).__name__),file=sys.stderr)
        raise SystemExit(1)
