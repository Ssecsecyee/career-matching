"""Build a code-only condition-review bundle; no secrets, data, AWS or SQL execution."""
from datetime import datetime,timezone
import hashlib,json,secrets
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
ROOT=Path(__file__).resolve().parents[1]

def build():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+secrets.token_hex(3)
    folder=ROOT/'infra/.build'/('condition-review-'+stamp);folder.mkdir(parents=True,exist_ok=False)
    files=list((ROOT/'app/backend/src').rglob('*.py'))
    names=['app/backend/database/condition_question_cache_migration.sql','infra/elasticsearch/verify_condition_review_v2.py','infra/elasticsearch/install_condition_review_v2.py','app/ingestion/condition_draft_actions.py','app/backend/database/condition_draft_migration.sql','infra/elasticsearch/install_condition_reviews.py','app/ingestion/run_condition_reviews_host.py','app/backend/database/condition_review_migration.sql','app/backend/requirements.validation.txt',
      'app/ingestion/classify_job_conditions.py','app/ingestion/incremental_jumpit.py','app/ingestion/normalize_jumpit.py',
      'app/ingestion/normalize_all_jumpit.py','app/ingestion/export_mysql_data.py','app/ingestion/page_extraction.py',
      'app/ingestion/search_index/sync_outbox.py','app/ingestion/search_index/index_snapshot.py',
      'app/ingestion/search_index/configure_condition_index.py','app/ingestion/search_index/export_classified_snapshot.py',
      'infra/elasticsearch/config/jobs.local.json','infra/elasticsearch/config/conditions.mapping.json']
    files+= [ROOT/name for name in names]
    manifest={str(p.relative_to(ROOT).as_posix()):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
    archive=folder/'condition-review.zip'
    with ZipFile(archive,'w',ZIP_DEFLATED) as z:
        for p in sorted(files):z.write(p,p.relative_to(ROOT).as_posix())
        z.writestr('manifest.json',json.dumps(manifest,indent=2))
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    result={'status':'built_not_deployed','files':len(files),'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
            'folder':str(folder),'aws_operations':0,'database_changes':0}
    print(json.dumps(result));return result
if __name__=='__main__':build()
