# 채용·교육 매칭 서비스

## 2026-10-29 Elasticsearch 도입 합의와 구현 상태

이 절은 아래 과거 초안의 검색엔진 관련 설명보다 우선한다. **로컬 Nori·동의어 실행과 실제 스냅샷 783건 색인·검색 어댑터 검증을 완료했으며 운영 Elasticsearch는 미도입이다.** 직접 설치 방식으로 진행하며 OpenSearch·Elastic Cloud로 자동 대체하지 않는다. 로컬 Docker에서 분석기·색인·백엔드·동기화를 검증한 뒤 AWS에 배포한다. S3는 원본·백업 저장소이며 검색엔진 설치 위치가 아니다.

검색 조회는 `app/backend`, 색인 동기화는 `app/ingestion/search_index`, 실행 환경은 `infra/elasticsearch`에서 관리한다. 아래 경로 중 Elasticsearch 전용 파일은 앞으로 만들 계획이며 이번에는 문서만 수정한다. [단계별 도입 계획](ELASTICSEARCH_ROLLOUT.md)을 공통 실행 기준으로 사용한다.

## 2026-10-28 최신 상태와 고용24 전환 계획

이 절의 실행 현황과 전환 방향을 아래의 과거 초안보다 우선한다. 현재 AWS 웹·대화 서버·EC2 MySQL 연결을 검증했으며 RDS와 Elasticsearch는 사용하지 않는다. 점핏 추가 표본 10건은 백업 후 운영 반영해 총 793건이며, 기존 783건의 버전·해시는 유지했다. 신규 10건의 모집 상태는 unknown이다. **고용24 승인 후 소량 표본 검증을 거쳐 AWS 정기 배치 자동화로 전환**한다. 상세 단계와 통과 기준은 [고용24 파이프라인 계획](../app/ingestion/GOYONG24_PIPELINE.md)을 따른다.

### 다음 데이터 소스

고용24 채용 API 승인 → 소량 실제 응답 검증 → 공통 어댑터 → 격리 DB 시험 → AWS 수동 연계 → 정기 배치 자동화 순으로 진행한다. 기존 테이블/서비스를 기반으로 확장하되 점핏 전용 검색·적재·식별 코드는 분리한다. 교육 API와 Elasticsearch는 독립적인 후속 단계다. 이 폴더의 8개 기준 문서와 별도 수집 프롬프트를 구분해 관리한다.

수정일: 2026-10-28. 이 문서들은 설계 기준이며 구현 완료 보고서가 아니다.

사용자의 초기 답변으로 채용 공고를 검색하고, 자격요건과 우대사항을 순서대로 확인한 뒤 부족 역량에 맞는 교육을 연결한다.

## 현재 확보한 것

- 점핏 21개 카테고리의 공고 783건을 수집·병합한 기록이 있다. 현재 모집 중인 건수와는 다르다.
- 로컬 PostgreSQL·FastAPI·Docker와 인증 검색을 검증했다. 현재 실행 여부는 별도 점검해야 한다.
- 일부 상세 원본에 주요업무·자격요건·우대사항이 있다. 전체 상세 섹션의 완전성은 아직 확인하지 않았다.
- 로컬 MySQL 기반 대화·질문 호출 어댑터·근거 저장을 구현하고 모의 모델로 검증했다. React 로컬 화면을 구현했고 실제 질문 모델도 사용자 실행으로 확인했다. AWS DB 이전·배포, 교육 수집·매칭, Elasticsearch는 남아 있다.

## 목표 흐름

초기 답변 → 검색 조건 생성 → 서버 검색 → 필요 시 공고 선택 → 자격요건 확인 → 충족 시 우대사항 확인 → 부족 역량과 교육 매칭.

모델은 Amazon Bedrock을 활용하며 실제 데이터 조회와 검증은 Lambda가 담당한다. 화면은 React를 S3·CloudFront로 제공한다. 초기에는 DB를 조회하고, 이후 Elasticsearch 검색 계층을 추가한다. Elasticsearch와 Amazon OpenSearch를 혼용하지 않는다.

## 폴더

- `docs/`: 현재 설계 문서 8개. 이 README도 이 폴더에 있다.
- `../workspace/api추출테스트/`: 수집 코드·원본·병합 데이터·기존 비밀 설정.
- `../workspace/local_job_api/`: 현재 Docker API·DB 적재 코드와 데이터.
- `../workspace/교안/`, `../workspace/kosa-bedrock-lab/`: 교육 자료와 실습 환경.
- `../workspace/outputs/`: 기존 산출물.
- `../archive/docs_before_20261028/`: 변경 전 문서 8개.
- `../DECISIONS.md`: 추가 협의 항목.

기존 경로와 workspace 연결 경로를 함께 유지한다. 실제 위치와 연결 방향은 아래 정리 결과를 따른다. 새 작업은 career_matching 아래에서 진행한다. 비밀값과 가상환경을 저장소에 무분별하게 추가하지 않는다.

## 문서

[PRD](PRD.md), [구조](ARCHITECTURE.md), [AWS](AWS_INFRA.md), [데이터](DATA_MODEL.md), [API](API_SPEC.md), [운영](OPERATIONS.md), [검증](QA_CHECKLIST.md).

## 참고

- https://docs.aws.amazon.com/bedrock/latest/userguide/tool-use.html
- https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html
- https://boottent.com/camps?industries=001

## 실제 정리 결과

교안·api추출테스트·outputs는 workspace 아래로 이동했고 기존 위치에 호환 junction을 남겼다. 실행 중인 파일 잠금 때문에 kosa-bedrock-lab과 local_job_api는 기존 실제 위치를 유지하며 workspace 안에 해당 위치를 가리키는 junction을 만들었다. 실습의 부분 이동분은 원래 위치로 복원했으며 archive/lab_move_recovery_snapshot에 복구용 중복 스냅샷을 보존했다. 서버 중단·가상환경 재생성·중복 삭제는 수행하지 않았다.


## 대화·근거·캐시 저장 보완 (2026-10-28)

대화·근거·실행 기록과 응답 캐시는 운영 DB에 저장하는 방향으로 정했다. 빈 MySQL 스키마 9개 테이블과 저장 계약은 ../workspace/database/mysql/에 있다. Bedrock 자체 프롬프트 캐시와 서비스 응답 캐시는 구분한다. 실제 저장 로직은 미구현이다.

## 현재 작업의 시작 위치

1. 설계: 이 docs 폴더의 8개 문서.
2. DB: ../workspace/database/mysql/schema.sql 및 CONVERSATION_STORAGE.md.
3. 점핏 수집: ../workspace/api추출테스트/collect_jumpit.py와 병합 스크립트, data/jumpit 원본 및 data/jumpit_merged 결과.
4. 미결정 사항: ../DECISIONS.md.

비활성 고용24 샘플·중복 초안·이전 작업용 스크립트는 ../retired/로 분리했다. 이는 삭제가 아니며 이동 내역은 retired/move_manifest.json에 있다. 현재 API·실습·비밀 설정과 경로 호환은 유지한다.

## 서비스 코드 시작 (2026-10-28)

실제 개발 경로는 ../app/backend, ../app/ingestion, ../app/frontend, ../infra로 분리했다. backend에는 로컬 이벤트 실행·검색 조건 검증·JSON 검색·Bedrock 검색 계획 어댑터·개인화 캐시 키가 있다. ingestion은 보유 상세를 정제하며 추가 수집은 하지 않는다. frontend와 infra는 위치와 작업 기준만 준비했다.

백엔드 오프라인 테스트 9개를 통과했다. 실제 Bedrock 호출·DB 저장·React 화면·AWS 배포는 아직 검증/구현하지 않았다. 운영 Lambda의 /chat은 영구 저장·인증 연결 전 503을 반환한다. 실행 안내는 ../app/backend/README.md를 따른다.




## DB 디버깅 참고
[DBeaver 사용법·9개 테이블 전체 컬럼 설명](DBEAVER_DEBUG_GUIDE.md), [조회용 SQL](../app/backend/debug_queries.sql). 실제 대화 내용은 Git에 포함하지 않는다.


## 교육·학습 루트 데이터 준비 (2026-10-28)
최종 교육 출처는 고용24 국민내일배움카드 훈련과정·일정 API다. 부트텐트는 허락이 없어 실제 스크래핑을 보류하고 직접 작성 가상 표본으로 공통 구조를 준비했다. [교육 데이터 계약·진행 순서](../app/ingestion/TRAINING_DATA_CONTRACT.md)를 따른다. 교육 과정 실수집·운영 적재·매칭 완료를 뜻하지 않는다.
