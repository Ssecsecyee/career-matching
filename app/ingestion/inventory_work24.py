"""Read-only Work24 education inventory from existing MySQL; no API/AWS calls."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
from incremental_jumpit import connect


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    if args.output.exists():ap.error('output_already_exists')
    try:
        conn=connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT source_id,content_hash,source_version,fetched_at,JSON_UNQUOTE(JSON_EXTRACT(raw_detail,'$.collection_metadata.list_detail_fingerprint')) AS list_detail_fingerprint,JSON_UNQUOTE(JSON_EXTRACT(raw_detail,'$.collection_metadata.validation_level')) AS validation_level FROM training_offerings WHERE source=%s",('goyong24_training',))
                rows=cur.fetchall()
        finally:conn.close()
        for row in rows:
            value=row.get('fetched_at')
            if isinstance(value,datetime):row['fetched_at']=(value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).isoformat()
        output={'generated_at':datetime.now(timezone.utc).isoformat(),'source':'goyong24_training','records':rows,'database_writes':0}
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open('x',encoding='utf-8') as f:json.dump(output,f,ensure_ascii=False,indent=2)
        print(json.dumps({'known':len(rows),'database_writes':0}));return 0
    except Exception as exc:
        code=exc.args[0] if exc.args and type(exc.args[0]) is int else None
        print(json.dumps({'status':'inventory_unavailable','error_type':type(exc).__name__,'driver_code':code,'database_writes':0}));return 1
if __name__=='__main__':raise SystemExit(main())
