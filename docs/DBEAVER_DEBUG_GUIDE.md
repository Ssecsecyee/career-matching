# DBeaver로 채용 챗봇 DB 디버깅하기

작성일: 2026-10-28. 기준은 app/backend/database/schema.sql과 실제 저장 코드다. 예약 필드와 실제 채워지는 필드를 구분한다. 실제 사용자 대화 내용·비밀번호는 이 문서에 포함하지 않았다.

## 시작하기

1. SSM 터널 CMD를 유지하고 DBeaver에서 career_matching / 127.0.0.1:13308 연결을 연다.
2. 연결 아래 Databases → career_matching → Tables를 펼친다. 예전 jobs / 5433 PostgreSQL 연결과 구분한다.
3. 테이블 우클릭 → 데이터 보기 → 모든 행으로 표를 볼 수 있다. 긴 JSON은 셀을 선택한 뒤 값(Value) 패널에서 읽는다.
4. 연결 우클릭 → SQL 편집기 → 새 SQL 스크립트를 연다. 연결과 활성 DB가 career_matching인지 확인한다.
5. SQL은 CMD가 아니라 SQL 편집기에 붙여넣고 Ctrl+Enter로 현재 문장을 실행한다. 여러 문장을 순서대로 실행하려면 해당 블록을 선택하고 Alt+X를 사용한다.
6. [디버깅 SQL](../app/backend/debug_queries.sql)을 열어 위에서부터 조회한다. 첫 번째 조회로 세션을 고른 다음 SET 문장에 그 세션 ID를 넣는다. SET은 현재 연결의 조회 변수만 설정하며 DB 행을 변경하지 않는다.

DBeaver 공식 도움말: [SQL 실행](https://dbeaver.com/docs/dbeaver/SQL-Execution/), [값 패널](https://dbeaver.com/docs/dbeaver/Panels/).

## 대화 한 개를 따라가는 순서

`chat_sessions.session_id → chat_messages.session_id → recommendation_evidence.message_id`

`chat_messages.idempotency_key ↔ model_invocations.request_id` (같은 session_id도 함께 비교)

`recommendation_evidence.subject_id → job_postings.job_id` (subject_type=job일 때)

| 보고 싶은 것 | 테이블/핵심 컬럼 |
|---|---|
| 어떤 대화인지 | chat_sessions: session_id, updated_at, stage |
| 내가 입력한 내용·화면 응답 | chat_messages: role, sequence_no, structured_content |
| 기억한 사용자 경험 | chat_sessions: profile_snapshot.memory.user_statements 및 facts |
| 전체 필수·우대 답변 | chat_sessions: requirement_answers.checks |
| 당시 원문과 답변 근거 | recommendation_evidence: evidence_quote, user_fact_snapshot, assessment_status |
| 모델 장애·호출 한도·토큰 | model_invocations: purpose, status, error_code, input_tokens, output_tokens |
| 재전송된 응답 | response_cache: payload, expires_at |

## 먼저 알아둘 한계

- 현재 상태 JSON은 가장 최근 상태다. 과거 특정 호출 때의 전체 모델 입력을 그대로 저장하지는 않는다. input_fingerprint는 해시이므로 원문으로 복원할 수 없다.
- 사용자 요청/서비스 응답과 근거는 보관하지만 모델의 숨겨진 사고과정은 보관하지 않는다.
- 앱 기록 시각은 UTC 기준이다. 한국 시각은 조회에서 9시간 더해 표시한다. DBeaver 표시 시간대와 중복 변환하지 않는다.
- 현재 세션 기본 보관은 24시간, 응답 캐시는 최대 10분이다. expires_at이 지나면 앱에서 만료로 취급하지만 정리 작업 전에는 DB 행이 남을 수 있다.
- 새로 추가한 로컬 코드는 AWS에 배포하기 전에는 운영 DB에 해당 기억 필드가 없을 수 있다. 프롬프트 버전과 실제 배포 시점을 함께 확인한다.
- 현재 career_runtime 계정은 대화 관련 테이블과 공고를 조회할 수 있지만 교육·조건·Outbox 등 일부 테이블은 권한이 없을 수 있다. 1142는 권한 오류이며 테이블이 없다는 뜻이 아니다. 조회 권한 문제 해결을 위해 앱 계정에 관리자 권한을 주지 않는다.
- 아래 SQL은 조회용이다. DBeaver 그리드 편집·삭제·저장은 피하고, 내보내는 대화는 개인정보를 포함할 수 있으므로 Git/공개 채팅에 올리지 않는다.

## `job_postings` — 공고 원문·상세의 기준 저장소

현재 공고 조회·선택에 사용. 모집 상태는 스냅샷 기준이다.

| 컬럼 | 타입 | 의미와 현재 해석 |
|---|---|---|
| `job_id` | `BIGINT` | DB 내부 공고 번호. 점핏 공고 ID(source_id)와 다르다. |
| `source` | `VARCHAR(40)` | 데이터 출처. 현재 점핏은 jumpit, 향후 고용24는 별도 출처 값으로 구분한다. |
| `source_id` | `VARCHAR(128)` | 출처 사이트의 공고/과정 ID. 단독으로 전 출처 공통 식별자가 되는 것은 아니다. |
| `source_url` | `TEXT` | 원문 상세 페이지 주소. |
| `title` | `TEXT` | 공고 또는 교육과정 제목. |
| `company_name` | `VARCHAR(255)` | 회사명. |
| `company_url` | `TEXT` | 회사 소개 또는 회사 페이지 URL. |
| `service_info` | `LONGTEXT` | 기업/서비스 소개 원문. |
| `responsibilities` | `LONGTEXT` | 주요업무 원문. |
| `qualifications` | `LONGTEXT` | 필수 지원 자격 원문. |
| `preferred_requirements` | `LONGTEXT` | 우대사항 원문. |
| `benefits` | `LONGTEXT` | 복지·혜택 원문. |
| `hiring_process` | `LONGTEXT` | 채용절차 원문. |
| `application_notes` | `LONGTEXT` | 지원 유의사항 원문. 통합 섹션은 출처 표시와 함께 동일 원문을 공유할 수 있다. |
| `tech_stacks` | `JSON` | 기술스택 JSON 배열. 기술 태그가 곧 필수 자격요건이라는 뜻은 아니다. |
| `original_categories` | `JSON` | 출처의 원래 카테고리 JSON. |
| `role_categories` | `JSON` | 서비스에서 정규화한 직무 분류 JSON. 미매핑이면 NULL. |
| `addresses` | `JSON` | 주소 JSON 배열. |
| `location_text` | `TEXT` | 원문 지역 표현. |
| `education_text` | `TEXT` | 학력 원문. |
| `education_source` | `JSON` | 학력 관련 원본 코드/값 JSON. |
| `career_source` | `JSON` | 신입 여부·최소/최대 경력 등 출처 원본 값 JSON. |
| `min_career_years` | `DECIMAL(5,2)` | 정규화한 최소 경력 연수. 현재 미매핑 데이터는 NULL일 수 있다. |
| `max_career_years` | `DECIMAL(5,2)` | 정규화한 최대 경력 연수. |
| `newcomer` | `BOOLEAN` | 정규화한 신입 허용 여부. 미확인은 NULL. |
| `employment_type` | `VARCHAR(80)` | 고용 형태. |
| `work_mode` | `VARCHAR(80)` | 근무 방식. 예: 대면/원격. 미확인 시 NULL. |
| `published_at` | `DATETIME(6)` | 원문 게시 시각. 수집 시각과 다르다. |
| `deadline_at` | `DATETIME(6)` | 정확한 마감 시각을 저장하는 필드. 날짜만 확인한 보완본은 NULL을 유지한다. |
| `deadline_type` | `VARCHAR(40)` | 마감 유형. 현재 always_open/fixed_date/unknown 등이 사용된다. |
| `recruitment_status` | `VARCHAR(40)` | 저장된 모집 상태: active/closed/unknown/unavailable. unknown은 현재 모집 중 확인을 뜻하지 않는다. |
| `field_status` | `JSON` | 필드별 확보·누락·파싱 상태 JSON. present_combined_source는 통합 원문 공유 표시다. |
| `additional_sections` | `JSON` | 추가 섹션/정밀도 메타데이터 JSON. 새 매핑은 날짜만 있는 마감 정보와 원문 섹션을 보존한다. |
| `raw_detail` | `JSON` | 출처 응답 또는 페이지 추출 원본 JSON. |
| `raw_object_key` | `TEXT` | 원본 S3 객체 키. 업로드 연계 전에는 NULL일 수 있다. |
| `content_hash` | `CHAR(64)` | 내용 변경 판별용 SHA-256. 새 증분 로직은 의미 있는 내용과 상태 기준으로 계산한다. |
| `source_version` | `BIGINT` | 저장된 원문 데이터의 버전. 과거 대화 근거와 최신 공고를 비교할 때 사용한다. |
| `source_updated_at` | `DATETIME(6)` | 출처에서 제공한 수정 시각. 없으면 NULL. |
| `fetched_at` | `DATETIME(6)` | 상세를 수집한 시각. |
| `last_seen_at` | `DATETIME(6)` | 마지막으로 확인한 시각. |
| `created_at` | `DATETIME(6)` | 레코드 최초 생성 시각. |
| `updated_at` | `DATETIME(6)` | 레코드 최근 갱신 시각. |

## `job_requirements` — 공고 조건을 독립된 행으로 보관하기 위한 테이블

현재 체크리스트는 세션 JSON에서 처리하므로 비어 있어도 정상이다.

| 컬럼 | 타입 | 의미와 현재 해석 |
|---|---|---|
| `requirement_id` | `BIGINT` | 개별 조건 ID. 현재 상담 근거에서는 NULL일 수 있다. |
| `job_id` | `BIGINT` | DB 내부 공고 번호. 점핏 공고 ID(source_id)와 다르다. |
| `requirement_type` | `VARCHAR(24)` | required(필수)/preferred(우대)/unspecified(미분류). |
| `condition_type` | `VARCHAR(40)` | 조건 분류: skill/education/experience/certificate/other 등. |
| `original_text` | `LONGTEXT` | 분해 전 또는 조건 단위 원문. |
| `normalized_condition` | `JSON` | 정규화한 조건 JSON. |
| `logic_expression` | `JSON` | AND/OR 등 조건 관계 JSON. |
| `evidence_section` | `VARCHAR(128)` | 근거가 나온 원문 섹션. |
| `evidence_quote` | `LONGTEXT` | 판단 근거로 보존한 원문 인용. |
| `source_version` | `BIGINT` | 저장된 원문 데이터의 버전. 과거 대화 근거와 최신 공고를 비교할 때 사용한다. |
| `sort_order` | `INT` | 조건의 원문 표시 순서. |

## `training_offerings` — 교육 과정·모집 기수 저장소

교육 데이터 연결 전이므로 비어 있을 수 있다.

| 컬럼 | 타입 | 의미와 현재 해석 |
|---|---|---|
| `offering_id` | `BIGINT` | 교육 모집 건의 DB 내부 ID. |
| `source` | `VARCHAR(40)` | 데이터 출처. 현재 점핏은 jumpit, 향후 고용24는 별도 출처 값으로 구분한다. |
| `source_id` | `VARCHAR(128)` | 출처 사이트의 공고/과정 ID. 단독으로 전 출처 공통 식별자가 되는 것은 아니다. |
| `source_url` | `TEXT` | 원문 상세 페이지 주소. |
| `course_key` | `VARCHAR(128)` | 교육 과정 식별자. |
| `cohort_name` | `VARCHAR(255)` | 모집 기수명. |
| `title` | `TEXT` | 공고 또는 교육과정 제목. |
| `provider_name` | `VARCHAR(255)` | 교육 제공 기관. |
| `original_categories` | `JSON` | 출처의 원래 카테고리 JSON. |
| `normalized_domains` | `JSON` | 정규화한 교육 분야 JSON. |
| `curriculum` | `LONGTEXT` | 커리큘럼 원문. |
| `learning_topics` | `JSON` | 학습 주제 JSON. |
| `tech_stacks` | `JSON` | 기술스택 JSON 배열. 기술 태그가 곧 필수 자격요건이라는 뜻은 아니다. |
| `eligibility` | `LONGTEXT` | 교육 지원 자격 원문. |
| `preferred_conditions` | `LONGTEXT` | 교육 우대조건 원문. |
| `benefits` | `LONGTEXT` | 복지·혜택 원문. |
| `selection_process` | `LONGTEXT` | 교육 선발 절차 원문. |
| `application_notes` | `LONGTEXT` | 지원 유의사항 원문. 통합 섹션은 출처 표시와 함께 동일 원문을 공유할 수 있다. |
| `application_start` | `DATETIME(6)` | 지원 접수 시작. |
| `application_deadline` | `DATETIME(6)` | 지원 접수 마감. |
| `starts_at` | `DATETIME(6)` | 교육 시작 시각. |
| `ends_at` | `DATETIME(6)` | 교육 종료 시각. |
| `delivery_mode` | `VARCHAR(40)` | 온라인/오프라인 등 교육 방식. |
| `addresses` | `JSON` | 주소 JSON 배열. |
| `tuition` | `DECIMAL(14,2)` | 수강료. |
| `currency` | `CHAR(3)` | 통화 코드. |
| `cost_description` | `LONGTEXT` | 비용 설명 원문. |
| `subsidy_description` | `LONGTEXT` | 지원금·국비 등 설명. |
| `recruitment_status` | `VARCHAR(40)` | 저장된 모집 상태: active/closed/unknown/unavailable. unknown은 현재 모집 중 확인을 뜻하지 않는다. |
| `field_status` | `JSON` | 필드별 확보·누락·파싱 상태 JSON. present_combined_source는 통합 원문 공유 표시다. |
| `additional_sections` | `JSON` | 추가 섹션/정밀도 메타데이터 JSON. 새 매핑은 날짜만 있는 마감 정보와 원문 섹션을 보존한다. |
| `raw_detail` | `JSON` | 출처 응답 또는 페이지 추출 원본 JSON. |
| `raw_object_key` | `TEXT` | 원본 S3 객체 키. 업로드 연계 전에는 NULL일 수 있다. |
| `content_hash` | `CHAR(64)` | 내용 변경 판별용 SHA-256. 새 증분 로직은 의미 있는 내용과 상태 기준으로 계산한다. |
| `source_version` | `BIGINT` | 저장된 원문 데이터의 버전. 과거 대화 근거와 최신 공고를 비교할 때 사용한다. |
| `fetched_at` | `DATETIME(6)` | 상세를 수집한 시각. |
| `last_seen_at` | `DATETIME(6)` | 마지막으로 확인한 시각. |
| `updated_at` | `DATETIME(6)` | 레코드 최근 갱신 시각. |

## `search_outbox` — DB 변경을 검색엔진에 전달할 작업 목록

새 증분 적재에서 기록하도록 구현. 운영 적재·검색 소비자 연결 전에는 비어 있거나 미처리일 수 있다.

| 컬럼 | 타입 | 의미와 현재 해석 |
|---|---|---|
| `event_id` | `BIGINT` | 검색 변경 이벤트 번호. |
| `entity_type` | `VARCHAR(24)` | 대상 유형. 예: job/program. |
| `entity_id` | `BIGINT` | 대상 DB 내부 ID. |
| `source_version` | `BIGINT` | 저장된 원문 데이터의 버전. 과거 대화 근거와 최신 공고를 비교할 때 사용한다. |
| `operation` | `VARCHAR(24)` | 색인 작업 종류: upsert/close/delete. |
| `created_at` | `DATETIME(6)` | 레코드 최초 생성 시각. |
| `processed_at` | `DATETIME(6)` | 색인 소비자 처리 완료 시각. NULL이면 미완료 또는 소비자 미연결. |
| `attempt_count` | `INT` | 처리 시도 횟수. |
| `last_error` | `TEXT` | 최근 처리 오류. 민감정보를 기록하지 않아야 한다. |

## `chat_sessions` — 대화 한 개의 현재 상태·기억·사용량

새 대화부터 만료까지의 기준 레코드. 디버깅을 시작하는 곳이다.

| 컬럼 | 타입 | 의미와 현재 해석 |
|---|---|---|
| `session_id` | `CHAR(36)` | 대화 세션 UUID. 테이블을 이어 조회하는 핵심 키. |
| `owner_scope` | `VARCHAR(128)` | 클라이언트 토큰과 접속 코드로 만든 소유 범위 해시. 실제 이름·이메일이 아니다. |
| `stage` | `VARCHAR(40)` | 현재 처리 단계. conversation/choose_job/no_results/checking_required/checking_preferred/completed/gap_guidance 등. 저장된 워크플로 단계와 일반 대화 응답의 표시 단계는 다를 수 있다. |
| `selected_job_ids` | `JSON` | 선택한 출처 공고 ID JSON 배열. 현재 source_id 중심이며 다중 출처 확장은 후속 사항. |
| `profile_snapshot` | `JSON` | 현재 사용자 프로필·기억 JSON. 사용자 원문 기억·추출 사실 등을 포함한다. |
| `profile_version` | `BIGINT` | 프로필 버전용 필드. 현재 기본값 1 중심이며 자동 증가 기능을 구현했다고 해석하면 안 된다. |
| `requirement_answers` | `JSON` | 이름과 달리 현재 전체 대화 상태 JSON. selected/checks/conditions/profile 등과 처리 중 _lease가 들어간다. |
| `state_version` | `BIGINT` | 요청 성공 시 증가하는 대화 상태 버전. 동시에 처리된 요청 충돌을 검증한다. |
| `cumulative_input_tokens` | `BIGINT` | 이 세션 호출에서 기록된 입력 토큰 누계. |
| `cumulative_output_tokens` | `BIGINT` | 이 세션 호출에서 기록된 출력 토큰 누계. |
| `model_call_count` | `INT` | 애플리케이션 모델 호출 시도 수. 실패도 포함하며 현재 세션 한도 검사에 사용된다. |
| `expires_at` | `DATETIME(6)` | 논리적 만료 시각. 시간이 지나도 정리 작업 전에는 행이 남아 있을 수 있다. |
| `created_at` | `DATETIME(6)` | 레코드 최초 생성 시각. |
| `updated_at` | `DATETIME(6)` | 레코드 최근 갱신 시각. |

## `chat_messages` — 사용자 요청과 서비스 응답의 시간순 기록

성공적으로 마친 요청은 보통 user/assistant 두 행. 처리 실패한 요청은 메시지 없이 호출 실패 기록만 남을 수 있다.

| 컬럼 | 타입 | 의미와 현재 해석 |
|---|---|---|
| `message_id` | `BIGINT` | 대화 메시지 DB 번호. |
| `session_id` | `CHAR(36)` | 대화 세션 UUID. 테이블을 이어 조회하는 핵심 키. |
| `sequence_no` | `BIGINT` | 한 세션 내 메시지 순서. |
| `idempotency_key` | `VARCHAR(128)` | 중복 요청 방지 키. 현재 사용자/응답 메시지의 request_id에 해당한다. |
| `role` | `VARCHAR(24)` | user(사용자 요청)/assistant(서비스 응답). assistant가 항상 모델 직접 생성 문장이라는 뜻은 아니다. |
| `content` | `LONGTEXT` | 요청/응답 전체를 JSON 문자열로 직렬화한 LONGTEXT. 자연어 문장만 들어 있는 필드가 아니다. |
| `structured_content` | `JSON` | 동일 요청/응답을 JSON으로 저장한 필드. message/action/answers/checks 등 경로로 확인한다. |
| `stage` | `VARCHAR(40)` | 현재 처리 단계. conversation/choose_job/no_results/checking_required/checking_preferred/completed/gap_guidance 등. 저장된 워크플로 단계와 일반 대화 응답의 표시 단계는 다를 수 있다. |
| `source_version_snapshot` | `JSON` | 원문 버전 스냅샷을 위한 예약 필드. 현재 메시지·호출 저장 코드에서는 직접 채우지 않아 NULL일 수 있다. |
| `expires_at` | `DATETIME(6)` | 논리적 만료 시각. 시간이 지나도 정리 작업 전에는 행이 남아 있을 수 있다. |
| `created_at` | `DATETIME(6)` | 레코드 최초 생성 시각. |

## `model_invocations` — 모델 호출 목적·성공/실패·토큰·지연 기록

모든 메시지가 모델 호출은 아니다. 실패에도 토큰이 기록될 수 있고 실제 청구는 Billing에서 확인한다.

| 컬럼 | 타입 | 의미와 현재 해석 |
|---|---|---|
| `invocation_id` | `CHAR(36)` | 모델 호출 기록 UUID. |
| `session_id` | `CHAR(36)` | 대화 세션 UUID. 테이블을 이어 조회하는 핵심 키. |
| `request_id` | `VARCHAR(128)` | API 요청 UUID. 메시지 idempotency_key와 연결된다. |
| `attempt_no` | `INT` | 호출 시도 순번용 필드. 현재 기본값 1이며 SDK 내부 재시도 하나하나가 별도 행인 것은 아니다. |
| `purpose` | `VARCHAR(40)` | 모델 호출 목적. conversation/search_plan/question_required/question_preferred 등. 배치 체크리스트 표시는 모델을 호출하지 않는다. |
| `provider` | `VARCHAR(40)` | 모델 제공 서비스. 현재 bedrock. |
| `model_id` | `VARCHAR(255)` | 실제 호출 모델/추론 프로필 ID. |
| `region` | `VARCHAR(40)` | 모델 호출 리전. |
| `prompt_version` | `VARCHAR(80)` | 호출에 사용한 프롬프트 버전. |
| `policy_version` | `VARCHAR(80)` | 저장·캐시·호출 정책 버전. |
| `input_fingerprint` | `CHAR(64)` | 실제 모델 입력 인자의 해시. 입력 원문 전체를 저장한 필드가 아니다. |
| `source_version_snapshot` | `JSON` | 원문 버전 스냅샷을 위한 예약 필드. 현재 메시지·호출 저장 코드에서는 직접 채우지 않아 NULL일 수 있다. |
| `status` | `VARCHAR(40)` | 호출 처리 상태. 현재 코드에서 pending/succeeded/failed를 기록한다. timed_out은 스키마 표현이며 실제 타임아웃은 failed+오류 코드일 수 있다. |
| `input_tokens` | `BIGINT` | 해당 호출 입력 토큰. |
| `output_tokens` | `BIGINT` | 해당 호출 출력 토큰. |
| `cache_read_input_tokens` | `BIGINT` | Bedrock 프롬프트 캐시 읽기 토큰. DB 응답 캐시와 다르다. |
| `cache_write_input_tokens` | `BIGINT` | Bedrock 프롬프트 캐시 쓰기 토큰. |
| `latency_ms` | `BIGINT` | 기록된 모델 호출 지연(밀리초). |
| `estimated_cost` | `DECIMAL(18,8)` | 예상 비용 예약 필드. 현재 호출 저장 코드에서는 산출하지 않아 NULL일 수 있다. |
| `cost_currency` | `CHAR(3)` | 예상 비용 통화. 현재 미산출이면 NULL. |
| `pricing_version` | `VARCHAR(80)` | 비용 계산에 사용한 가격표 버전. 현재 미산출이면 NULL. |
| `provider_request_id` | `VARCHAR(255)` | AWS 응답 요청 ID. |
| `error_code` | `VARCHAR(128)` | 실패 원인 코드. succeeded여도 답변 내용이 정확하다는 보장은 없다. |
| `started_at` | `DATETIME(6)` | 호출 기록 시작 시각. |
| `finished_at` | `DATETIME(6)` | 호출 처리 완료 시각. |
| `expires_at` | `DATETIME(6)` | 논리적 만료 시각. 시간이 지나도 정리 작업 전에는 행이 남아 있을 수 있다. |

## `recommendation_evidence` — 공고 원문과 사용자의 조건 답변을 연결한 근거

체크리스트 한 요청으로 조건 여러 개를 저장하면 메시지 하나에 근거 여러 행이 연결된다.

| 컬럼 | 타입 | 의미와 현재 해석 |
|---|---|---|
| `evidence_record_id` | `BIGINT` | 답변 근거 레코드 번호. |
| `message_id` | `BIGINT` | 대화 메시지 DB 번호. |
| `subject_type` | `VARCHAR(24)` | 근거 대상: job/program. |
| `subject_id` | `BIGINT` | 대상 공고/교육의 DB 내부 ID. job이면 job_postings.job_id. |
| `source_version` | `BIGINT` | 저장된 원문 데이터의 버전. 과거 대화 근거와 최신 공고를 비교할 때 사용한다. |
| `source_url` | `TEXT` | 원문 상세 페이지 주소. |
| `requirement_id` | `BIGINT` | 개별 조건 ID. 현재 상담 근거에서는 NULL일 수 있다. |
| `requirement_type` | `VARCHAR(24)` | required(필수)/preferred(우대)/unspecified(미분류). |
| `requirement_snapshot` | `JSON` | 당시 섹션·조건 원문 JSON. |
| `source_section` | `VARCHAR(128)` | qualifications/preferred_requirements 등 원문 필드. |
| `evidence_quote` | `LONGTEXT` | 판단 근거로 보존한 원문 인용. |
| `user_fact_snapshot` | `JSON` | 해당 조건에 대한 사용자 자기 평가·설명 JSON. |
| `assessment_status` | `VARCHAR(24)` | met(충족)/unmet(미충족)/unknown(미확인) 등. 현재 사용자의 명시적 자기 평가다. |
| `explanation` | `LONGTEXT` | 사용자에게 보여주는 근거 설명. 모델의 숨겨진 사고과정이 아니다. |
| `validation_status` | `VARCHAR(24)` | 앱의 형식·출처 연결 검증 상태. validated가 실제 역량이나 합격 가능성 검증을 뜻하지 않는다. |
| `rule_version` | `VARCHAR(80)` | 근거 저장에 적용한 규칙 버전. |
| `expires_at` | `DATETIME(6)` | 논리적 만료 시각. 시간이 지나도 정리 작업 전에는 행이 남아 있을 수 있다. |
| `created_at` | `DATETIME(6)` | 레코드 최초 생성 시각. |

## `response_cache` — 동일 요청 재전송에 대한 저장 응답

현재 약 10분 응답 캐시이며 세션 만료를 넘지 않는다. 비슷한 문장에 대한 공용 답변 캐시나 Bedrock 프롬프트 캐시가 아니다.

| 컬럼 | 타입 | 의미와 현재 해석 |
|---|---|---|
| `cache_id` | `BIGINT` | 캐시 레코드 번호. |
| `scope_key` | `VARCHAR(128)` | 사용자 소유 범위 해시. |
| `cache_kind` | `VARCHAR(24)` | 캐시 유형. 현재 response를 저장한다. |
| `cache_key` | `CHAR(64)` | 세션·요청 기반 캐시 키 해시. |
| `session_id` | `CHAR(36)` | 대화 세션 UUID. 테이블을 이어 조회하는 핵심 키. |
| `session_state_version` | `BIGINT` | 응답을 저장했을 때의 대화 상태 버전. |
| `profile_version` | `BIGINT` | 프로필 버전용 필드. 현재 기본값 1 중심이며 자동 증가 기능을 구현했다고 해석하면 안 된다. |
| `stage` | `VARCHAR(40)` | 현재 처리 단계. conversation/choose_job/no_results/checking_required/checking_preferred/completed/gap_guidance 등. 저장된 워크플로 단계와 일반 대화 응답의 표시 단계는 다를 수 있다. |
| `model_id` | `VARCHAR(255)` | 실제 호출 모델/추론 프로필 ID. 현재 캐시 저장 코드에서는 직접 설정하지 않아 NULL일 수 있다. |
| `prompt_version` | `VARCHAR(80)` | 호출에 사용한 프롬프트 버전. 현재 캐시 저장 코드에서는 직접 설정하지 않아 NULL일 수 있다. |
| `policy_version` | `VARCHAR(80)` | 저장·캐시·호출 정책 버전. |
| `data_generation` | `BIGINT` | 전체 데이터 세대용 필드. 현재 기본 운영 경로에서는 1을 저장하며 자동 무효화가 완성됐다는 뜻은 아니다. |
| `dependency_versions` | `JSON` | 선택 공고 ID와 버전 등 응답 의존 정보 JSON. 검색엔진 색인 버전과 다르다. |
| `payload` | `JSON` | 요청 fingerprint와 실제 response를 담은 JSON. |
| `invalidated_at` | `DATETIME(6)` | 명시적 무효화 시각. NULL이어도 expires_at이 지났으면 유효하지 않다. |
| `expires_at` | `DATETIME(6)` | 논리적 만료 시각. 시간이 지나도 정리 작업 전에는 행이 남아 있을 수 있다. |
| `created_at` | `DATETIME(6)` | 레코드 최초 생성 시각. |
