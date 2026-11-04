"""Offline completeness audit of a Work24 inventory run. No network or SQL writes."""
import argparse
from collections import Counter
from datetime import datetime
import gzip
import json
from pathlib import Path
import sqlite3
from work24_collect import identity,parse,KST,start_state


def audit(catalog,folder,run):
    db=sqlite3.connect(catalog.resolve().as_uri()+'?mode=ro',uri=True)
    status=db.execute('SELECT status,start,end FROM runs WHERE id=?',(run,)).fetchone()
    if status is None:raise ValueError('unknown_run')
    today=datetime.now(KST).date();totals={};buckets=[];global_records={};returned_by_service=Counter()
    for service,start,end,next_page,expected,bucket_status in db.execute('SELECT service,start,end,page,total,status FROM buckets WHERE run=? ORDER BY service,start',(run,)):
        if bucket_status=='split':continue
        records={};returned=0;observations=[]
        for page, in db.execute('SELECT page FROM pages WHERE run=? AND service=? AND start=? AND end=? ORDER BY page',(run,service,start,end)):
            path=folder/'pages'/service/(start+'_'+end)/(str(page)+'.xml.gz')
            with gzip.open(path,'rb') as source:reported,rows=parse(source.read())
            observations.append(reported);returned+=len(rows)
            for row in rows:
                key=identity(row);records[key]={'traStartDate':row.get('traStartDate')}
                global_records.setdefault(service,{})[key]=(row.get('traStartDate'),row.get('trprId'),row.get('trainstCstId'))
            returned_by_service[service]+=len(rows)
        counts=Counter(start_state(row,today) for row in records.values())
        buckets.append({'service':service,'start':start,'end':end,'status':bucket_status,'unique':len(records),'returned':returned,'duplicate_rows':returned-len(records),'last_provider_count':expected,'provider_counts_changed':len(set(observations))>1,'count_difference':None if expected is None else len(records)-expected})
        item=totals.setdefault(service,{'unique':0,'started':0,'future':0,'unknown':0,'duplicate_rows':0,'distinct_courses':0})
        item['unique']+=len(records);item['duplicate_rows']+=returned-len(records)
        for state,count in counts.items():item[state]+=count
    for service,records in global_records.items():
        states=Counter(start_state({'traStartDate':value[0]},today) for value in records.values())
        totals[service]={'unique':len(records),'distinct_courses':len({(value[1],value[2]) for value in records.values()}),'started':states['started'],'future':states['future'],'unknown':states['unknown'],'duplicate_rows':returned_by_service[service]-len(records)}
    db.close()
    warnings=[]
    if any(b['status']!='done' for b in buckets):warnings.append('collection_in_progress_or_stopped')
    if any(b['count_difference'] not in (0,None) for b in buckets):warnings.append('provider_count_reconciliation_required')
    if any(b['provider_counts_changed'] for b in buckets):warnings.append('provider_changed_during_collection')
    return {'run':run,'status':status[0],'start':status[1],'end':status[2],'as_of_kst':datetime.now(KST).isoformat(),'services':totals,'buckets':buckets,'warnings':warnings,'frozen_snapshot':False,'aws_db_comparison':'not_performed','operational_database_writes':0}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--catalog',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--run-id',required=True);args=ap.parse_args()
    value=audit(args.catalog,args.output,args.run_id)
    (args.output/'reconciliation.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# 고용24 훈련 목록 수집 결과','',f"범위: 훈련 시작일 {value['start']} ~ {value['end']}",f"집계 기준: {value['as_of_kst']}",f"수집 상태: {value['status']}",'','| API | 과정·기관 수 | 회차 포함 고유 수집 | 이미 시작(당일 포함) | 시작 전 | 시작일 미확인 |','|---|---:|---:|---:|---:|---:|']
    for service,item in value['services'].items():lines.append(f"| {service} | {item.get('distinct_courses',0)} | {item['unique']} | {item['started']} | {item['future']} | {item['unknown']} |")
    lines+=['','검증 알림: '+(', '.join(value['warnings']) or '건수 대조 이상 없음'),'','원천은 페이지 조회 도중 바뀔 수 있으므로 고정 시점의 전체 스냅샷이라고 주장하지 않는다. 응답 총수·중복·고유 건수는 reconciliation.json에 분리했다.','고유 수집 건수는 서비스·과정·회차·기관 기준이다. distinct_courses는 회차를 제외한 서비스별 과정·기관 수로, 반복 회차를 서로 다른 교육 주제로 해석하지 않는다.','이미 시작한 과정은 실제 모집 마감으로 기록하지 않고 신청 후보에서 제외한다. 시작 전 과정도 신청 가능이 확인된 것은 아니다.','신규/변경은 로컬 수집 카탈로그 비교 기준이다. AWS MySQL과 비교·적재·ES 갱신은 아직 하지 않았다.']
    (args.output/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'status':value['status'],'services':value['services'],'warnings':value['warnings']},ensure_ascii=False))
    return 0
if __name__=='__main__':raise SystemExit(main())
