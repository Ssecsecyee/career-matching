# 데이터 모델

## 2026-10-30 추천 근거 확장 계획

chat_messages 원문/응답과 chat_sessions 검색 선호를 참조하고 recommendation_evidence의 기존 스냅샷 필드를 활용하는 방향이다. 현재 writer는 조건 자기평가 중심이다. 검색 후보 근거 유형·실행 계획·발언 참조·정책 버전 저장 계약과 최소 스키마 변경을 구현 전에 확정한다. DDL은 이번에 수정하지 않으며 24시간 세션 만료와 물리 삭제·백업 보관은 구분한다.

상세 계약·실제 재현·저장 책임·추가 작업 순서는 [검색 문맥·추천 근거 개선 계획](SEARCH_CONTEXT_EVIDENCE_PLAN.md)을 따른다. 이 추가 절은 후속 설계이며 이번 문서 수정으로 코드·스키마·운영 기능을 변경하지 않았다.


## 2026-10-29 Elasticsearch 도입 합의와 구현 상태

이 절은 아래 과거 초안의 검색엔진 관련 설명보다 우선한다. **로컬 Nori·동의어 실행과 실제 스냅샷 783건 색인·검색 어댑터 검증을 완료했으며 운영 Elasticsearch는 미도입이다.** 직접 설치 방식으로 진행하며 OpenSearch·Elastic Cloud로 자동 대체하지 않는다. 로컬 Docker에서 분석기·색인·백엔드·동기화를 검증한 뒤 AWS에 배포한다. S3는 원본·백업 저장소이며 검색엔진 설치 위치가 아니다.

검색 문서는 MySQL에서 재생성 가능한 사본이다. source+source_id를 고유 식별자로 사용하고 source_version, indexed_version, 제목·주요업무·자격요건·우대사항·기술·지역·모집 상태·마감 근거를 유지한다. 본문 검색 필드와 정확 일치 필드를 구분한다. 날짜만 있는 마감일에 임의 시각을 만들거나 unknown을 active로 바꾸지 않는다.

채용과 교육은 필드·판정 의미가 달라 색인과 매핑을 분리한다. 초기 연결은 채용부터 진행하고 교육 검색 전환은 별도 검증한다. 재색인은 버전별 새 색인 생성→검증→별칭 전환 방식으로 계획하며 실제 매핑·별칭 이름은 구현 시 확정한다.

## 2026-10-28 최신 상태와 고용24 전환 계획

이 절의 실행 현황과 전환 방향을 아래의 과거 초안보다 우선한다. 현재 AWS 웹·대화 서버·EC2 MySQL 연결을 검증했으며 RDS와 Elasticsearch는 사용하지 않는다. 점핏 추가 표본 10건은 백업 후 운영 반영해 총 793건이며, 기존 783건의 버전·해시는 유지했다. 신규 10건의 모집 상태는 unknown이다. **고용24 승인 후 소량 표본 검증을 거쳐 AWS 정기 배치 자동화로 전환**한다. 상세 단계와 통과 기준은 [고용24 파이프라인 계획](../app/ingestion/GOYONG24_PIPELINE.md)을 따른다.

### 고용24 매핑 원칙

job_postings의 공통 구조와 대화·근거 테이블은 유지하되 source=goyong24와 원문 source_id로 식별한다. 점핏과 같은 ID여도 서로 다른 행이다. 직종·지역·학력·경력 코드는 원문 및 정규화 값을 함께 보존하고 날짜 정밀도·미제공 필드를 추정하지 않는다. 실제 필드명·ID 형식은 승인 후 목록/상세 응답을 확인해 확정한다. 현재 source=jumpit·숫자 ID 하드코딩과 source_id 단독 세션/캐시 식별을 수정해야 한다. 추가 컬럼이 필요하면 별도 마이그레이션으로 검토한다. Outbox는 DB 반영과 함께 기록하며 검색 색인 완료와 구분한다.

수정일: 2026-10-28. 논리 모델이며 실제 테이블 마이그레이션은 별도 작업이다.

## 공통 객체

Opportunity는 job / program으로 구분한다. 식별자는 source + source_id로 고정한다. 원문 직무·태그와 서비스 정규화 값을 함께 보관하며 복수 카테고리를 지원한다.

공통 필드: opportunity_id, source, source_id, source_url, title, provider_name, original_categories, role_categories, skill_tags, published_at, deadline, deadline_type, status, retrieved_at, last_seen_at, source_updated_at, content_hash, source_version, raw_object_key.

게시일·원본 수정일이 없으면 null이다. 수집 시각을 게시일로 대체하지 않는다. 마감일 미기재·상시채용·채용시 마감을 구분한다. status는 active / closed / unknown 등으로 관리한다.

## 채용 상세

- responsibilities: 주요업무 원문.
- qualifications: 자격요건 원문.
- preferred_requirements: 우대사항 원문.
- benefits: 복지·혜택 원문.
- hiring_process: 채용절차 원문.
- application_notes: 지원 유의사항 원문.
- addresses: 상세주소 목록.
- experience, education, employment_type, work_mode: 원문과 정규화 값.
- additional_sections: 알려지지 않은 상세 섹션도 제목·본문으로 보존.
- field_status: 항목별 present / not_provided / fetch_failed / parse_failed.

## 조건과 근거

Requirement: requirement_id, opportunity_id, type(required / preferred / unspecified), condition_type(skill / experience / education / certificate / other), original_text, normalized_value, group_id, logical_operator, evidence_id, source_version.

Evidence: evidence_id, opportunity_id, section, quote, source_url, source_version. 단순 기술 태그에 있다는 이유만으로 필수 기술로 분류하지 않는다.

## 교육 모집

과정(course)과 기수(cohort)를 분리한다. 추천 단위는 모집 기수이다.

필드: course_id, cohort_id, provider, original_category, normalized_domains, curriculum_text, learning_topics, skill_tags, eligibility, application_start, application_deadline, start_date, end_date, delivery_mode, addresses, tuition, subsidy, selection_process, benefits, source_url 및 공통 추적 필드.

부트텐트 소프트웨어·AI개발의 실제 코드·필드·수집 방식은 허용 범위 확인 후 검증한다. 미기재는 추정하지 않는다.

## 프로필·세션

UserProfile: 목표 직무, 기술, 학력, 경력, 지역, 교육 시간·비용 조건. 사용자 진술과 확인 시각을 기록한다.

Session: session_id, owner_id, stage, selected_job_ids, profile_version, question_history, requirement_answers, total_usage, expires_at.

RequirementAnswer: requirement_id, answer, status(met / unmet / unknown), evidence_source(user_statement 등), checked_source_version. 기술 미확인은 미보유가 아니다. OR 조건과 AND 조건을 별도로 평가한다.

## 검색과 색인

SearchPlan: intent, role_categories, skill_tags, allowed_filters, top_k. 서버가 범위 검증 후 검색식으로 변환한다.

Elasticsearch 초안:

| 타입 | 필드 |
|---|---|
| keyword | ID, 출처, 유형, 직무, 기술, 지역, 상태 |
| text | 제목, 주요업무, 자격요건, 우대사항, 교육과정 |
| date | 게시일, 마감일, 교육 기간, 마지막 확인일 |
| integer / float | 경력 범위, 비용 |
| nested | 조건과 해당 근거의 관계를 보존할 항목 |

job / program 논리 인덱스를 분리하고 공통 분류 키로 연결한다. 한국어 분석기·기술 동의어는 배포 환경 검증 후 결정한다. 벡터 검색은 초기 필수 범위가 아니다.

## 변경 이벤트

event_id, opportunity_id, operation(upsert / close / delete), source_version, created_at, processed_at, attempt_count. 내용 해시는 변동성 수집 시각을 제외한 정규화 본문으로 계산한다. 검색엔진 indexed_version과 DB source_version을 대조한다.

삭제·마감은 원문 보존 정책과 검색 노출 정책을 구분한다. DB에서 전체 색인을 재생성할 수 있어야 한다.

## 대화·근거·캐시 저장 보완 (2026-10-28)

chat_sessions(소유 범위·상태·프로필 버전), chat_messages(순서·중복 키), recommendation_evidence(원문·사용자 진술·판정 스냅샷), model_invocations(실제 호출·토큰·캐시 토큰·지연), response_cache(범위·키·데이터 버전·만료)를 추가한다. 현재 SQL은 빈 구조이며 테이블만으로 TTL 삭제·자동 무효화가 작동하지 않는다. 상세 계약: ../workspace/database/mysql/CONVERSATION_STORAGE.md.

## 오프라인 정제 보완

모든 수집 폴더의 raw/details와 provenance를 공고 ID로 결합하고 최신 수집 스냅샷을 선택한다. 마감일 경과와 실시간 모집 확인을 구분한다. 로컬 검색 검증은 명시적 opt-in으로 unknown 스냅샷을 포함할 수 있지만 상태를 active로 바꾸지 않는다. 지원 유의사항과 전체 상세 완전성은 추가 원문 대조 대상이다.

## 2026-10-28 실제 정제 확인

사용자가 실행한 전체 정제 보고서: 783/783건, complete=true, closed 23건·unknown 760건. 주요업무·지원 자격·우대조건·주소는 모두 존재한다. 혜택 768건, 채용절차 729건, 지원 유의사항 독립 추출 0건이다. 이는 필드 존재 확인이며 의미 정확성·최신 웹 상태·모든 섹션 수집 완료를 뜻하지 않는다. 최초 MySQL 데이터 SQL 생성 도구는 app/ingestion/export_mysql_data.py이며 아직 실행·적재하지 않았다.


## 2026-10-28 로컬 대화 기억 구현

기존 chat_sessions.profile_snapshot.memory에 최근 사용자 발언, 원문 근거가 있는 주제별 정보, 명시적 조건 답변을 저장한다. requirement_answers에 조건 목록·조건 ID별 결과·현재 질문을 보관한다. 스키마 변경은 없다. 전체 대화와 과거 정정 기록은 chat_messages에 보존한다. 사용자 정보는 사용자 진술이며 검증된 보유 역량을 뜻하지 않는다.


## 교육·학습 루트 데이터 준비 (2026-10-28)
최종 교육 출처는 고용24 국민내일배움카드 훈련과정·일정 API다. 부트텐트는 허락이 없어 실제 스크래핑을 보류하고 직접 작성 가상 표본으로 공통 구조를 준비했다. [교육 데이터 계약·진행 순서](../app/ingestion/TRAINING_DATA_CONTRACT.md)를 따른다. 교육 과정 실수집·운영 적재·매칭 완료를 뜻하지 않는다.


## 교육 표본 실제 적재 보완 (2026-10-28)
AWS EC2 MySQL training_offerings에 실제 공개 교육 7건을 적재했습니다. 모집 상태는 모두 unknown이며 additional_sections.recommendation_eligible=false입니다. training outbox 7건을 생성했고 챗봇 추천 및 검색엔진 소비자는 미연결입니다. 상세 검증 결과는 workspace/incoming/boottent/boottent_20261028_real02/aws-result.json 참조.
