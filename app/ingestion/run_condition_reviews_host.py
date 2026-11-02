"""Use a protected host-only writer config. Live calls are off until explicitly authorized."""
import json,os,sys
from pathlib import Path

def main():
    base=Path('/opt/career');settings=json.loads((base/'condition-review-db.json').read_text())
    live='--live' in sys.argv[1:]
    if live and settings.get('live_calls_allowed') is not True:raise ValueError('Host live calls are not enabled')
    config=json.loads((base/'config.json').read_text())
    os.environ.update(INGEST_MYSQL_HOST='127.0.0.1',INGEST_MYSQL_PORT=str(settings['port']),
      INGEST_MYSQL_DATABASE=settings['database'],INGEST_MYSQL_USER=settings['user'],INGEST_MYSQL_PASSWORD=settings['password'],
      AWS_REGION=config['AWS_REGION'],AWS_DEFAULT_REGION=config['AWS_REGION'],BEDROCK_REGION=config['AWS_REGION'],
      BEDROCK_MODEL_ID=config.get('BEDROCK_MODEL_ID') or config.get('MODEL_ID') or 'global.anthropic.claude-sonnet-4-6',
      ENABLE_LIVE_BEDROCK='true' if live else 'false')
    os.environ.pop('AWS_PROFILE',None)
    from classify_job_conditions import main as classify_main
    return classify_main()
if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({'status':'failed','error_type':type(exc).__name__}));raise SystemExit(1)
