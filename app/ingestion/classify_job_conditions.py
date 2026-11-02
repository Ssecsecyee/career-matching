"""Bounded source review backfill; default is read-only and makes no model call."""
import argparse,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'app/backend'))
from src.config import load_local_settings
from src.repositories.condition_reviews import ConditionReviewStore
from src.services.condition_review import condition_hash
from src.services.deadlines import VISIBLE_SQL

def run(connection_factory,classifier,*,limit=5,after_job_id=0,live=False,apply=False,stage=False):
    if apply:raise ValueError('Direct publication disabled; stage, verify and publish the draft')
    store=ConditionReviewStore(connection_factory)
    connection=connection_factory()
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT job_id,source,source_id,source_version,qualifications,preferred_requirements FROM job_postings WHERE job_id>%s AND recruitment_status IN ('active','unknown') AND "+VISIBLE_SQL+" ORDER BY job_id LIMIT 500",(after_job_id,))
            rows=cur.fetchall()
    finally:connection.close()
    result={'scanned':0,'reused':0,'planned':0,'saved':0,'staged':0,'reviewed':0,'failed':0,'next_after_job_id':after_job_id,'items':[]}
    work=0
    for job in rows:
        if work>=limit:break
        result['scanned']+=1;result['next_after_job_id']=job['job_id']
        cached=store.get(job)
        if cached:
            result['reused']+=1;continue
        item={'job_id':job['job_id'],'condition_hash':condition_hash(job)}
        work+=1
        if not live:
            result['planned']+=1;item['status']='model_not_called'
        else:
            try:
                review,usage=classifier.classify(job)
                item.update(review=review,usage=usage)
                if stage:
                    from src.repositories.condition_drafts import ConditionDraftStore
                    outcome=ConditionDraftStore(connection_factory).stage(job,review,usage)
                else:outcome=store.save(job,review,usage,apply=False)
                item.update(outcome);result['reviewed']+=1
                if outcome['status']=='staged':result['staged']+=1
            except Exception as exc:
                result['failed']+=1;item.update(status='failed',error_type=type(exc).__name__)
                # Preserve safe usage for cost accounting even for malformed/truncated outputs.
                if isinstance(getattr(exc,'usage',None),dict):item['usage']=exc.usage
        result['items'].append(item)
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--limit',type=int,default=5);p.add_argument('--after-job-id',type=int,default=0)
    p.add_argument('--live',action='store_true');p.add_argument('--stage',action='store_true');p.add_argument('--apply',action='store_true',help='Disabled: use staged approval')
    p.add_argument('--confirm-index-ready',action='store_true',help='Confirm new consumer/mapping/grants are ready before r: events')
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if not 1<=a.limit<=20 or a.after_job_id<0:p.error('Use limit 1..20 and nonnegative cursor')
    if a.apply:p.error('Direct publication disabled; use --stage then separate verification')
    if a.stage and not a.live:p.error('Stage requires --live')
    if a.output.exists():p.error('Choose a new report path')
    load_local_settings()
    if a.live and os.getenv('ENABLE_LIVE_BEDROCK')!='true':p.error('Explicit live model opt-in required')
    from incremental_jumpit import connect
    classifier=None
    if a.live:
        from src.bedrock.condition_classifier import ConditionClassifier
        classifier=ConditionClassifier(os.getenv('BEDROCK_MODEL_ID'),os.getenv('BEDROCK_REGION'))
    result=run(connect,classifier,limit=a.limit,after_job_id=a.after_job_id,live=a.live,apply=a.apply,stage=a.stage)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='items'}))
    return 1 if result['failed'] else 0
if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({'status':'failed','error_type':type(exc).__name__}));raise SystemExit(1)
