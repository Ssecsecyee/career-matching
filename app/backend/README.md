# Lambda 백엔드 시작점

Python 3.11 이상. 기본 로컬 검증은 표준 라이브러리만 사용하며 AWS 자격증명이나 Docker가 필요 없다.

```powershell
cd C:\AWS_project\career_matching\app\backend
python -m unittest discover -s tests -v
python local.py
```

local.py는 Lambda 이벤트를 직접 전달한다. HTTP 서버는 띄우지 않는다. LOCAL_JOBS_JSON 미설정이면 data_not_configured를 반환한다. 운영 모집 상태를 검증한 정규화 JSON을 지정해야 검색 결과가 나온다. 임의 공고는 제공하지 않는다.

## 구현 상태

- handlers/: /health와 로컬 /chat 요청 검증·라우팅. AWS 환경 /chat은 미구현 저장·인증 때문에 차단.
- schemas/: 허용된 검색 조건과 범위 검증. 임의 SQL/DSL 실행 없음.
- repositories/: JSON 기반 로컬 검색과 DB 어댑터 인터페이스.
- services/: 후보 요약·입력 길이 보호, 개인화 캐시 키 생성. 실제 캐시 저장/조회는 미구현.
- bedrock/: 명시적 opt-in Converse 검색 계획 호출, 토큰·지연 메타데이터 반환. DB 호출 기록 저장은 미구현.

## 실제 Bedrock 연결 준비

requirements.txt 의존성을 설치한 뒤 프로세스 환경에 ENABLE_LIVE_BEDROCK=true, BEDROCK_MODEL_ID, BEDROCK_REGION을 명시한다. 기본은 꺼져 있다. 모델/추론 프로필·리전·지원 여부는 실제 계정에서 확인해야 한다. 자동 로그인이나 모델 선택을 하지 않는다. 백엔드 폴더 .env를 로컬 요청 시작 시 읽는다. Lambda에서는 로컬 파일을 읽지 않고 실행 역할과 배포 환경변수를 사용한다. 로컬은 표준 AWS 자격증명 체계, 배포는 실행 역할을 사용한다. API 키를 코드에 넣지 않는다.

실제 호출은 비용이 발생한다. 이번 검증은 가짜 주입 클라이언트만 사용한다. SDK 재시도는 제한되며 서비스 내 추가 재시도는 없다. 모델 오류·권한·타임아웃의 운영 응답 매핑, 실패 호출 영구 기록, 실제 입력 토큰 계산과 세션 예산은 후속 구현이다. 현재 문자 수 예산은 토큰 수가 아니다.

## 다음 연결

확정 DB 어댑터 → 세션/질문 상태 머신 → 자격요건·우대사항 판단 → 근거·호출 기록 저장 → 캐시 TTL/무효화 → 교육 검색 → API 인증 → AWS 배포. 프론트엔드·DB·실제 모델이 연결된 완성 서비스라고 해석하지 않는다.

## 전체 공고 파일의 로컬 검색 검증 (CMD)

정제 결과의 unknown 상태를 유지하면서 로컬 연결 검증에만 포함할 수 있다. 기본은 제외한다. closed와 unavailable은 이 옵션에서도 제외된다. 실제 모집 중이라고 표시하거나 운영 응답에 사용하지 않는다.

```cmd
set "LOCAL_JOBS_JSON=C:\AWS_project\career_matching\app\backend\local-data\jumpit_all_v2\jobs.normalized.json"
set "LOCAL_INCLUDE_UNVERIFIED=true"
set "ENABLE_LIVE_BEDROCK=false"
python local.py
```

응답에는 includes_unverified_snapshots와 공고별 recruitment_status가 표시된다. 검증 후 set "LOCAL_INCLUDE_UNVERIFIED=false"로 되돌린다. 새 테스트를 포함하면 unittest 총 13개가 예상되지만 이번 수정 후 에이전트가 실행하지 않았으므로 직접 결과를 확인한다.


## 로컬 환경 파일

로컬 실행 설정은 C:\AWS_project\career_matching\app\backend\.env이다. 루트 .env는 자동으로 읽지 않는다. AWS_REGION→BEDROCK_REGION, MODEL_ID→BEDROCK_MODEL_ID, BEDROCK_MOCK=0→ENABLE_LIVE_BEDROCK=true로 연결한다. 기존 CMD 프로세스 변수는 .env보다 우선한다. 대화와 연결 점검은 MODEL_ID의 Sonnet만 사용한다. EMBED_MODEL_ID는 보관만 하며 아직 별도 호출에 연결하지 않았다. AWS_PROFILE은 표준 SDK 프로필 선택에 사용한다. 프로필 이름을 적는 것만으로 로그인되지는 않는다.

BEDROCK_MOCK=0은 실제 호출 허용 설정이므로 요청에 따라 비용이 발생할 수 있다. local.py는 명시적 search_plan으로 검색하므로 이 모의 실행 자체는 모델을 호출하지 않는다. .env와 AWS_PROFILE은 Lambda 패키지·브라우저·로그에 포함하지 않는다. 지정 모델/프로필의 계정 접근 가능 여부는 사용자 CLI 결과로 확인해야 한다.


## MySQL 대화 API 추가

새 구현과 실행 순서는 [DIALOGUE_LOCAL.md](DIALOGUE_LOCAL.md)를 따른다. 기존 스캐폴드 handler와 새 dialogue handler를 구분한다. 34개 테스트 중 실제 MySQL 통합 5개가 통과했고, 이번 검증에서 실제 Bedrock 호출과 AWS 배포는 하지 않았다.

## 개발 서버 자동 리로드

현재 실행 중인 기존 서버를 Ctrl+C로 한 번 종료한 뒤 python dev.py로 실행한다. src/**/*.py, local_server.py, backend/.env 변경을 감지해 약 1초 내 API 프로세스를 재시작한다. .env는 새 자식 프로세스에서 읽어 변경값을 적용하며 CMD의 명시적 환경변수는 계속 우선한다. DB 데이터·SQL·tests·캐시 파일 변경은 자동 마이그레이션/재적재하지 않는다. React는 npm run dev의 HMR을 유지한다. 종료 시 watcher와 자식 API를 함께 정리한다. 별도 임시 서버에서 코드/.env 재시작·자식 종료를 검증했고 실제 모델 호출은 없었다.
