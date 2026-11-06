"""One short admin API smoke. Credentials never printed or persisted."""
import json,secrets,time,urllib.request,urllib.error,sys
from uuid import uuid4
from pathlib import Path
import boto3
s=boto3.Session(profile_name='myisb_IsbUsersPS-954935267704',region_name='ap-northeast-2')
out={x['OutputKey']:x['OutputValue'] for x in s.client('cloudformation').describe_stacks(StackName='career-backend-test-v2')['Stacks'][0]['Outputs']}
auth=json.loads(s.client('secretsmanager').get_secret_value(SecretId=out['AuthSecretArn'])['SecretString'])
headers={'Content-Type':'application/json','Authorization':'Bearer '+auth['admin_token'],'X-Client-Token':secrets.token_hex(32)}
request_id=str(uuid4());payload={'action':'search','engine':'agentcore','message':sys.argv[1] if len(sys.argv)>1 else '안녕. 짧게 인사만 해줘.','request_id':request_id}
def read(req):
 try:
  with urllib.request.urlopen(req,timeout=15) as r:return r.status,json.load(r)
 except urllib.error.HTTPError as e:return e.code,json.loads(e.read())
code,v=read(urllib.request.Request(out['ApiEndpoint']+'/api/chat',data=json.dumps(payload).encode(),headers=headers))
if code==202:
 job=v['job_id']
 for _ in range(100):
  time.sleep(.6);code,v=read(urllib.request.Request(out['ApiEndpoint']+'/api/jobs/'+job,headers=headers))
  if code!=202:break
report={'http':code,'request_id':request_id,**{k:v.get(k) for k in ('stage','engine','total','message','status','error_code','error_type')}}
print(json.dumps(report,ensure_ascii=True))
Path(__file__).resolve().parents[1].joinpath('.build/agentcore-smoke-result.json').write_text(json.dumps(report,ensure_ascii=False),encoding='utf-8')
if code!=200 or v.get('engine')!='agentcore':raise SystemExit(1)
