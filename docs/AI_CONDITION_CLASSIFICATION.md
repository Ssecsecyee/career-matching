# AI 공고 조건 구조화·질문 선정·검색 반영

상태: 로컬 구현·MySQL/ES 통합 검증 완료 / AWS·실제 모델 평가 미실행

## 방향

공고 원문 → AI 분류 → 서버 계약·원문 연결 검증 → MySQL 분류 이력 + Outbox → ES 검색 사본 → 문답/후속 역량 검색에 활용한다. 사용자가 선택한 공고만 분류하는 방식으로 제한하지 않는다. 기존 공고를 제한 배치로 채우고 신규·조건 변경 공고를 반복 처리한다. 미분류 공고도 기존 원문 검색·문답을 유지한다.

## 데이터 계약

원문 조건 key와 원문 위치를 조합한 해시를 AI condition_id로 사용한다. 반복된 동일 문장도 구분하며 기존 파서의 섹션 해시·유형·원문·위치에서 생성되므로 주소/마감일 변경만으로 달라지지 않는다. 분류는 ask/reference/review, 조건 유형은 기술·경력·학력·자격·성향·기타로 구분한다. reason_code와 짧은 사용자용 이유를 보관한다. 논리식은 atom/all/any/unresolved 트리이며 개별 atom의 evidence는 원문 인용 안의 정확한 문자열이어야 하고 term도 evidence에서 발췌해야 한다. 번역·동의어 정규화는 ES 분석기와 후속 정책으로 분리한다. AI 의미 해석의 정확성은 별도 평가로 검증한다.

원문은 모델이 재작성하지 않는다. 원본 job_postings와 분류 이력을 분리하고 조건 해시·파서/정책/모델 버전·출처 버전·토큰을 남긴다. 같은 해시와 정책은 재사용하며, 조건 변경·정책 변경 시 새 분류를 만든다. 과거 분류와 사용자 답변을 덮어쓰지 않는다. reference는 질문 생략일 뿐 공고 조건 삭제나 사용자 충족 판정이 아니다.

## 저장·동기화

새 job_condition_reviews 테이블에 분류 JSON과 메타데이터를 저장한다. 저장 전 공고 행 공유 잠금(FOR SHARE)과 조건 해시 재검증으로 수집 중 변경을 방어한다. 같은 트랜잭션에서 source_version을 유지한 Outbox 이벤트 operation=r:<review_id>를 기록한다. 이벤트 고유성은 기존 source_version·operation 키를 활용한다. 원문 버전을 올려 사용자 문답을 무효화하지 않는다.

소비자는 분류 이벤트를 허용하고 현재 공고·현재 조건 해시/정책에 맞는 분류만 색인한다. 단일 소비자 잠금과 ES 외부 원문 버전 방어는 유지한다. 분류만 바뀐 경우 동일 원문 버전의 최신 DB 사본을 반영한다. 전체 재색인은 기존 소비 중지/변경 경계 절차를 따른다. r: 이벤트는 새 소비자 배포와 DB 권한 준비 뒤 발행해야 한다.

## ES

필수/우대 조건과 treatment/category, 원문, evidence atom, 논리 트리를 별도 필드에 넣는다. 중첩 조건 관계는 nested 항목과 비실행 원문 논리 JSON으로 유지한다. 기술 atom은 source evidence를 가진 검색용 terms로 제공하되 자격 충족 확정 필터로 사용하지 않는다. 기존 원문·태그 검색을 유지해 미분류 자료 누락을 막는다. 사용자 역량은 MySQL에 보관하며 이 단계는 사용자별 최종 추천 엔진 완성이 아니다.

## 실행과 질문 적용

수집과 AI는 분리한다. 분류 CLI는 기본 읽기 전용 계획만 출력하고 --live와 ENABLE_LIVE_BEDROCK=true일 때 제한 건수만 실제 호출한다. --apply는 검증된 결과와 이벤트를 저장한다. 자동 대량 호출을 기본값으로 두지 않는다. 모델 실패는 조건 제외로 해석하지 않는다.

질문 선정은 별도 opt-in 설정으로 활성화한다. 저장 분류가 유효할 때 reference만 문답 대상에서 분리하고 원문·이유를 참고사항으로 공개한다. ask/review는 계속 질문한다. 전체 조건과 참고사항을 세션에 보관하며 reference를 met로 만들지 않는다. 분류 없음·오류·오래된 결과는 기존 전체 원문 문답으로 복귀한다. 기존 세션 답변은 새 정책으로 재편집하지 않는다.

## 검증·배포

[AI 질문 선정 평가](AI_QUESTION_SELECTION_EVALUATION.md)의 사람 정답·중요 조건 오생략 평가를 유지한다. 모의 모델·실제 로컬 MySQL·로컬 ES로 계약/원문/버전/재시도/색인/문답을 검증하되 실모델 정확도로 부풀리지 않는다. 운영 전에는 DB 마이그레이션·분류 읽기/쓰기 최소 권한·ES 매핑·소비자·실제 모델 표본 평가를 준비한다. 이번 구현에서 운영 DB와 AWS 설정을 자동 변경하지 않는다.


## 구현 위치와 검증

- 계약·원문 검증: app/backend/src/schemas/condition_review.py, services/condition_review.py.
- AI 호출: app/backend/src/bedrock/condition_classifier.py. 공고당 한 번, 출력 예산 4096토큰. 잘림/잘못된 형식은 실패 처리하며 질문 생략으로 변환하지 않는다.
- 저장: repositories/condition_reviews.py와 database/condition_review_migration.sql. MySQL 실제 권한 시험에서 FOR UPDATE의 쓰기 권한 요구를 확인해 FOR SHARE로 변경했다. 원본 쓰기 권한 없이 원문 변경을 방어한다.
- 제한 배치 분류: app/ingestion/classify_job_conditions.py. 캐시 재사용, 읽기 전용 계획, 소량 실제 호출, 명시적 반영과 진행 커서 지원.
- 검색: search_index/sync_outbox.py, index_snapshot.py, configure_condition_index.py, export_classified_snapshot.py 및 infra/elasticsearch/config/conditions.mapping.json.
- 문답: DialogueFlow의 저장 분류 적용, 참고사항 원문·이유 보존과 프런트 ConditionReferences. 검토 항목은 계속 질문하고 참고 항목은 충족으로 기록하지 않는다.
- 선택적 검색 확장: ENABLE_AI_CONDITION_RANKING=true일 때 보유 기술의 후보 조건에 기존 태그와 분류 terms를 OR로 연결하고 순위를 보강한다. 기존 필터를 분류 필드만으로 대체하지 않는다. 이는 사용자별 최종 추천·적합도 점수·학위/경력 판정 완성이 아니다.

실제 임시 MySQL/Nori ES에서 분류 저장·중복 재사용·조건 변경 무효화·Outbox 권한 실패 시 전체 롤백·ES 반영·AND/OR 보존·미분류 후보 유지·원문 변경 후 구형 분류 필드 제거를 검증했다. 임시 컨테이너와 원본 DB를 분리했으며 운영 DB에는 접근하지 않았다. 유료 Bedrock 호출은 하지 않았다. 사람 정답/실모델 분류 정확도·비용·지연 평가와 운영 스케줄 설치는 남아 있다.

실행 순서·권한·설정·복구 주의사항: [조건 분류 운영 준비](AI_CONDITION_RUNBOOK.md).


## 로컬 검증 기록

- MySQL/Nori ES를 함께 켠 전체 실행: 414건 중 412건 통과, 기존 외부 환경 조건 2건 건너뜀.
- 마지막 발췌 검색어의 공백/허위값 거부 검증 추가 후 기본 실행: 415건 중 393건 통과, DB/ES 통합 등 환경 조건 22건 건너뜀. 앞선 실제 통합 검증을 대체하거나 실모델 정확도 결과로 해석하지 않는다.
- 프런트엔드 36건 통과, production build 성공.
- 조건 분류 코드 묶음 생성 확인: 비밀 설정/데이터/AWS 작업 없이 코드·DDL·매핑·해시만 생성.
- 이번 검증용 MySQL 13339·ES 19301 컨테이너는 ID/라벨/포트 대조 후 종료했다. 기존 개발 DB 3308은 유지했다.
- 최초 설계, 분류 코어, 검색·문답 연결을 나누어 커밋·푸시했다. 운영 마이그레이션·권한 부여·실제 AI 분류·운영 소비자/웹 배포는 아직 실행하지 않았다.
