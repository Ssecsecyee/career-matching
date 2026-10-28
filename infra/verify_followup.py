"""Synthetic end-to-end regression for React lookup and education comparison."""
import argparse
import base64
import json
from pathlib import Path
import sys
import boto3
from botocore.config import Config

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'infra/.build/followup-regression-state.json'
SCRIPT="""import json,os,secrets,sys,uuid
sys.path.insert(0,'/opt/career/app')
from worker import configure
configure()
from src.handlers.dialogue import handle_request
from src.repositories.mysql_jobs import MySQLJobRepository
from src.repositories.mysql_connection import connect_mysql
from src.schemas.search import SearchPlan
repo=MySQLJobRepository(connect_mysql,include_unverified=True)
counts={word:repo.search(SearchPlan(keyword=word,skills=('React',)))[0] for word in ['react','React','REACT']}
if min(counts.values())<=0 or len(set(counts.values()))!=1:raise RuntimeError('React casefold regression')
from src.bedrock.client import BedrockPlanner
plans=[];raw_model=[]
from src.bedrock.client import runtime_client
class RecordingClient:
    def converse(self,**kwargs):
        result=runtime_client(os.environ['BEDROCK_REGION']).converse(**kwargs)
        raw_model.append({'stop':result.get('stopReason'),'text':''.join(b.get('text','') for b in result['output']['message']['content'])})
        return result
class Probe(BedrockPlanner):
    def route(self,message,history):
        result,usage=super().route(message,history)
        plans.append({k:v for k,v in result.items() if k in ('intent','plan')})
        return result,usage
probe=Probe(os.environ['MODEL_ID'],os.environ['BEDROCK_REGION'],client=RecordingClient())
owner=secrets.token_hex(32);session=None
def request(action,**kwargs):
    global session
    payload={'action':action,'request_id':str(uuid.uuid4()),**kwargs}
    if session:payload['session_id']=session
    response=handle_request({'headers':{'Authorization':'Bearer '+os.environ['CHAT_API_TOKEN'],'X-Client-Token':owner},'body':json.dumps(payload,ensure_ascii=False)},planner=probe)
    data=json.loads(response['body'])
    if response['statusCode']!=200:
        print(json.dumps({'synthetic_model_output':raw_model[-1:]},ensure_ascii=False))
        raise RuntimeError('Synthetic request failed: '+str(data.get('error_code') or data.get('status')))
    session=data['session_id'];return data
first=request('search',message='안녕 react 관련 공고가 있을까 최근 수업을 들어서 할만할거 같아')
if first['stage']!='choose_job' or first.get('total',0)<=0:
    print(json.dumps({'synthetic_first_stage':first['stage'],'synthetic_plan':plans},ensure_ascii=False))
    raise RuntimeError('Natural language React search regression')
job=next((j for j in first['candidate_jobs'] if repo.get(j['source_id']).get('qualifications')),None)
if not job:raise RuntimeError('No qualifying synthetic test candidate')
result=request('select',source_id=job['source_id'],grouped=True)
for index in range(3):
    if result['stage'] not in {'checking_required','checking_preferred'}:break
    result=request('answer_batch',answers=[{'question_id':q['question_id'],'assessment':'unmet','detail':'합성 회귀 테스트의 명시적 자기평가'} for q in result['questions']])
courses=result.get('learning_opportunities',[])
if not courses:raise RuntimeError('Completion education lookup regression')
identities=[(c['source'],c['source_id'],c['source_version']) for c in courses]
reply=request('search',message='이중 어떤걸 제일 추천해?')
compared=reply.get('learning_opportunities',[])
same=[(c['source'],c['source_id'],c['source_version']) for c in compared]==identities
text=reply.get('message','')
named=any(c['title'] in text or (c.get('provider_name') and c['provider_name'] in text) for c in courses)
wrong=any(phrase in text for phrase in ['공고 하나만','공고가 하나','다른 공고가 없는','교육 목록을 받지 못'])
ok=same and named and not wrong and '참고용' in text
report={'passed':ok,'react_counts':counts,'natural_language_job_total':first['total'],'completion_course_count':len(courses),'comparison_same_sources_and_versions':same,'named_an_actual_education':named,'wrong_job_only_reply':wrong,'reference_warning_present':'참고용' in text,'synthetic_session_id':session,'comparison_reply':text,'synthetic_test_only':True}
print(json.dumps(report,ensure_ascii=False))
raise SystemExit(0 if ok else 1)
"""

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['submit','result']);args=parser.parse_args()
    state=json.loads((ROOT/'infra/.build/backend-state.json').read_text(encoding='utf-8'))
    sess=boto3.Session(profile_name=state['profile'],region_name=state['region'])
    config=Config(connect_timeout=5,read_timeout=40,retries={'mode':'standard','total_max_attempts':2})
    ssm=sess.client('ssm',config=config)
    if args.action=='result':
        saved=json.loads(STATE.read_text(encoding='utf-8'))
        result=ssm.get_command_invocation(CommandId=saved['command_id'],InstanceId=saved['instance_id'])
        report={'status':result['Status'],'output':result.get('StandardOutputContent',''),'stderr_present':bool(result.get('StandardErrorContent'))}
        print(json.dumps(report,ensure_ascii=False))
        (ROOT/'infra/.build/followup-regression-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        return
    if STATE.exists():raise ValueError('Already submitted; inspect result')
    stack=sess.client('cloudformation',config=config).describe_stacks(StackName=state['stack'])['Stacks'][0]
    instance=next(x['OutputValue'] for x in stack['Outputs'] if x['OutputKey']=='WorkerInstanceId')
    wrapper='import json\ntry:\n'+''.join('    '+line+'\n' for line in SCRIPT.splitlines())+'\nexcept Exception as exc:\n    print(json.dumps({"error_type":type(exc).__name__,"error_code":getattr(exc,"response",{}).get("Error",{}).get("Code"),"test_failure":str(exc)[:160] if type(exc) is RuntimeError else None}))\n    raise SystemExit(1)\n'
    encoded=base64.b64encode(wrapper.encode()).decode()
    command="/opt/career/venv/bin/python -c \"import base64;exec(base64.b64decode('"+encoded+"'))\""
    response=ssm.send_command(InstanceIds=[instance],DocumentName='AWS-RunShellScript',Parameters={'commands':[command]},TimeoutSeconds=240,Comment='Synthetic regression: React jobs, grouped checks, same education comparison')
    STATE.write_text(json.dumps({'command_id':response['Command']['CommandId'],'instance_id':instance}),encoding='utf-8')
    print(json.dumps({'submitted':True,'command_id':response['Command']['CommandId']}))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('Regression stopped: '+getattr(exc,'response',{}).get('Error',{}).get('Code',type(exc).__name__),file=sys.stderr)
        raise SystemExit(1)
