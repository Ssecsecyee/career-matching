# MySQL 대화 API 로컬 검증

2026-10-28. 실제 임시 MySQL에서 34개 테스트(실제 DB 통합 5개 포함)를 통과했다. 모델 응답은 주입된 검증용 응답이며 이 작업에서 실제 Bedrock을 호출하지 않았다.

## 현재 구현

- 새 진입점: src.handlers.dialogue.lambda_handler. 기존 src.handlers.chat은 이전 스캐폴드 경로이며 운영 차단을 유지한다.
- action=search: 자연어를 제한된 검색 계획으로 변환하거나 명시적 search_plan 사용.
- action=select: 세션 후보 중 공고 하나 선택, 자격요건 질문 생성.
- action=answer: met/unmet/unknown을 사용자 진술로 저장. 필수 미충족은 gap_guidance, 미확인은 질문 유지, 충족 후 우대조건 확인.
- 원문 목록 항목별로 질문한다. AND/OR 및 이어지는 하위 설명은 보존한다. 의미상 모든 조건의 자동 분해·충족 판정·합격 평가가 아니다.
- MySQL: 세션·대화·당시 원문 버전·사용자 진술·판정 근거·모델 호출 메타데이터 저장.
- 캐시는 동일 요청의 응답 재전송용이다. 사용자·세션·요청 ID·내용 지문을 검증하며 새 요청에 과거 답변을 의미 캐시로 재사용하지 않는다.
- 테스트용 공유 Bearer 토큰과 클라이언트별 무작위 토큰으로 세션을 격리한다. 정식 계정 로그인은 아직 아니다.

## CMD 실행 순서

```cmd
conda activate AWS_project
cd /d C:\AWS_project\career_matching\app\backend
python -m pip install -r requirements.txt
python prepare_local_mysql.py
docker compose -f compose.dev.yaml up -d --wait --wait-timeout 180
python dialogue_demo.py --live
```

prepare_local_mysql.py는 기존 AWS 모델·프로필·API 키 설정을 유지하고 로컬 MySQL 자격증명과 테스트 API 토큰 중 누락된 값만 추가한다. 비밀값을 출력하지 않는다. 로컬 테스트 기본 보존은 24시간, 응답 재전송 캐시는 최대 10분이다. 배포 전 보존 정책을 확정한다. 이 값들은 로컬 검증 설정이지 운영 정책 확정이 아니다.

MySQL은 127.0.0.1:3308에만 연결하며 기존 PostgreSQL과 별개다. 전용 영구 Docker 볼륨을 사용한다. 초기화 SQL은 새 볼륨에서 처음 시작할 때만 실행된다. 기존 볼륨이 있다면 임의 삭제하지 말고 상태를 확인한다. 개발 사용자는 Docker 초기화가 생성한 계정이며 운영 배포 전에 DDL 없는 최소 권한 사용자로 제한한다.

대화 예: '서울에서 Python을 사용하는 개발 공고 3개 찾아줘' → 공고 번호 선택 → 자격요건 원문과 질문 확인 → 1 충족 / 2 미충족 / 3 모름 → 우대조건 확인. 결과가 없으면 지역·직무 조건을 줄인다. 검색은 저장 스냅샷이며 모집 상태 미확인 표시를 유지한다. Bedrock 실제 호출 시 비용이 발생하며 실패 시 오류 유형과 DB 이력을 확인한다.

## HTTP API

python local_server.py로 127.0.0.1:8020에 서버를 띄울 수 있다. GET /health, POST /chat을 제공한다. 인증 헤더는 Authorization: Bearer <CHAT_API_TOKEN>, X-Client-Token: <클라이언트가 생성한 32~128자 임의 토큰>이다. 토큰을 URL에 넣거나 로그로 출력하지 않는다.

요청 공통: action, request_id(UUID), 두 번째 요청부터 session_id(UUID).

- search: message 또는 search_plan, 선택 profile.
- select: source_id.
- answer: question_id, assessment(met/unmet/unknown), 선택 detail.

모델 호출은 DB 트랜잭션 밖에서 실행한다. 세션별 요청 임대 잠금은 90초, 세션별 모델 호출 예산은 12회다. 같은 요청이 완료된 후 재전송되면 원래 응답을 반환하고 모델을 다시 호출하지 않는다. 모델 실패 후 사용자가 재시도할 때는 새 request_id를 사용한다. SDK 내부 재시도는 한 호출 기록에 포함되며 HTTP 시도별로 분리하지 않는다.

## 보존·정리

만료 데이터는 조회에서 제외한다. MySQL에서 자동 삭제되지는 않는다. python cleanup_chat.py는 만료 건수만 조회하고, --apply를 붙이면 호출당 테이블별 최대 1000건을 삭제한다. 공고·교육 데이터는 삭제하지 않는다. 운영에서는 별도 스케줄과 보존·삭제 정책을 구성해야 한다.

## 남은 범위

- React 화면과 API 연결.
- 실제 Bedrock 추가 질문의 사용자 검증.
- AWS 비공개 MySQL 네트워크·DB 작업 Lambda 분리 또는 연결 경로 구성.
- 운영 인증·최소 DB 권한·비밀관리·CORS·로그와 예산.
- 교육 데이터 확보·적재·연결, Elasticsearch, 정기 웹 동기화.

현재 로컬 구현을 AWS 배포 완료로 표현하지 않는다.

## Bedrock 일시 오류 처리 보완

ServiceUnavailableException 등은 retryable과 재시도 안내를 반환하고 세션 ID를 유지한다. CLI는 사용자가 y를 입력하면 10초 후 새 request_id로 최대 2회 추가 시도한다. 자동 모델 전환은 없다. 검색 계획 호출을 생략하려면 python dialogue_demo.py --live --skills MySQL을 사용한다. 이는 DB 검색을 직접 수행하지만 공고 선택 후 질문 생성은 실제 Bedrock을 호출한다. 원문·세션 저장 로직은 유지한다. 이번 오류 수정 검증은 모델을 실제 호출하지 않았다.


## 2026-10-28 대화 기억과 항목별 질문
- Sonnet만 사용한다. 질문과 근거 있는 사용자 정보 정리를 한 호출에서 수행한다. 질문 출력 상한 1,024토큰, 기존 세션 호출 한도 12회는 유지한다.
- chat_sessions.profile_snapshot.memory에 사용자 발언·주제별 사실·명시적으로 확인한 조건을 저장한다. requirement_answers에 질문 순서와 항목별 답변을 저장한다. 기존 JSON 칼럼을 사용하며 스키마 이관은 없다.
- 최초 메시지와 profile.user_statement를 기록한다. 다음 질문에는 최근 사용자 발언 최대 6개/6,000자, 사용자 정보 최근 16개, 조건 답변 최근 4개를 전달한다. 개별 원문 조건 최대 18,000자, 메모리 JSON 최대 24,000자를 검증한다. 전체 원본 대화는 기존 chat_messages에 남긴다.
- 사용자 정보는 category/subject/quote/statement_id로 구성한다. 모델이 돌려준 quote가 실제 사용자 발언에 존재하는지 검증한다. 희망 기술을 보유 기술로 간주하거나 MySQL 사용만으로 최적화 능력을 추론하지 않는다. 의미 정확성은 실제 호출로 별도 검증해야 한다.
- 기존 search/select/answer 외 action=remember를 추가한다. session_id/request_id/message(최대 2,000자)가 필요하다. 명시적인 경험 정정 시 파생 사용자 정보와 기존 조건 확인 결과를 무효화하고 선택한 공고의 첫 항목부터 다시 확인한다. 원래 기록은 보존한다.
- 동일 세션에서 search 시 기억을 유지한다. 새로운 세션은 기억을 공유하지 않는다. 같은 공고·버전·동일 원문 조건에서 met/unmet으로 직접 답한 항목만 재질문을 생략한다. 다른 회사의 유사 조건이나 변경된 공고로 답변을 전이하지 않는다.
- unknown은 미확인으로 저장하고 다음 항목으로 넘어간다. 모든 필수 항목 다음 우대 항목을 확인한다. 필수 미충족은 최종 gap_guidance에 반영하고 미확인 개수도 별도 표시한다.
- 프론트의 기억한 경험 수정 버튼으로 정정할 수 있다. 현재 기억 요약과 진행률을 보여준다. 새 대화는 새 기억으로 시작하고, 페이지 새로고침 후 기존 세션 자동 재개·사용자 계정 간 장기 기억은 아직 제공하지 않는다.
- 응답 재전송 캐시를 유지한다. Bedrock 프롬프트 캐시와 의미 응답 캐시는 새로 활성화하지 않았다.
