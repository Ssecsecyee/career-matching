# 로컬 챗봇 Elasticsearch 검색 연결

2026-10-29. 로컬 설정에서만 JOB_SEARCH_BACKEND=elasticsearch를 선택했다. 운영 AWS 환경은 변경하지 않았고, 선택 설정이 없는 환경은 기존 MySQL 검색을 사용한다.

## 실행 순서 — CMD

프로젝트 Python 환경과 Docker Desktop을 준비한다. 기존 로컬 MySQL 데이터와 계정 설정을 유지한다.

```cmd
cd /d C:\AWS_project\career_matching
docker compose -f infra\elasticsearch\compose.local.yaml up -d --wait
cd app\backend
python dev.py
```

다른 CMD:

```cmd
cd /d C:\AWS_project\career_matching\app\frontend
npm run dev
```

기존 서버가 이미 실행 중이면 중복 실행하지 않는다. backend dev.py 감시 실행은 소스/.env 변경 후 재시작하며, local_server.py를 직접 실행했다면 수동 재시작한다. 기존 인증 토큰을 사용하고 새 대화로 시험한다. 실모델 호출은 기존 ENABLE_LIVE_BEDROCK 설정에 따르며 이 작업에서 활성화 값을 바꾸지 않았다.

## 확인할 시나리오

1. ‘리액트 공고가 있을까?’ → 후보 카드.
2. ‘서울에서 React와 TypeScript 사용하는 공고’ → 지역·두 기술 조건 검색.
3. 공고 선택 → MySQL의 최신 상세로 자격요건 확인.
4. 등록되지 않은 기술 → 정상 0건.
5. 로컬 Elasticsearch를 stop한 뒤 새 검색 → MySQL 검색으로 복귀. 엔진 미응답일 때 MySQL 검색으로 자동 복귀하고 로그와 응답 메타데이터로 구분한다. 다시 up하면 다음 요청부터 엔진을 재시도한다.

기존 SQL 검색으로 돌아가려면 backend .env의 JOB_SEARCH_BACKEND=mysql로 수정하거나 실행 CMD에서 다음을 지정하고 backend를 재시작한다.

```cmd
set "JOB_SEARCH_BACKEND=mysql"
python dev.py
```

다시 Elasticsearch를 선택하려면 같은 CMD에서 JOB_SEARCH_BACKEND=elasticsearch로 바꾸거나 환경 변수를 비워 .env를 적용한다.

## 현재 검증과 제한

- 실제 로컬 ES+MySQL로 React/리액트/리엑트 검색→공고 선택→자격요건 확인을 검증했다. 질문 생성만 모의 구현으로 대체했으며 Bedrock 호출과 대화 DB 쓰기는 0이다. 브라우저 자연어 의도 분류를 확인한 결과는 아니다.
- Elasticsearch 후보 46건, 로컬 MySQL에서 확인된 42건만 카드/개수에 반영했다. 검색 색인은 AWS 803건 내보내기 기준이고 로컬 DB는 별도로 유지된다. 새 AWS 공고를 로컬 DB에 자동 복제하지 않았다. 두 저장소가 다르면 확인되지 않은 후보는 제외된다.
- 후보 전체의 현재 모집 상태·마감·버전을 MySQL에서 조회하고, 결과 순서는 ES 순위를 유지한다. 삭제/누락/버전 불일치는 제외한 뒤 total을 계산한다. 공고 선택과 답변 시 상세/버전 재확인은 기존 대화 흐름을 따른다.
- 현재 API는 점핏 숫자 ID 선택 계약이므로 연결 경로는 source=jumpit으로 한정한다. 고용24 연결 전 source-aware 후보·선택·DB 조회 계약 확장이 필요하다.
- 현재 검증 한도는 한 검색당 1000후보이며 초과 시 명시적 오류다. 일부만 확인하고 전체 개수인 것처럼 반환하지 않는다. 고용24 파이프라인 단계에서 페이지 처리·필터 전략·최소 3배 부하 검증을 진행한다. 이 한도를 운영 규모 지원 보장으로 해석하지 않는다.
- 엔진 미응답·타임아웃은 MySQL로 자동 복귀한다. 부분 샤드 실패·설정 오류·정상 0건은 복귀하지 않는다. 상세는 SEARCH_FAILOVER.md 참조. HTTP 연결은 로컬 127.0.0.1:19200만 허용한다. AWS 설치 시 별도 인증·통신 설정을 구현해야 한다.

자동 Outbox 소비자와 AWS 검색엔진 배포는 다음 단계다. 부하 테스트는 사용자 합의에 따라 고용24 파이프라인 작업 시 수행한다.


## 교육 검색 연결 (2026-10-29)

TRAINING_SEARCH_BACKEND=elasticsearch를 로컬 .env에 추가했다. 교육은 career-training-local-read 별칭으로 채용과 분리해 7건 색인했다. 모집 미확인 표시는 유지하며 UI/UX 과정은 현재 결과 0건이다. 상세 튜닝 절차는 SEARCH_RELEVANCE_TUNING.md 참조. 교육 검색만 복귀하려면 TRAINING_SEARCH_BACKEND=mysql로 변경하고 backend를 재시작한다. 재색인은 프로젝트 최상단에서 python app/ingestion/search_index/index_training.py로 실행한다. 현재 입력은 로컬 MySQL이고 AWS DB를 자동 복제하지 않는다.
