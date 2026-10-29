# 로컬 Elasticsearch — 1단계

2026-10-29: Elasticsearch 9.5.5 + analysis-nori 직접 설치 이미지와 로컬 Docker 실행을 준비했다. Nori 분석, 기술명 12개 양성/음성 검색, 엔진 내부 기술 동의어, 출처별 같은 ID 분리를 합성 문서로 검증했다. 실제 고용24 API를 호출하거나 데이터 계약을 검증한 결과가 아니다.

프로젝트 최상단 CMD:

```cmd
docker compose -f infra\elasticsearch\compose.local.yaml up -d --build --wait
python infra\elasticsearch\verify_local.py
docker compose -f infra\elasticsearch\compose.local.yaml stop
```

다시 실행할 때도 첫 명령을 사용한다. `stop`은 볼륨을 보존한다. `down -v`는 색인을 지우므로 사용하지 않는다. 기존 MySQL 컨테이너와 별도 프로젝트/볼륨이다. 검색 주소는 127.0.0.1:19200, 메모리 상한 2GB, 힙 512MB다. 이 크기는 운영 권장 용량이 아니라 시작용 실험 설정이다.

인증을 끈 루프백 전용 로컬 구성이다. AWS나 외부에 그대로 공개하지 않는다. Nori 플러그인은 엔진과 같은 버전으로 설치한다. [공식 설치 안내](https://www.elastic.co/docs/reference/elasticsearch/plugins/analysis-nori)

`config/jobs.local.json`은 합성 문서 검증용 최소 매핑이다. verify_local.py는 매번 고유 임시 색인만 만들고 삭제한다. 기술 배열은 keyword tokenizer로 각 기술을 보존하고 검색 분석기의 synonym_graph에서 별칭을 연결한다. 일반 본문은 Nori로 분석하며 본문 전체 동의어 검색까지 완성한 구성은 아니다. Nori 불용 품사·사용자 사전·전체 필드·날짜 필터는 다음 단계에서 검증한다.

현재 실제 공고 색인, backend 검색 전환, Outbox 소비자, AWS 배포는 하지 않았다. 다음 단계는 최소 매핑을 실제 공통 공고 구조로 확장하고 원본 스냅샷을 색인하는 것이다. 상세 계획은 ../../docs/ELASTICSEARCH_ROLLOUT.md를 따른다.
