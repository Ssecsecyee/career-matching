"""Read-only full-index snapshot including current valid condition reviews."""
import argparse,json,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'app/backend'));sys.path.insert(0,str(ROOT/'app/ingestion'))
from incremental_jumpit import connect
from src.repositories.condition_reviews import ConditionReviewStore
from src.repositories.mysql_jobs import decode_row
from src.services.deadlines import VISIBLE_SQL,effective_deadline

def export(connection):
    with connection.cursor() as cur:
        cur.execute("SELECT * FROM job_postings WHERE recruitment_status IN ('active','unknown') AND "+VISIBLE_SQL+" ORDER BY job_id")
        rows=cur.fetchall()
    result=[]
    for raw in rows:
        row=decode_row(raw);review=ConditionReviewStore.load(connection,row)
        if review is not None:row['condition_review']=review
        row['deadline_at']=effective_deadline(row)
        for k,v in list(row.items()):
            if isinstance(v,datetime):row[k]=(v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v).isoformat()
        result.append(row)
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():p.error('Choose a new snapshot path')
    db=connect()
    try:
        # Consistent read: original rows and derived classifications share one DB snapshot.
        db.begin();rows=export(db);db.rollback()
    finally:db.close()
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(rows,ensure_ascii=False,default=str,indent=2),encoding='utf-8')
    print(json.dumps({'exported':len(rows),'classified':sum('condition_review' in r for r in rows)}))
if __name__=='__main__':main()
