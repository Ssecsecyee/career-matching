"""HTTPS edge for the low-cost worker; authenticated owner-scoped asynchronous jobs."""
import hashlib
import hmac
import json
import os
import re
import time
from functools import lru_cache

from src.handlers.dialogue import response, validate_payload
from src.repositories.aws_secrets import read_secret


@lru_cache(maxsize=4)
def aws_client(name):
    import boto3
    from botocore.config import Config
    return boto3.Session(region_name=os.environ['AWS_REGION']).client(name,
        config=Config(connect_timeout=2,read_timeout=4,retries={'mode':'standard','total_max_attempts':2}))


class JobStore:
    def __init__(self, client=None):
        self.client=client or aws_client('dynamodb')
        self.table=os.environ['JOBS_TABLE']

    def get(self, job_id):
        row=self.client.get_item(TableName=self.table,Key={'job_id':{'S':job_id}},ConsistentRead=True).get('Item')
        if not row: return None
        return {k:(int(v['N']) if 'N' in v else v['S']) for k,v in row.items()}

    def create(self, row):
        item={k:({'N':str(v)} if isinstance(v,int) else {'S':v}) for k,v in row.items()}
        try:
            self.client.put_item(TableName=self.table,Item=item,ConditionExpression='attribute_not_exists(job_id)')
            return True
        except self.client.exceptions.ConditionalCheckFailedException:
            return False

    def progress(self,job_id,text,version):
        if not isinstance(text,str) or not 1<=len(text)<=5000 or type(version) is not int or version<1:
            raise ValueError('Invalid draft snapshot')
        try:
            self.client.update_item(TableName=self.table,Key={'job_id':{'S':job_id}},
                UpdateExpression='SET partial_text=:text, partial_version=:version',
                ConditionExpression='attribute_exists(job_id) AND #s <> :done AND expires_at > :now',
                ExpressionAttributeNames={'#s':'state'},ExpressionAttributeValues={
                    ':text':{'S':text},':version':{'N':str(version)},':done':{'S':'done'},':now':{'N':str(int(time.time()))}})
        except self.client.exceptions.ConditionalCheckFailedException:
            return False
        return True

    def complete(self, job_id, result):
        self.client.update_item(TableName=self.table,Key={'job_id':{'S':job_id}},
            UpdateExpression='SET #s=:done, response_json=:response REMOVE payload_json, client_token, partial_text, partial_version',
            ExpressionAttributeNames={'#s':'state'},ExpressionAttributeValues={':done':{'S':'done'},':response':{'S':json.dumps(result,ensure_ascii=False)}})


def authorize(headers):
    headers={k.lower():v for k,v in headers.items()}
    token=read_secret(os.environ['CHAT_SECRET_ARN']).get('token','')
    if len(token)<32 or not hmac.compare_digest(headers.get('authorization',''),'Bearer '+token):
        return None
    identity=headers.get('x-client-token','')
    if not isinstance(identity,str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,128}',identity): return None
    owner=hmac.new(token.encode(),identity.encode(),hashlib.sha256).hexdigest()
    return owner,identity


def handle(event, *, store=None, queue=None, auth=None):
    http=event.get('requestContext',{}).get('http',{})
    method,path=http.get('method'),http.get('path','')
    if method=='GET' and path=='/api/health':
        return response(200,{'status':'ok','mode':'queued_worker','database_ready':'check worker status before connecting web'})
    if (method,path)!=('POST','/api/chat') and not (method=='GET' and re.fullmatch(r'/api/jobs/[a-f0-9]{64}',path)):
        return response(404,{'status':'not_found'})
    identity=auth if auth is not None else authorize(event.get('headers',{}))
    if not identity: return response(401,{'status':'unauthorized'})
    owner,client_token=identity
    store=store or JobStore()
    if method=='GET':
        row=store.get(path.rsplit('/',1)[1])
        return job_response(row,owner)
    try:
        raw=event.get('body','')
        if event.get('isBase64Encoded') or not isinstance(raw,str) or len(raw)>24000: raise ValueError()
        payload=validate_payload(json.loads(raw))
    except (ValueError,TypeError,KeyError,AttributeError):
        return response(400,{'status':'invalid_request'})
    request_id=payload['request_id']
    job_id=hashlib.sha256((owner+':'+request_id).encode()).hexdigest()
    fingerprint=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    row={'job_id':job_id,'owner':owner,'client_token':client_token,'fingerprint':fingerprint,
         'payload_json':json.dumps(payload,ensure_ascii=False),'state':'queued','expires_at':int(time.time())+86400}
    created=store.create(row)
    if not created:
        row=store.get(job_id)
        if not row or row.get('fingerprint')!=fingerprint:
            return response(409,{'status':'request_id_reused_with_different_content'})
        return job_response(row,owner)
    try:
        (queue or aws_client('sqs')).send_message(QueueUrl=os.environ['WORK_QUEUE_URL'],MessageBody=json.dumps({'job_id':job_id}))
    except Exception:
        # Leave a visible failure for this request; do not leave a permanently queued browser.
        result=response(503,{'status':'queue_submission_failed','retryable':True,'retry_after_seconds':10})
        store.complete(job_id,result)
        return result
    return job_response(row,owner)


def job_response(row,owner):
    if not row or not hmac.compare_digest(row.get('owner',''),owner): return response(404,{'status':'job_not_found'})
    if row['expires_at']<=int(time.time()): return response(410,{'status':'job_expired'})
    if row['state']=='done': return json.loads(row['response_json'])
    value={'status':'processing','job_id':row['job_id'],'poll_after_ms':500}
    if isinstance(row.get('partial_text'),str) and 0<len(row['partial_text'])<=5000:
        value.update(partial_text=row['partial_text'],partial_version=row.get('partial_version',0),draft=True)
    return response(202,value)


def lambda_handler(event,context):
    try: return handle(event)
    except Exception as exc:
        from src.services.dependency_errors import error_code
        return response(503,{'status':'queue_dependency_failed','error_code':error_code(exc)})
