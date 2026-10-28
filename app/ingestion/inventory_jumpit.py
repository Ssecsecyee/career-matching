"""Export source IDs and due checks only; no scraping, model calls, or DB writes."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import re
from pathlib import Path
from incremental_jumpit import connect, sql_date


def inventory(rows, *, now=None, dated_days=3, unknown_days=7, limit=100):
    now=now or datetime.now(timezone.utc)
    current=now.astimezone(timezone.utc).replace(tzinfo=None)
    known=[];due=[];excluded=[]
    for row in rows:
        identity=str(row['source_id']);known.append(identity)
        deadline=sql_date(row.get('deadline_at'))
        status=row['recruitment_status']
        if status in {'closed','unavailable'} or (row.get('deadline_type')!='always_open' and deadline and deadline<=current):
            excluded.append(identity);continue
        fetched=sql_date(row['fetched_at'])
        days=dated_days if row.get('deadline_type')=='fixed_date' and deadline else unknown_days
        next_check=fetched+timedelta(days=days)
        if next_check<=current:
            due.append({'source_id':identity,'source_url':'https://jumpit.saramin.co.kr/position/'+identity,
                'last_checked_at':fetched.isoformat()+'Z','due_at':next_check.isoformat()+'Z'})
    due.sort(key=lambda x:(x['due_at'],x['source_id']))
    return {'schema_version':1,'generated_at':now.isoformat(),'known_ids':known,'recheck_due':due[:limit],
        'remaining_due_count':max(0,len(due)-limit),'skip_routine_details':excluded,
        'note':'Dates are scheduling hints. Missing from a list or past deadline does not independently verify closure.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:
        if args.output.exists():raise ValueError('output_already_exists')
        connection=connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT source_id,recruitment_status,deadline_type,deadline_at,fetched_at FROM job_postings WHERE source=%s",('jumpit',))
                result=inventory(cursor.fetchall())
        finally:connection.close()
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open('x',encoding='utf-8') as output:json.dump(result,output,ensure_ascii=False,indent=2)
        print(json.dumps({'known':len(result['known_ids']),'recheck_due':len(result['recheck_due']),'database_writes':0}))
    except Exception as exc:
        # Show only numeric driver codes; never print server text, SQL or credentials.
        code = exc.args[0] if exc.args and type(exc.args[0]) is int else None
        suffix = ' [code=' + str(code) + ']' if code is not None else ''
        allowed={'replace_ingestion_password_placeholder','configure_ingestion_environment','invalid_ingestion_env_key','output_already_exists','remote_mysql_requires_verified_tls'}
        if type(exc) is ValueError and str(exc) in allowed:
            suffix += ' [' + str(exc) + ']'
        parser.exit(2, 'Inventory stopped: ' + type(exc).__name__ + suffix +
                    '; check settings, tunnel, and output path.\n')

if __name__=='__main__':main()
