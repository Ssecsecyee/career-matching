# AI 조건 분류 실행·운영 준비

상태: 로컬 구현·검증 / 운영 미활성

## 먼저 구분할 것

기존 웹/API 배포와 이 기능 활성화는 별개다. 새 DB 테이블, 소비자 코드, ES 매핑, 계정 권한이 준비되기 전에는 실제 분류 결과를 운영 DB에 저장하지 않는다. 이번 작업은 이를 AWS에 실행하지 않았다. 실모델 정확도 평가는 [평가 계획](AI_QUESTION_SELECTION_EVALUATION.md)을 따른다.

## 준비 순서

1. 별도 검증 DB에서 app/backend/database/condition_review_migration.sql 적용 후 원본·분류·Outbox 권한 시험.
2. ES 별칭의 새 매핑 적용. configure_condition_index.py는 기본 계획만 출력하며 --apply를 지정해야 수정한다.
3. 새 소비자 배포와 보호된 소비자 설정의 enable_condition_reviews=true(JSON boolean) 준비.
4. 실제 모델 소량 호출은 사용자 opt-in 뒤 --live로 수행한다. 먼저 --apply 없이 결과와 이유를 확인한다.
5. 새 소비자·매핑·권한을 확인한 뒤 --apply --confirm-index-ready로 분류와 r: 이벤트를 저장한다.
6. Outbox 대기·실패, 원본/색인 버전·조건 해시, 미분류 자료 검색을 확인한다.
7. 사람 정답 평가와 비교 운영 후 질문 선정/순위 기능을 소량 활성화한다.

## 최소 권한

| 주체 | 필요한 범위 |
|---|---|
| 분류 작업자 | job_postings SELECT, job_condition_reviews SELECT/INSERT, search_outbox INSERT |
| 검색 소비자 | 기존 권한 + job_condition_reviews SELECT |
| 대화 작업자 | 기존 권한 + job_condition_reviews SELECT (질문 선정 활성 시) |
| 마이그레이션 관리자 | 새 테이블 CREATE·참조 권한, 계정 권한 부여 |

분류 작업자는 원본 UPDATE/DELETE, 대화 테이블 권한이 필요 없다. FOR SHARE와 위 권한 조합은 실제 로컬 MySQL 8.4에서 시험했다. 자격증명을 명령 인수·Git·프롬프트·출력에 넣지 않는다. 모델 설정은 backend/.env 또는 실행 환경, ingestion/.env에는 기존 INGEST_MYSQL_ 키만 사용한다.

## CMD: 계획과 소량 검토

프로젝트 최상단에서 실행한다. 아래 파일 경로는 매 실행 새 이름으로 바꾼다. DB 조회에는 해당 환경의 접속·테이블 준비가 필요하다.

```cmd
cd /d C:AWS_projectcareer_matching
python appingestionsearch_indexconfigure_condition_index.py
python appingestionclassify_job_conditions.py --limit 2 --output workspaceingestion-reportscondition_plan_01.json
```

실제 모델 검토는 비용이 발생한다. 계정·모델·리전과 ENABLE_LIVE_BEDROCK=true opt-in이 준비된 뒤 아래를 사용한다. --apply가 없으므로 분류·Outbox를 쓰지 않는다.

```cmd
python appingestionclassify_job_conditions.py --live --limit 2 --output workspaceingestion-reportscondition_review_01.json
```

결과 검토와 환경 준비 뒤 적용 예시:

```cmd
python appingestionclassify_job_conditions.py --live --apply --confirm-index-ready --limit 2 --output workspaceingestion-reportscondition_apply_01.json
```

검토와 적용 실행 사이 캐시가 없으면 실제 호출이 다시 발생한다. 검토 보고서를 신뢰된 입력으로 바로 import하는 기능은 제공하지 않는다. 저장된 동일 해시·정책은 후속 실행에서 재호출 없이 재사용한다. 실패 사용량은 보고서에, 저장 성공 사용량은 분류 테이블의 model_usage에도 남는다. 이 배치 비용은 기존 대화 model_invocations 집계와 별개이며 기존 관리자 대시보드에 자동 합산되지 않는다.

## 배치 재개·신규·수정 감지

--limit는 미분류 검토 시도 수(기본 5, 최대 20), 한 실행의 읽기 창은 최대 500행이다. 보고서 next_after_job_id를 다음 실행의 --after-job-id에 사용한다. 실패가 있으면 실패 ID를 확인하고 이전 커서 또는 0부터 재실행한다. 새 수집/수정 반영 후에는 새 순회를 0부터 시작해야 낮은 ID의 수정 공고도 다시 검사한다. 동일 해시·정책은 건너뛰므로 모델을 다시 부르지 않는다. 자동 주기 실행 스케줄은 아직 설치하지 않았다.

## 기능 설정

- 작업자 환경 ENABLE_AI_CONDITION_SELECTION=false: 기본은 기존 전체 원문 문답. true일 때 유효한 저장 분류만 적용한다.
- 작업자 환경 ENABLE_AI_CONDITION_RANKING=false: 기본 검색 유지. true일 때 분류 기술의 후보·순위 보강.
- 소비자 보호 JSON의 enable_condition_reviews: true: 새 분류 이벤트와 DB 조회를 사용한다. 환경 문자열 설정과 JSON boolean을 혼동하지 않는다.

전체 원문·참고사항은 세션에 보존한다. AI 실패·검증 실패·미분류는 기존 전체 질문으로 복귀한다. 주소/마감일 변경만으로 재분류하지 않고 조건 해시가 달라진 경우 재분류한다. 기존 답변이 있는 세션을 새 분류로 자동 재편집하지 않는다.

## 전체 재색인과 배포 묶음

export_classified_snapshot.py --output 새경로는 원본과 현재 유효 분류를 함께 읽는다. index_snapshot.py는 그 스냅샷의 분류와 논리를 새 색인에 보존한다. 운영 전체 재색인은 소비 중지·변경 경계 보존·소비 재개 절차를 유지한다.

```cmd
python infrauild_condition_review_bundle.py
```

이 명령은 코드·마이그레이션·매핑·해시 manifest만 infra/.build에 묶으며 AWS/SQL을 실행하지 않는다. 비밀 설정·원문 데이터는 포함하지 않는다. 자동 설치기는 아니다. 운영 소비자는 기존 배포 폴더의 코드를 실행하므로 백엔드 코드만 업데이트해서는 새 소비자가 반영되지 않는다. 기존 infra/connect_search.py apply는 최초 설치용이므로 이미 설치된 서버에서 다시 실행하지 않는다. AWS 단계에서 소비자 경로·설정 소유권·권한·매핑을 함께 갱신해야 한다.

## 복귀

질문 선정/순위 플래그를 false로 돌리면 기존 질문·검색으로 복귀한다. DB 분류 이력과 원문은 지우지 않는다. 이미 발행한 r: 이벤트가 있다면 새 소비자를 유지해 처리해야 한다. 구형 소비자는 해당 이벤트를 해석하지 못하므로 단순 코드 복귀로 처리 성공을 주장하면 안 된다. 아직 처리되지 않은 이벤트·실패·별칭·버전을 확인한다.

## 한계

이 구조의 실행·데이터 무결성을 검증한 것과 AI 선정 정확도를 입증한 것은 다르다. 복합 조건의 의미·성향 분류·중요 조건 오생략을 사람 정답과 실제 모델로 평가해야 한다. 4096 출력 토큰 안에 긴 조건 전체를 완결하지 못하면 실패하며 자동으로 조건을 없애지 않는다. 사용자 역량 프로필 기반 최종 재추천과 추천 이유 A3 확장은 별도 과업이다.
