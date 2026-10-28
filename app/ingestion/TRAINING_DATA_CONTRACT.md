# 교육 데이터 공통 구조와 고용24 훈련 API 전환

수정일: 2026-10-28. 최신 목표는 **국민내일배움카드 훈련과정·훈련일정 → 부족 역량에 맞는 교육 및 학습 루트 추천**이다. 고용24 채용 자동화와 구분한다.

## 현재 결정과 수집 범위

부트텐트 소프트웨어·AI 분야를 임시 출처로 검토했지만, 확인 당시 사이트 하단에 무단 복제·가공·크롤링·스크래핑 금지 안내가 있고 사용자는 별도 허락을 받지 않았다고 답했다. 따라서 실제 과정 상세 수집·복제·운영 적재는 실행하지 않았다. 대신 공통 정제 코드와 출처=fixture인 직접 작성 가상 데이터 3건으로 구조를 검증한다. 실제 기관·모집 과정이 아니며 사용자 추천이나 운영 DB에 넣지 않는다.

- 부트텐트 확인 페이지: https://boottent.com/camps?industries=001
- 고용24 공식 명세: https://www.work24.go.kr/cm/e/a/0110/selectOpenApiSvcInfo.do?apiSvcId=&upprApiSvcId=&fullApiSvcId=000000000000000000000000000004
- 프로젝트 규칙: ../../AGENTS.md의 ‘외부 수집은 출처 이용 범위 확인 후 실행’.

허락된 부트텐트 제공 데이터, 사용자가 권리를 확보해 제공한 파일, 이용 가능한 교육기관 공식 데이터가 생기면 별도 어댑터로 넣을 수 있다. 공개 조회 가능성이 수집 허락을 자동 의미하지는 않는다.

## 공통 필드와 DB 매핑

기존 training_offerings를 기반으로 한다. schema.sql이나 AWS DB는 이번 작업에서 수정하지 않는다.

| 그룹 | 공통 필드 | 주의점 |
|---|---|---|
| 식별 | source, source_id, course_key, cohort_name, source_url | 과정과 모집 기수를 구분. 다른 출처끼리 이름이 같다는 이유로 합치지 않음 |
| 기본 | title, provider_name, original_categories, normalized_domains | 원문 분류와 소프트웨어/AI 등 내부 분류를 구분 |
| 학습 | curriculum, learning_topics, tech_stacks | 원문 커리큘럼과 확인된 기술을 보존. 과정 제목만으로 기술을 만들어내지 않음 |
| 지원 | eligibility, preferred_conditions, selection_process, application_notes | 선수조건·지원 자격과 우대조건 구분 |
| 일정 | application_start, application_deadline, starts_at, ends_at | 모집 접수 일정과 교육 기간은 별개. 개강일이 미래라고 모집 중으로 판단하지 않음 |
| 장소 | delivery_mode, addresses | 온라인/오프라인/혼합, 실제 지역 |
| 비용 | tuition, currency, cost_description, subsidy_description | 미제공 비용은 NULL. 총 훈련비·지원금·개인 부담액을 혼동하지 않음 |
| 추적 | recruitment_status, fetched_at, raw_detail, content_hash, source_version, field_status | 상태 근거·최신 확인 시점 보존 |

정제 입력의 dates는 다음 구조를 사용한다. 날짜만 있으면 기존 DATETIME 컬럼에 임의 시각을 넣지 않고 additional_sections.date_precision에 보존한다.

```json
{"dates":{"starts_at":{"raw":"2026-12-01","precision":"date_only"}}}
```

정확한 시각은 precision=timestamp와 시간대가 있는 ISO 문자열을 사용한다. cohort_name 미확인은 NULL, additional_sections.cohort_verified=false로 남기고 실제 모집 기수를 식별하는 후속 검증이 필요하다.

## 고용24 공식 명세에서 확인한 부분

목록·과정/기관정보·훈련일정 구분을 제공한다. 목록의 trprId(과정 ID)와 trprDegr(순차), trainstCstId(기관 ID)를 실제 응답에서 확인해 모집 단위 식별을 설계한다. title/titleLink, traStartDate/traEndDate, address 등 목록 필드를 공통 구조로 매핑할 예정이다. 목록만으로 상세 커리큘럼·접수 마감·개인별 자부담이 모두 제공된다고 가정하지 않는다. 상세/일정 계약은 실제 승인·응답 검증 후 확정한다.

중요: srchTraStDt/srchTraEndDt는 명세상 **훈련시작일 조회 범위**다. 이를 접수 시작/마감으로 매핑하지 않는다. 소프트웨어·AI 표본은 공식 분류·과정명 조건을 실제 결과와 대조해 선정한다. API 키는 호출 URL에서 빼고 저장·로그를 마스킹한다.

## 로컬 검증

```cmd
cd /d C:\AWS_project\career_matching\app\ingestion
python normalize_training.py --input examples\training.fixture.json --output C:\AWS_project\career_matching\workspace\training-prototype\training.normalized.json
```

출력은 새 경로여야 한다. 네트워크 요청·DB 쓰기·모델 호출은 없다. 이 코드는 공통 입력 검증기이며 부트텐트의 실제 스크래퍼나 고용24 원본 응답 어댑터가 완성된 것은 아니다.

## 다음 단계

1. 고용24 국민내일배움카드 API 승인 및 실제 목록 최대 10건 확인.
2. 상세/기관/훈련일정 조합으로 과정·기수·지원 조건·모집 상태·기간·비용·커리큘럼 확보 범위 검증.
3. 출처 어댑터 및 training_offerings+Outbox 적재 구현·격리 DB 시험.
4. 필수 미충족 역량 → 선수지식 → 기초 → 실습 → 프로젝트 순 학습 루트와 교육 연결.
5. 교육 추천에는 원문 근거·교육에서 다루는 역량·선수조건·최신 모집/일정을 함께 제시. 직무 경력 연수와 학위 등 교육 수료로 대체되지 않는 조건을 구분.
6. 허락된 교육 표본으로 로컬 매칭을 검증한 뒤 AWS 배치 수집·정기 갱신으로 확장.


## 실제 교육 표본 추가 (2026-10-28)
사용자 요청으로 실제 공개 교육 5건의 선택 사실을 저장 페이지에서 구조화했습니다. `workspace/incoming/boottent/boottent_20261028_real01/REPORT.md` 참조. 최신 모집 검증·자동 수집기·DB 적재·서비스 추천은 아직 완료하지 않았습니다. 기존 fixture와 구분합니다.


## AWS 반영 및 실제 DB 검증 완료 (2026-10-28)
- training_offerings: 0 → 7건, offering_id 8~14. 선행 롤백 테스트로 번호가 1부터 시작하지 않으며 누락 데이터가 아닙니다.
- search_outbox: training 이벤트 7건 추가. 검색엔진 소비자는 아직 연결하지 않았습니다.
- 전체 DB 백업 gzip 검증 완료. 복구용 서버 경로와 체크섬은 aws-result.json에 기록했습니다. 복원 리허설까지 완료했다는 뜻은 아닙니다.
- 실제 MySQL에서 롤백·동일 트랜잭션 내 동일 배치 재실행·한글 및 날짜 정밀도 보존·이벤트 수·기존 데이터 불변 검증 통과.
- 기술 조회: React 3건, RAG 2건. 이 조회는 교육 구조 테스트이며 현재 신청 가능한 교육 추천이 아닙니다.
- 모든 7건은 모집 상태 unknown, recommendation_eligible=false입니다. 종료된 회차와 최신 모집 미검증 자료가 포함됩니다.
- 최초 시도는 잠금 조회 단계에서 중단됐습니다. 새 행은 반영되지 않았고 임시 계정은 제거됐습니다. 신규 전용 적재에서 불필요한 FOR UPDATE를 제거한 재실행은 성공했습니다.
- DB 작성용 임시 계정 제거 완료. 기존 앱 DB 계정 권한·기존 채용 데이터·운영 챗봇 코드는 변경하지 않았습니다.
- 챗봇의 역량 부족 → 교육 조회 → 추천 응답 연결은 미구현입니다. 모델 호출 테스트는 수행하지 않았습니다.

DBeaver 조회 예시: app/ingestion/training_debug_queries.sql


## 교육 DB와 Bedrock 상담 연결 완료 (2026-10-28)

AWS 백엔드 코드 릴리스 `20261028T053143Z`와 웹 교육 참고 카드 배포를 완료했습니다.

- 학습·교육 요청에서 현재 메시지의 기술명과 필수/우대 미충족 조건의 기술명을 추출합니다. 기술명 사전과 별칭을 사용하며 의미 검색은 아직 아닙니다.
- unknown과 met 답변은 부족 역량으로 분류하지 않습니다. 부족 기술이 없으면 사용자 원문에서 언급한 주제를 참고할 수 있지만 부족 역량이라고 단정하지 않습니다.
- 교육 DB는 허용된 출처와 기술 JSON 필드를 매개변수 쿼리로 검색합니다. 최대 20건을 읽어 관련성과 신청 후보 여부로 정렬하고 상위 3건만 상담 입력에 전달합니다. 모델이 SQL을 작성하지 않습니다.
- history.training_retrieval에 교육명·기관·학습 주제·짧은 커리큘럼·지원 조건·표시 자부담·일정·출처·버전을 함께 넣고 기존 Sonnet 상담 호출 1회로 답합니다. 일반 인사나 단순 대화 정리는 교육 DB를 검색하지 않습니다.
- 교육 조회 결과와 근거 기술은 응답 learning_opportunities/learning_search에 저장됩니다. 대화·응답 캐시에도 당시 결과와 출처 버전이 포함됩니다. 현재 요청 재전송 캐시는 기존 10분 정책이며 실시간 교육 변경 무효화 시스템은 미구현입니다.
- 조건 확인 완료 후 미충족 조건이 있으면 교육 참고 카드를 함께 조회합니다. 이 추가 조회 자체는 모델을 호출하지 않습니다. 학습 순서는 사용자가 후속 질문할 때 기존 상담 모델이 답합니다.
- 후속 온라인 여부·비용 질문에는 같은 교육 주제를 유지합니다. 과거 채용 조건 답변을 지우지 않습니다.
- career_runtime에는 training_offerings SELECT만 추가했습니다. 교육 데이터와 기존 채용 데이터는 이번 코드 배포에서 변경하지 않았습니다.
- 현재 교육 7건은 모두 unknown이며 recommendation_eligible=false입니다. 과거 회차/모집 미확인 학습 참고자료로만 표시하고 신청 가능한 교육으로 추천하지 않습니다. 경력·학위는 교육 수료로 대체하지 않습니다.

### 검증
- 전체 백엔드 126개 검사 중 119개 통과, 별도 MySQL 환경이 필요한 7개 생략. 실제 배포 DB 조회는 따로 수행했습니다.
- 프론트엔드 빌드 통과 및 기존 S3·CloudFront 게시 완료.
- 운영 앱 DB 계정으로 React 3건 / RAG 2건 조회 성공, 모두 학습 참고용 처리 확인.
- 합성 사용자 테스트 대화 1건의 실제 Sonnet 호출 성공: HTTP 200, conversation, 교육 카드 3건, 참고용 안내 포함. 테스트 세션도 기존 24시간 보관 정책에 따릅니다.
- 결과 기록: infra/.build/training-grant-result.json, training-verify-result.json, training-smoke-result.json.

### 직접 확인할 질문
`React를 공부하고 싶어. 저장된 교육을 참고해서 기초 → 실습 → 포트폴리오 순서로 알려줘.`
다음으로 `그중 온라인 과정은?`을 입력합니다. 현재 신청 가능한 교육이 확인된 것처럼 답하지 않는지 확인합니다.

### 남은 범위
최신 모집/지원 자격 재확인, 승인된 고용24 교육 API 연동, 기술 동의어 확대·검색 품질 평가, 검색엔진, 학습 추천의 정밀한 분야·수준·시간·비용 필터는 후속 작업입니다.
