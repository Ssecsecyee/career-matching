"""IAM-only initial import of two fixed, hash-verified deployment artifacts."""
import gzip
import hashlib
import os

from src.repositories.aws_secrets import read_secret
from src.repositories.mysql_connection import connect_mysql
from src.services.dependency_errors import error_code

def sql_statements(text):
    text='\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('--'))
    quote=None
    escaped=False
    part=[]
    for char in text:
        if escaped:
            escaped=False
        elif char=='\\' and quote:
            escaped=True
        elif char in "'\"`":
            if quote==char: quote=None
            elif quote is None: quote=char
        if char==';' and quote is None:
            if ''.join(part).strip(): yield ''.join(part)
            part=[]
        else: part.append(char)
    if quote: raise ValueError('Unterminated SQL literal')
    if ''.join(part).strip(): yield ''.join(part)

def lambda_handler(event, context):
    if event != {'action':'initialize'}:
        return {'status':'invalid_bootstrap_request'}
    connection=None
    try:
        import boto3
        from botocore.config import Config
        s3=boto3.Session(region_name=os.environ['AWS_REGION']).client('s3',config=Config(connect_timeout=3,read_timeout=15,retries={'mode':'standard','total_max_attempts':2}))
        sources=[]
        for key, checksum in [('SCHEMA_KEY','SCHEMA_SHA256'),('DATA_KEY','DATA_SHA256')]:
            body=s3.get_object(Bucket=os.environ['ARTIFACT_BUCKET'],Key=os.environ[key])['Body']
            try: data=body.read(40*1024*1024+1)
            finally: body.close()
            if len(data)>40*1024*1024 or hashlib.sha256(data).hexdigest()!=os.environ[checksum]:
                raise ValueError('Artifact checksum or size mismatch')
            if os.environ[key].endswith('.gz'): data=gzip.decompress(data)
            if len(data)>80*1024*1024: raise ValueError('Expanded SQL exceeds budget')
            sources.append(data.decode('utf-8-sig'))
        admin=read_secret(os.environ['ADMIN_SECRET_ARN'])
        runtime=read_secret(os.environ['MYSQL_SECRET_ARN'])
        if runtime['username']!='career_runtime': raise ValueError('Unexpected runtime user')
        connection=connect_mysql(credentials=(admin['username'],admin['password']))
        with connection.cursor() as cur:
            for text in sources:
                for statement in sql_statements(text): cur.execute(statement)
            cur.execute("CREATE USER IF NOT EXISTS 'career_runtime'@'%%' IDENTIFIED BY %s REQUIRE SSL",(runtime['password'],))
            cur.execute("ALTER USER 'career_runtime'@'%%' IDENTIFIED BY %s REQUIRE SSL",(runtime['password'],))
            for table in ('job_postings','training_offerings'):
                cur.execute('GRANT SELECT ON career_matching.'+table+" TO 'career_runtime'@'%'")
            for table in ('chat_sessions','chat_messages','recommendation_evidence','model_invocations','response_cache'):
                cur.execute('GRANT SELECT,INSERT,UPDATE,DELETE ON career_matching.'+table+" TO 'career_runtime'@'%'")
            cur.execute("SELECT COUNT(*) AS n FROM job_postings WHERE source='jumpit'")
            count=cur.fetchone()['n']
            if count<int(os.environ['EXPECTED_JOBS']): raise ValueError('Imported row count below expected snapshot count')
        return {'status':'initialized','jobs':count,'note':'Source snapshots remain unverified. Disable bootstrap in the next stack update.'}
    except Exception as exc:
        if connection: connection.rollback()
        return {'status':'bootstrap_failed','error_code':error_code(exc)}
    finally:
        if connection: connection.close()
