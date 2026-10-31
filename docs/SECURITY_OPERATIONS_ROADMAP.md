# 보안·배포 후 운영 개선 계획과 DB 변경 목록

작성일: 2026-10-31. 상태: **후속 설계·작업 목록 작성**. 이 문서는 새 테이블 생성, 인증 전환, 알림 연결 또는 AWS 배포 완료를 뜻하지 않는다. 아래 테이블명과 컬럼은 논리 설계 제안이며 실제 DDL은 해당 단계에서 검토해 작성한다.

## 1. 현재 기준과 이번 문서의 범위

- 실제 운영: React/S3/CloudFront → API Gateway/Lambda → SQS/임시 DynamoDB 작업 상태 → EC2 Python 작업자 → MySQL·Bedrock·Elasticsearch.
- 기존 EC2(t4g.medium)에 MySQL·검색엔진·작업자를 함께 운영한다. DB·검색 포트는 서버 loopback, 외부 관리는 SSM을 사용한다.
- 관리자/일반 토큰 검증, 별도 관리자 DB 계정, 소유 범위 확인, 공고 숨김/복구 감사, 버전/Outbox 기록은 구현·배포했다. 상세 증거는 [ADMIN_DASHBOARD.md](ADMIN_DASHBOARD.md).
- 관리자 채팅은 세션별 모델 호출 횟수 제한만 해제했다. 일반 12회 제한은 세션 단위이며 사용자 전체/일자 예산을 의미하지 않는다.
- 배포 시 백업·압축 무결성 확인과 이전 코드 복구 절차가 있다. 실제 DB 복원 훈련·정기 외부 백업·알림 수신·정기 개인정보 삭제 완료는 아직 입증하지 않았다.
- 운영 설정 전체를 새로 조회한 보안 감사는 아니다. 기존 구현과 문서를 기준으로 개선 작업을 설계했다. 서비스 설정·요금·권한은 실행 시 다시 확인한다.
- 현재 공유 토큰 기반 owner_scope는 개인 신원이 아니다. 새 로그인 이후에도 과거 세션을 임의의 계정에 연결하지 않는다.

## 2. 무엇을 DB에 추가해야 하는가

모든 운영 정보를 MySQL로 모으지 않는다. DB 장애도 감지해야 하므로 알림·보안 로그의 독립 저장 경로를 유지한다.

| 보완 대상 | 새 MySQL 테이블 | 기존 변경/재사용 | DB 밖의 실제 작업 |
|---|---|---|---|
| 오류·서버/검색/큐 적체 감지 | 기본 불필요 | search_outbox·model_invocations 지표 활용 | CloudWatch 등 독립 지표·로그·알림, 수신/복구 테스트 |
| 개인별 로그인·MFA·계정 정지 | app_principals 제안 | chat_sessions와 admin_audit의 principal 연결 | 외부 인증 공급자, 토큰 검증, MFA·복구·권한 회수 |
| 로그인·거부·민감정보 조회 추적 | security_events 제안 | 기존 admin_audit는 공고 변경 근거로 유지 | 중앙 로그, 위변조 방지·접근 제한·보존 |
| 사용자/전체 일일 사용량 통제 | usage_budget_policies / usage_budget_windows / usage_reservations 제안 | model_invocations에 예산 예약 연결 | 서버 사전 승인·토큰/비용 추정·실패 정산·중지 수단 |
| 백업·복원·삭제·대조 실행 이력 | operational_runs 제안 | 실행 도구/대시보드 확장 | 서버 밖 백업, 스케줄, 격리 복원·실패 알림 |
| 배포·롤백 추적 | deployment_releases 제안 | 기존 배포 패키지·해시·Git SHA 활용 | IaC 정합화·배포 검사·건강 확인·롤백 |
| 스키마 적용 이력 | schema_migrations 제안 | 기존 schema.sql·개별 migration 유지 | 체크섬·잠금·멱등 실행·확장 후 전환 |
| 비밀 관리·회전 | 불필요 | 비밀 참조명/버전 등 비밀이 아닌 메타데이터만 허용 | Secrets Manager·서버 파일 권한·권한 분리·회전/폐기 |
| 일시적 요청 빈도 제한 | 기본 불필요 | 기존 API 제한 유지 | 게이트웨이 또는 만료형 카운터. 임시 DynamoDB Jobs 테이블과 별도 용도 |
| 물리적 권한 격리 | 불필요 | 내부 인증 컨텍스트 개선 | 관리자 처리 분리, 실행 역할·DB 자격증명·네트워크 경계 |

**핵심 신규 후보는 총 8개**다. app_principals, security_events, 예산 3개, operational_runs, deployment_releases, schema_migrations. 모두 즉시 만들지 않고 각 단계에서 필요한 것만 추가한다. 알림 자체·MFA 비밀·비밀번호·OS 패치는 이 8개 테이블이 해결하지 않는다.

## 3. 신규 테이블 논리 설계

공통 제안: 시각은 UTC, 기간/화면 표시 시간대는 명시, 비용은 DECIMAL과 통화 사용, 상태는 코드 enum/검증으로 제한한다. ID 형식·컬럼 크기·인덱스·외래키는 실제 쿼리와 삭제 정책을 검증한 후 DDL로 확정한다. 모든 JSON은 허용 키·크기 제한이 필요하다.

### 3.1 app_principals — 개인 신원과 앱 권한

| 필드 | 목적 |
|---|---|
| principal_id (PK) | 앱 내부 개인 식별자, 토큰 값과 분리 |
| identity_issuer / identity_subject | 인증 공급자가 검증한 iss/sub 매핑. 두 값 조합 UNIQUE |
| status | active / suspended / deleted 등 계정 상태 |
| app_role | 초기 user / admin. 세부 역할 필요 시 별도 설계 |
| authz_version | 정지·역할 변경 시 증가, 큐/캐시의 오래된 권한 판단 차단 |
| created_at / updated_at / disabled_at | 생명주기 메타데이터 |

- 인증은 외부 공급자에 맡기는 방향을 제안한다. 공급자 제품/리전/비용·계정 복구 방식은 미확정이다. 비밀번호, MFA 시드, OTP, access/refresh/ID token을 이 테이블에 저장하지 않는다.
- 앱 역할은 서버 관리 권한으로만 변경한다. 최초 관리자 등록은 통제된 운영 절차로 수행한다. 클라이언트 role·이메일 문자열·가입 순서만으로 관리자 승격하지 않는다.
- 인증 공급자가 사용자 신원을 확인하고, 앱은 principal 상태와 app_role로 권한을 판정하는 제안이다. 공급자 그룹을 권한 원본으로 선택한다면 이중 권한 원본이 생기지 않게 별도 ADR로 교체한다.
- 이메일·실명은 화면에 필요한 경우에만 추가한다. 이메일은 안정적 신원 키로 사용하지 않는다. 개인 삭제 후 감사 식별자 익명화/보존 범위를 확정해야 한다.
- 인덱스: UNIQUE(issuer, subject), 운영상 필요한 경우 status/role. 공급자별 subject 대소문자 보존 및 콜레이션을 검증한다.

### 3.2 security_events — 인증·인가·민감 조회 기록

| 필드 | 목적 |
|---|---|
| event_id (PK), event_key (UNIQUE) | 재전송 중복 방지용 사건 식별자 |
| occurred_at / received_at | 사건 발생·수집 시각 구분 |
| principal_id (nullable), actor_scope (nullable) | 검증된 신원 또는 과거 익명 범위. 실패 로그인을 특정 개인으로 단정하지 않음 |
| event_type / outcome / reason_code | auth_denied, admin_read, role_changed 등 분류와 결과 |
| request_id / trace_id / authz_version | API→큐→작업자 추적, 당시 권한 버전 |
| target_type / target_ref / result_count | 어떤 범위의 데이터를 조회/변경했는지. 본문은 제외 |
| metadata / retention_class / expires_at | 허용 목록 메타데이터와 별도 보존 정책 |

- 성공/실패 로그인 중 앱이 실제 관측한 것, 관리자 접근 거부, 메시지/근거 조회, 역할 변경·계정 정지, 비밀 회전 수행 사실을 기록한다. 로그인 공급자 내부 사건은 공급자 로그와 연결해야 한다.
- 토큰, 쿠키, 비밀번호, 사용자 대화 본문, 원본 SQL/오류 전체, presigned URL을 넣지 않는다. IP/User-Agent는 꼭 필요한지 결정하고 최소화한다. 해시 처리도 개인정보성 검토를 대체하지 않는다.
- **기존 admin_audit를 대체하지 않는다.** 공고 변경의 before/after·사유는 admin_audit, 접근/조회 사건은 security_events로 분리한다. 내부 이벤트 기록 자체를 재귀적으로 다시 기록하지 않는다.
- 공고 변경은 감사 INSERT가 실패하면 함께 롤백한다. 일반 로그인 거부/오류 기록은 독립 로그로도 전송해 MySQL 장애 때 사건이 사라지지 않게 한다. 민감 조회는 감사 가능한 상태일 때만 허용하는 정책을 우선 검토한다.
- 초기 작은 규모에서는 중앙 보안 로그만 먼저 사용하고 MySQL 검색 사본은 나중에 둘 수도 있다. 이 선택을 단계 S05에서 확정한다.
- 인덱스: (principal_id, occurred_at), (event_type, occurred_at), request_id. 기록용 계정은 INSERT 위주, 삭제/보존 처리는 별도 운영 권한으로 분리한다.

### 3.3 usage_budget_policies — 사용량 정책

| 필드 | 목적 |
|---|---|
| policy_id (PK), policy_version | 적용 규칙과 버전 |
| scope_type / scope_ref | 전체 서비스, 역할, 로그인 개인 등 적용 범위 |
| period_type / timezone | 일간/월간 기간과 경계 시간대. UTC 저장과 구분 |
| max_calls / max_input_tokens / max_output_tokens / max_estimated_cost / currency | 각각 선택 가능한 상한. NULL 의미를 명시 |
| warn_ratio / enforced / enabled | 경고·차단·사용 여부 |
| effective_from / effective_until / created_by / updated_at | 효력 기간과 변경 주체 |

- 개인 로그인 전에는 공유 토큰의 사람별 사용량 제한을 보장할 수 없다. 임시로 서비스 전체/역할별 예산부터 적용한다. 브라우저 식별자는 보조적 남용 억제용이다.
- 관리자 ‘세션 횟수 무제한’과 서비스 전체 일간 비용 한도는 양립한다. 관리자가 모든 예산·경보를 자동 우회하도록 만들지 않는다.
- 실제 상한, 알림 비율, 시간대, 관리자 예외 여부는 사용자 결정 사항이다. 예시 금액을 운영 확정값으로 쓰지 않는다.

### 3.4 usage_budget_windows — 기간별 사용·예약 합계

| 필드 | 목적 |
|---|---|
| window_id (PK), policy_id / policy_version | 정책과 해당 버전 |
| scope_type / scope_ref / window_start / window_end | 정확한 집계 범위와 경계 |
| used_calls / reserved_calls | 실제 시도·사전 예약 호출 수 |
| used_input_tokens / used_output_tokens / reserved_tokens | 확인된 사용량과 보수적 예약량 |
| used_estimated_cost / reserved_estimated_cost / currency | 추정 비용의 사용·예약 합계 |
| updated_at | 마지막 정산 시각 |

- UNIQUE(policy_id, policy_version, scope_type, scope_ref, window_start). 집계만 조회하고 나중에 차감하는 구조로 구현하지 않는다. 잠금/조건부 갱신으로 동시 요청의 초과 승인을 막는다.
- 모델 한 번 호출에 전체/역할/개인 정책이 함께 적용될 수 있다. 같은 트랜잭션에서 고정 순서로 잠그고 모두 예약하거나 전부 취소한다. 정책 버전 변경으로 같은 기간의 이미 쓴 사용량이 초기화되지 않게 이월/유효 시점을 정의한다.
- model_invocations가 24시간 후 삭제돼도 일간/월간 예산 합계가 사라져 한도가 초기화되지 않아야 한다. 집계 보존은 대화 보존과 분리한다.

### 3.5 usage_reservations — 호출 전 예약·호출 후 정산

| 필드 | 목적 |
|---|---|
| reservation_id (PK), reservation_key (UNIQUE) | 동일 호출 시도의 이중 차감 방지 |
| invocation_id / request_id / attempt_no | 실제 모델 호출 시도와 연결 |
| principal_id (nullable), scope_ref, model_id / region | 책임 범위와 가격 적용 정보 |
| status | reserved / settled / cancelled / uncertain |
| window_allocations | 예약에 참여한 window ID·정책 버전·금액. 필요 시 관계 테이블로 분리 |
| reserved/actual input·output tokens, reserved/actual estimated_cost | 승인 상한과 실제 정산 |
| pricing_version / currency / usage_complete | 가격표 버전과 사용량 확인 여부 |
| created_at / dispatched_at / settled_at / expires_at | 예약 생명주기·호출 전송 여부 |

- 호출 전에 입력 추정과 최대 출력·적용 가격으로 보수적으로 예약하고, 성공/실패 후 실제 제공 사용량을 정산한다. 합성 사용량을 실제 청구로 표시하지 않는다.
- SDK가 숨겨서 재시도한 호출까지 관측할 수 있는지 점검한다. 불가하면 자동 재시도 축소 또는 최대 시도 수를 포함한 예약 정책이 필요하다. 명시적 재시도는 새 attempt와 새 예약으로 기록한다.
- 타임아웃은 무료 호출이라는 뜻이 아니다. 전송 후 사용량 미확인은 uncertain으로 남기고 예약을 바로 반환하지 않는다. 프로세스 중단 후 조정 작업이 필요하다.
- 응답 캐시 적중은 새 모델 호출 예약을 만들지 않는다. 같은 요청 재조회/폴링도 중복 예약하지 않는다.
- 예약 상태/기간 경계·가격표 버전은 호출 시 고정한다. 가중 토큰·프롬프트 캐시·교차 리전 가격 적용을 확인한다. 앱 추정 예산은 AWS 전체 청구액의 절대 상한을 보장하지 않는다.
- 별도 장기 usage_events·daily_costs 테이블은 초기부터 중복 생성하지 않는다. 예약과 기간 합계로 부족한 분석 요구가 입증되면 확장한다.

### 3.6 operational_runs — 백업·복원·삭제·정합성 점검 이력

| 필드 | 목적 |
|---|---|
| run_id (PK), run_type | backup / restore_test / retention_cleanup / index_reconcile / credential_rotation 등 |
| schedule_key / idempotency_key | 중복 실행 방지와 예약 연결 |
| status / phase / started_at / finished_at | pending / running / succeeded / failed / partial 및 중단 단계 |
| initiated_by / trace_id / deployment_id | 수동·예약 주체 및 배포와 연결 |
| artifact_uri / artifact_version / checksum | 비공개 백업·보고서 식별자. 서명 URL·비밀은 금지 |
| counters / verification_summary / error_code | 처리·건너뜀·실패 수와 검증 결과. 본문은 제외 |
| parent_run_id / next_retry_at / retention_class / expires_at | 복원 대상 백업 연결·재시도·이력 보존 |

- 같은 테이블로 실행 종류를 구분한다. backup_runs·restore_runs·cleanup_runs를 우선 각각 만들 필요는 없다.
- 백업이 저장됐다는 결과와 복원 테스트 성공은 별도 run이다. gzip 검증을 복원 완료로 기록하지 않는다.
- 운영 DB가 죽으면 이 테이블도 기록할 수 없다. 외부 로그/비공개 저장소 manifest에도 실행 ID와 복구 결과를 남기고 복구 후 연결한다.
- 백업 오브젝트 생명주기와 run 이력 보존은 독립이다. 메타데이터 행 삭제가 S3 삭제를 뜻하지 않으며 반대도 동일하다.
- 인덱스: (run_type, started_at), (status, next_retry_at), UNIQUE(idempotency_key). null 값/재시도 규칙은 DDL에서 확정한다.

### 3.7 deployment_releases — 배포·롤백·스키마 호환성

| 필드 | 목적 |
|---|---|
| deployment_id (PK), release_id | 배포 시도와 빌드 산출물 식별자 |
| environment / component / git_sha | 어디의 어느 코드를 배포했는지 |
| artifact_uri / artifact_sha256 / config_revision | 재현 가능한 코드/설정 참조. 설정 내용·비밀값 금지 |
| schema_min_version / schema_max_version | 해당 코드가 읽고 쓸 수 있는 스키마 범위 |
| previous_deployment_id / rollback_of | 이전 정상 버전·복구 관계 |
| status / initiated_by / started_at / finished_at | 빌드/적용/확인/복구 진행 상태 |
| verification_run_id / sanitized_error_code | 건강 확인·검증 이력 연결 |

- frontend / Lambda / worker / sync를 구분한다. 일부만 성공한 배포를 전체 성공으로 기록하지 않는다. 배포 이력은 덮어쓰지 않는다.
- 초기에는 비공개 아티팩트 manifest와 CI 로그가 기준이 될 수 있다. 관리자 통합 조회 필요 시 DB 사본을 추가한다. DB가 안 될 때 배포 복구를 막는 필수 의존성으로 만들지 않는다.
- 구성 변경은 비밀 참조 버전만 기록한다. 비밀 회전 시 과거 비밀값을 롤백용으로 복사하지 않는다.

### 3.8 schema_migrations — 실제 적용된 DDL 이력

| 필드 | 목적 |
|---|---|
| migration_id (PK) / checksum | 정렬 가능한 버전과 적용 파일 해시 |
| status / started_at / applied_at | started / applied / failed 등 상태 |
| executor / deployment_id / duration_ms | 실행 주체·배포·소요 시간 |
| verification_summary / error_code | 민감정보 없는 검증 결과 |

- 이미 적용한 migration 파일은 수정하지 않고 후속 파일을 추가한다. 같은 버전의 해시가 다르면 중단한다.
- MySQL DDL 전체가 트랜잭션 롤백된다고 가정하지 않는다. 중간 실패 시 실제 컬럼/인덱스를 대조한 후 재개한다.
- 기존 DB는 현재 schema.sql을 무조건 다시 실행해서 과거를 덮지 않는다. 실제 구조를 조사해 기준 버전을 등록하고 운영 외부에서도 manifest를 보관한다.
- 새 테이블만 먼저 만들고 nullable 컬럼 확장 → 구/신 코드 호환 배포 → backfill → 읽기 전환 → 별도 검증 후 제약 강화 순서를 기본으로 한다. 자동 down migration/테이블 삭제는 기본 복구 수단이 아니다.

## 4. 기존 테이블 변경 제안

| 기존 테이블 | 추가/변경 제안 | 유지해야 하는 것 |
|---|---|---|
| chat_sessions | principal_id nullable, auth_method, 필요 시 authz_version/retention_class | 기존 owner_scope·24시간 expires_at·요청 멱등성. 과거 소유권을 임의 이관하지 않음 |
| chat_messages | 필요 시 trace_id/retention_class. principal을 세션에서 유도할 수 있으면 중복 저장하지 않음 | 사용자 원문·실패 전달 상태·세션 종속 삭제 |
| model_invocations | reservation_id nullable, trace_id, 필요 시 오류 단계/모델 호출 시도 식별 보완 | 기존 실제 사용량·purpose·attempt_no·가격 관련 컬럼 재사용. estimated_cost/pricing_version 이미 존재 |
| admin_audit | actor_principal_id nullable, auth_method, trace_id, authz_version 제안 | 과거 actor_scope, request_id 고유성·before/after·사유 보존 |
| recommendation_evidence | 신원은 세션/메시지 연결로 유도, 검색 근거 확장은 기존 별도 계획과 조율 | 원문 근거·버전·만료·합격 판정과 검색 일치 분리 |
| response_cache | 신원·권한 버전이 달라지면 재사용하지 않는 scope/key 정책. 필요 시 principal/authz_version 메타데이터 | 기존 소유 범위·TTL·무효화·멱등 캐시 |
| search_outbox | 기존 pending/attempt_count/last_error/processed_at로 우선 감시. 독립 실행 이력과 trace 연결은 필요 시 추가 | 단조 버전·Outbox 원자성·실패 재시도 |
| job_postings / training_offerings | 보안 개선만을 이유로 신원·로그·예산 필드를 추가하지 않음 | 출처+ID·원본·버전·날짜·모집 미확인 구분 |

외래키는 보존과 삭제 전파를 먼저 결정한다. 특히 principal 삭제가 관리자 감사·월간 예산·운영 복구 이력을 연쇄 삭제하면 안 된다. 새 이력에서 model_invocations로 FK를 둔다면 짧은 대화 보존 때문에 예약/집계가 지워지지 않는 관계를 선택한다.

## 5. DB 이외에 반드시 바꿀 것

### 접근·권한

- 개인 로그인/MFA를 붙여도 화면 URL을 나누는 것으로 끝내지 않는다. Lambda의 입장·폴링과 작업자의 실행 직전에 권한/정지 상태를 재확인한다. 관리자 권한 회수 후 이미 큐에 있는 변경 작업도 차단한다.
- 인증 토큰을 DynamoDB/SQS payload로 복사하지 않는다. 검증된 principal·허용 작업·권한 버전·요청 지문만 전달하는 내부 계약을 정한다. 브라우저가 보낸 신원/역할을 그대로 신뢰하지 않는다.
- 사용자와 관리자 작업은 현재 같은 프로세스에서 두 자격증명을 읽는다. 실행 경로·IAM 역할·DB 권한의 분리를 설계하고, 같은 EC2를 유지하면 호스트 침해에 대한 완전 격리는 아니라는 한계를 명시한다.
- ES는 현재 loopback 제한이다. 향후 호스트 분리 시 인증·TLS·접속 제한을 다시 설계한다. 공개 포트 개방으로 연결 문제를 해결하지 않는다.
- 로그인 성공·토큰 만료·회전·계정 정지·비밀 읽기 실패·소유권 거부를 점검한다. 사용자 인증의 MFA와 AWS 운영자 SSO/MFA는 별개다.

### 감지·알림

- 감시 후보: HTTP 5xx/502, 작업자/동기화 중단, 큐 최장 대기·DLQ, Outbox 최고 대기 시간/재시도, DB 연결 실패, ES health/응답 지연, 메모리·디스크·CPU 크레딧, 비정상 관리자 접근·일별 모델 사용량.
- 알림 수신자·판정 기간·복구 알림·재알림 간격은 미정이다. 저사용량에서 오류율만 쓰지 말고 최소 요청 수·절대 실패 수·heartbeat와 함께 설계한다.
- worker journal이 서버에만 남는지, 실제 중앙 로그 수집이 되는지부터 확인한다. 지표/로그/알림의 생성만으로 완료 처리하지 않고 합성 실패 → 실제 수신 → 복구 통지를 검증한다.
- 기존 API 빈도 제한은 전체 서비스 admission/polling에 영향을 준다. 로그인/채팅/관리 작업/폴링의 서로 다른 부하와 비용을 구분해 조정한다.

### 백업·복구·보존

- 서버 밖의 비공개 백업과 정기 스케줄·암호화·접근 권한·생명주기를 정한다. 지금 서버 디스크의 백업만으로 호스트/볼륨 손실 복구를 입증할 수 없다.
- 복원은 격리 DB에서 진행한다. 테이블 수·행 수·참조 무결성·신원/권한·한글/JSON·최신 source_version을 확인하고, 복원 DB로 ES를 재생성해 검색까지 검증한다.
- RPO(허용 데이터 손실 시간)·RTO(목표 복구 시간)는 아직 미정이다. 실제 복구 시간을 측정한 뒤 목표를 확정한다.
- 복구된 과거 백업에는 이미 삭제한 개인정보·정지 전 권한·지출 전 카운터가 포함될 수 있다. 재오픈 전 삭제/정지/비용 상태를 재적용할 절차가 필요하다. 필요하면 최소 정보의 deletion_tombstones를 별도 설계한다.
- cleanup_chat.py의 순서·1,000행 제한과 FK CASCADE를 검토한다. 일부 부모 삭제로 전체 삭제량이 커지는지 확인하고, 짧은 배치·잠금·재시도·외부 실행 이력으로 제한한다. 단순 스케줄 연결 전 권한/성능 검증이 필요하다.
- DB 만료 조회 제외, 물리 삭제, DynamoDB TTL, S3 원본/백업 삭제, CloudWatch 보존은 각각 다르다. 기간을 한 값으로 자동 통일하지 않는다.

### 배포·패치

- 실제 t4g.medium과 초기 LaunchTemplate t4g.small의 차이를 조사하고 유지 리소스 교체 여부를 검토한 변경 계획으로 IaC를 맞춘다. 템플릿을 무조건 재적용하지 않는다.
- 현재 운영에 필요한 Elasticsearch·동기화·관리자 설정이 새 환경 재현 절차에 포함되는지 확인한다. 초기 bootstrap만으로 현재 서비스 전체가 재현된다고 주장하지 않는다.
- 코드/SQL/설정의 독립 변경과 결합 배포를 구분한다. schema 호환 범위·Git SHA·패키지 해시·검증 결과·이전 정상 릴리스를 연결한다.
- OS·Python·npm·컨테이너 이미지 의존성 점검과 정기 업데이트 절차를 둔다. 수정 전 백업·정상 흐름 검증·문제 발생 시 복구 경계를 명시한다.

## 6. 단계별 실행 체크리스트

한 단계마다 구현 → 격리 검증 → 적용 계획 검토 → 소량 운영 적용 → 결과 기록 순서로 진행한다. 이 문서는 실제 작업의 일괄 실행 지시가 아니다.

| 단계 | 작업 | DB 변경 | 완료 증거 | 실패 시 대응 |
|---|---|---|---|---|
| S00 | 운영 설정·권한·보존·백업/릴리스 기준선 목록 작성 | 없음 | 민감값 없는 현황/차이 보고서 | 읽기 전용으로 중단, 미확인 항목 분리 |
| S01 | 독립 로그·핵심 장애 알림 연결 | 없음 | 합성 장애 실제 수신·복구 알림, 수신자 확인 | 새 알림/수집 설정만 이전 버전으로 복구 |
| S02 | 버전형 migration 도구·기준 버전 등록 | schema_migrations만 | 해시 불일치·중복 적용·중간 실패 복구 시험 | 기존 런타임 유지, DDL 자동 역삭제 금지 |
| S03 | 외부 정기 백업·격리 복원·삭제 실행 이력 | operational_runs | 서버 밖 백업에서 실제 복원, 소요 시간 측정 | 운영 원본 미변경, 실패 run/외부 manifest 보존 |
| S04 | 인프라 정합화·배포 추적·롤백 훈련 | deployment_releases 필요 시 | 리소스 교체 없는 변경 계획, 이전 정상 코드 복귀·schema 호환 확인 | 승인된 이전 코드/설정 복구, DB는 forward fix 우선 |
| S05 | 개인 관리자 로그인·MFA·정지·권한 회수와 보안 사건 | app_principals, security_events 선택 확정, 기존 nullable 연결 | 일반 거부, MFA/만료/정지·소유권·큐 재검증·조회 감사 시험 | 인증 실패 시 닫힌 상태 유지, 제한된 운영자 SSM 복구 경로 |
| S06 | 전체/역할/개인 일일 예산과 예약·정산 | usage_budget_policies/windows/reservations, invocation 연결 | 동시 호출·캐시·재시도·타임아웃·재시작·날짜 경계 검증 | 신규 모델 호출을 제한, 미확인 예약 유지·조정, 무제한 우회 금지 |
| S07 | 데이터별 보존 확정·정기 삭제·복원 후 삭제 재적용 | operational_runs 재사용, retention 필드 필요 시 | 격리 실제 삭제·관련 데이터/원본 보존·실패 후 재개 검증 | 삭제 확대 전 중단, 검증된 복구 절차 사용 |
| S08 | 관리자 실행 권한/프로세스 분리·비밀 회전 | 보통 없음, audit 재사용 | 일반 경로에서 관리자 DB/비밀 접근 불가, 회전·폐기·큐 영향 검증 | 노출된 비밀을 부활시키지 않는 운영 복구 |
| S09 | 정기 패치·장애 훈련·검색 정합성 점검 | operational_runs / deployment_releases 재사용 | 호스트/DB/ES/큐/모델 장애별 감지·복구·데이터 일치 보고서 | 정의된 복구 경로, 고용24 대규모 부하 시험은 별도 범위 유지 |

최소 착수는 S00→S01이다. S02 이후 테이블은 선행 조건이 충족된 단계에서만 추가한다. 모니터링을 위해 8개 테이블부터 만들 필요가 없다. S05의 개인 식별 이후에만 ‘개인별 일일 예산’을 보장한다고 표시한다.

각 단계 기록 템플릿:

```text
단계/상태: 미착수 | 설계 | 로컬 검증 | 격리 DB 검증 | 운영 적용 | 검증 완료 | 보류
담당/실행 주체:
문제와 변경 범위:
선행 조건·미결 결정:
변경 코드/설정/테이블·migration ID:
기존 데이터 영향·보존·새 권한:
테스트·합성 실패·수신/복구 증거:
백업 위치 참조·복구 절차·적용 중단 조건:
Git SHA·release ID·운영 적용 시각:
적용 전후 수치·잔여 문제:
```

## 7. 권한·데이터 보존의 공통 통과 기준

- 인증이 없거나 권한이 불명확하면 관리자 기능을 허용하지 않는다. 예산 DB 장애 시 모델 호출을 무제한 허용하지 않는다.
- 일반/관리자 조회/변경/계정 정지/예산 정책 수정/감사 조회 권한을 구분한다. UI 버튼 숨김만으로 권한을 적용하지 않는다.
- 감사 작성 계정은 임의 UPDATE/DELETE를 할 수 없게 하고 보존 삭제·운영 migration 계정과 분리한다. 기존 runtime 계정에 전역 권한을 일괄 부여하지 않는다.
- 새 테이블을 관리자 화면 허용 목록에 추가할 때 필요한 컬럼만 노출하고 principal·대화 조회 범위 및 audit 정책을 확인한다. 테이블 존재 전부터 모든 환경에서 SELECT하지 않는다.
- 기간은 현재 24시간 앱 세션 설정을 전체 데이터에 복제하지 않는다. 대화 원문, 보안 사건, 감사, 예산 합계, 예약 멱등성, 배포/복구 이력, 백업별 기간과 삭제 책임을 별도로 확정한다.
- 민감값은 예제·문서·로그·테스트 산출물·Git에 포함하지 않는다. 스키마·실행 이력에는 비밀 참조/버전·상태만 기록한다.
- 자동 삭제/백업/복구/회전·알림을 ‘코드가 있음’만으로 완료 표시하지 않는다. 실제 실행과 결과 대조가 통과 기준이다.

## 8. 선택적으로만 추가할 테이블

| 후보 | 필요한 조건 | 초기 대안 |
|---|---|---|
| alert_incidents | 담당자 배정·확인/종료·SLA 관리가 앱 안에서 필요할 때 | CloudWatch 알림 + 정해진 대응 문서 |
| app_roles / app_role_permissions / principal_roles | 다중 역할·기관별 세부 권한이 실제로 필요할 때 | app_principals.app_role + 서버 허용 목록 |
| retention_policies | 운영자가 데이터별 기간을 동적으로 편집해야 할 때 | 버전 관리된 설정 + 별도 승인 기록 |
| deletion_tombstones | 백업 복원 후 삭제 요청 재적용이 필요할 때 | 명시된 백업 보존/폐기·외부 최소 정보 삭제 이력. 신원/보존 정책부터 결정 |
| usage_reservation_items | 다수 정책/window 정산을 관계형 제약·조회로 관리해야 할 때 | 제한된 window_allocations 계약으로 시작, 원자성 요구가 복잡하면 처음부터 관계 테이블 선택 |
| search_runs / search_result_evidence | 검색 당시 후보/근거·후속 설명 구현 시 | [검색 문맥·근거 계획](SEARCH_CONTEXT_EVIDENCE_PLAN.md)의 별도 결정 |

비밀번호 테이블, MFA 코드 테이블, 원문 토큰 보관 테이블, CPU/메모리 원시 시계열 테이블, 전체 AWS 청구 복제 테이블은 이번 계획에 넣지 않는다.

## 9. 결정이 필요한 값

아래는 미정이다. 문서 작성이나 상한 예시가 사용자 승인·정책 확정을 대신하지 않는다.

1. 로그인 공급자, 관리자 인원·권한, MFA 방식·계정 복구·권한 회수 시점.
2. 알림 받을 사람/수단, heartbeat·에러·적체·디스크·비용 기준과 재알림 주기.
3. 정기 백업 빈도·보존·서버 밖 저장 위치·권한, RPO/RTO와 복원 훈련 주기.
4. 대화/개인정보·감사·보안 사건·예산·배포 기록별 기간과 개인 삭제 처리.
5. 서비스/역할/개인 일간·월간 예산, 가격 추정 버전·통화·불확실 사용량 처리.
6. 작업 중단을 허용할 시간, 새 리소스가 필요할 때 예산, 단일 호스트 유지/분리 기준.

## 10. 기존 계획과의 연결·참고

- 현재 배포 근거: [관리자 대시보드](ADMIN_DASHBOARD.md), [검색 동기화](SEARCH_SYNC.md).
- 검색 문제·추천 근거 저장과 성능 검증은 계속 별도 작업이다: [검색 문맥·근거](SEARCH_CONTEXT_EVIDENCE_PLAN.md), [성능 평가](PERFORMANCE_EVALUATION_PLAN.md). 보안 개선 완료가 검색 품질 문제 해결을 뜻하지 않는다.
- 운영 기준: [OPERATIONS.md](OPERATIONS.md), DB 기준: [DATA_MODEL.md](DATA_MODEL.md), 적용 전 확인: [QA_CHECKLIST.md](QA_CHECKLIST.md).
- 외부 기준: [AWS 인증 관리](https://docs.aws.amazon.com/wellarchitected/latest/framework/sec-02.html), [OWASP 권한 검증](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html), [OWASP 보안 로깅](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html). 이 링크가 프로젝트의 구현/인증 완료를 뜻하지 않는다.

## 11. 이번 문서 작업 결과

- 신규 후보 8개와 조건부 확장 테이블, 기존 테이블 변경 범위, DB 밖 설정·운영 작업을 구분했다.
- S00~S09의 순서·선행 조건·완료 증거·복구 기준을 정리했다.
- **실제 DDL/DML, 개인정보 삭제, 모델 호출, AWS 리소스 생성/수정, 인증 전환, Git 커밋/푸시는 실행하지 않았다.**
