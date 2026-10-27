"""AWS HTTP entry and separate IAM-only database inspection entry."""
import os

from src.handlers.dialogue import lambda_handler as dialogue_handler, response
from src.repositories.aws_secrets import configure_chat
from src.repositories.mysql_connection import connect_mysql
from src.services.dependency_errors import error_code

def lambda_handler(event, context):
    http = event.get('requestContext',{}).get('http',{})
    method, path = http.get('method'), http.get('path')
    if method=='GET' and path=='/api/health':
        return response(200,{'status':'ok','mode':'aws','service':'career-matching'})
    if method!='POST' or path!='/api/chat':
        return response(404,{'status':'not_found'})
    try:
        configure_chat()
    except Exception as exc:
        return response(503,{'status':'configuration_dependency_failed','error_code':error_code(exc)})
    return dialogue_handler(event,context)

def inspect_handler(event, context):
    # Not attached to API Gateway. Invoke only with AWS IAM permission.
    if event != {'action':'summary'}:
        return {'status':'invalid_inspection_request'}
    try:
        with connect_mysql() as conn:
            with conn.cursor() as cur:
                result={}
                for table in ('job_postings','chat_sessions','chat_messages','recommendation_evidence','model_invocations','response_cache'):
                    cur.execute('SELECT COUNT(*) AS n FROM '+table)
                    result[table]=cur.fetchone()['n']
                cur.execute('SELECT recruitment_status,COUNT(*) AS n FROM job_postings GROUP BY recruitment_status')
                result['job_status_counts']=cur.fetchall()
                cur.execute('SELECT model_id,status,COUNT(*) AS calls,SUM(input_tokens) AS input_tokens,SUM(output_tokens) AS output_tokens,SUM(cache_read_input_tokens) AS cache_read_input_tokens,SUM(cache_write_input_tokens) AS cache_write_input_tokens FROM model_invocations GROUP BY model_id,status')
                result['model_usage']=cur.fetchall()
                for row in result['model_usage']:
                    for key in row:
                        if key not in {'model_id','status'} and row[key] is not None:
                            row[key]=int(row[key])
                return {'status':'ok','database':result,'note':'Application counters only; billing is in AWS Cost Explorer.'}
    except Exception as exc:
        return {'status':'inspection_failed','error_code':error_code(exc)}
