"""Existing-worker education read grant and bounded connection checks."""
import argparse
import base64
import json
from pathlib import Path
import sys
import boto3
from botocore.config import Config

ROOT=Path(__file__).resolve().parents[1]

GRANT="""import json,pathlib,pymysql
values=dict(line.split('=',1) for line in pathlib.Path('/opt/career/mysql-root.env').read_text().splitlines())
conn=pymysql.connect(host='127.0.0.1',port=3308,user='root',password=values['MYSQL_ROOT_PASSWORD'],database='career_matching',autocommit=True,connect_timeout=5,read_timeout=10)
try:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM mysql.user WHERE User='career_runtime' AND Host='%'")
        if cur.fetchone()[0]!=1:raise RuntimeError('Expected runtime account missing')
        cur.execute("GRANT SELECT ON career_matching.training_offerings TO 'career_runtime'@'%'")
        cur.execute('SELECT COUNT(*) FROM training_offerings');count=cur.fetchone()[0]
    print(json.dumps({'training_read_granted':True,'training_rows':count,'table_data_changes':0}))
finally:conn.close()
"""

VERIFY="""import sys,json
sys.path.insert(0,'/opt/career/app')
from worker import configure
configure()
from src.repositories.mysql_training import MySQLTrainingRepository
from src.repositories.mysql_connection import connect_mysql
repo=MySQLTrainingRepository(connect_mysql)
result={topic:repo.search([topic]) for topic in ['React','RAG']}
if not all(result.values()):raise RuntimeError('Expected topic results missing')
if not all(c['recommendation_eligible'] is False for cards in result.values() for c in cards):raise RuntimeError('Unverified sample exposed as application candidate')
print(json.dumps({'runtime_database_lookup':'passed','topic_counts':{k:len(v) for k,v in result.items()},'all_reference_only':True,'model_calls':0}))
"""

SMOKE="""import sys,json,os,secrets,uuid
sys.path.insert(0,'/opt/career/app')
from worker import configure
configure()
from src.handlers.dialogue import handle_request
payload={'action':'search','request_id':str(uuid.uuid4()),'message':'React를 공부하고 싶어. 저장된 교육 정보를 참고해서 학습 순서를 알려줘. 과거 회차라면 그렇게 설명해줘.'}
response=handle_request({'headers':{'Authorization':'Bearer '+os.environ['CHAT_API_TOKEN'],'X-Client-Token':secrets.token_hex(32)},'body':json.dumps(payload,ensure_ascii=False)})
data=json.loads(response['body']);courses=data.get('learning_opportunities',[])
ok=response['statusCode']==200 and len(courses)>0 and all(c['recommendation_eligible'] is False for c in courses) and '참고용' in data.get('message','')
print(json.dumps({'passed':ok,'http_status':response['statusCode'],'stage':data.get('stage'),'course_count':len(courses),'reference_warning_present':'참고용' in data.get('message',''),'session_id':data.get('session_id'),'error_code':data.get('error_code'),'synthetic_test_conversation':True,'real_bedrock_call':True}))
raise SystemExit(0 if ok else 1)
"""

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['grant','verify','smoke','result'])
    parser.add_argument('--check',choices=['grant','verify','smoke'],default='verify')
    args=parser.parse_args()
    state=json.loads((ROOT/'infra/.build/backend-state.json').read_text(encoding='utf-8'))
    sess=boto3.Session(profile_name=state['profile'],region_name=state['region'])
    config=Config(connect_timeout=5,read_timeout=40,retries={'mode':'standard','total_max_attempts':2})
    ssm=sess.client('ssm',config=config)
    check=args.check if args.action=='result' else args.action
    path=ROOT/'infra/.build'/('training-'+check+'-check.json')
    if args.action=='result':
        saved=json.loads(path.read_text(encoding='utf-8'))
        value=ssm.get_command_invocation(CommandId=saved['command_id'],InstanceId=saved['instance_id'])
        result={'status':value['Status'],'output':value.get('StandardOutputContent',''),'stderr_present':bool(value.get('StandardErrorContent'))}
        print(json.dumps(result,ensure_ascii=False))
        (ROOT/'infra/.build'/('training-'+check+'-result.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
        return
    if path.exists():raise ValueError('Check already submitted; inspect its result')
    stack=sess.client('cloudformation',config=config).describe_stacks(StackName=state['stack'])['Stacks'][0]
    instance=next(x['OutputValue'] for x in stack['Outputs'] if x['OutputKey']=='WorkerInstanceId')
    script={'grant':GRANT,'verify':VERIFY,'smoke':SMOKE}[check]
    # Error reporting omits exception arguments, source text and credentials.
    wrapper='import json\ntry:\n'+''.join('    '+line+'\n' for line in script.splitlines())+'\nexcept Exception as exc:\n    print(json.dumps({"error_type":type(exc).__name__,"error_code":getattr(exc,"response",{}).get("Error",{}).get("Code")}))\n    raise SystemExit(1)\n'
    encoded=base64.b64encode(wrapper.encode()).decode()
    command="/opt/career/venv/bin/python -c \"import base64;exec(base64.b64decode('"+encoded+"'))\""
    response=ssm.send_command(InstanceIds=[instance],DocumentName='AWS-RunShellScript',Parameters={'commands':[command]},TimeoutSeconds=180,Comment='Requested education connection '+check+'; no credentials in output')
    saved={'command_id':response['Command']['CommandId'],'instance_id':instance}
    path.write_text(json.dumps(saved),encoding='utf-8')
    print(json.dumps({'submitted':check,'command_id':saved['command_id']}))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('Training connection stopped: '+getattr(exc,'response',{}).get('Error',{}).get('Code',type(exc).__name__),file=sys.stderr)
        raise SystemExit(1)
