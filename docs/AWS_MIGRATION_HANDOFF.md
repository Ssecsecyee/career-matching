# 해!듀케: 다른 PC·AWS 계정으로 이식

작성일: 2026-11-21. 현재 AWS MySQL `career_matching` 전체를 압축 JSONL과 SQL로 인계하고, Git 코드와 MCP 에이전트로 새 계정 복원을 진행하기 위한 절차다. 실제 데이터는 Git에 넣지 않는다. 이번 변경은 이식 도구와 인계 문서이며 새 AWS 배포 완료를 의미하지 않는다.

## 인계물

1. Git 저장소의 코드, `infra/migration/` 도구, 이 문서와 `MCP_MIGRATION_PROMPT.md`.
2. 별도로 전달하는 `educare-full-data.tar.gz`와 `.receipt.json` 파일. 공고·교육뿐 아니라 사용자 대화·문답·호출 기록이 들어 있으므로 비공개 경로로 전달한다. 일반 S3 웹 버킷·공개 Drive·Git에 올리지 않는다.
3. 동료 PC에만 만드는 `.env`. AWS 인증은 동료의 프로필/SSO를 사용하고 개인 액세스 키를 채팅·프론트엔드·Git에 넣지 않는다.

압축본 구조:

```text
<추출시각>/
  manifest.json                 # 행 수, 컬럼 타입, 파일 SHA256
  mysql/<테이블>.jsonl.gz        # 한 줄에 한 행, 컬럼 순서는 manifest 참조
  mysql/<테이블>.sql             # 운영 SHOW CREATE TABLE 결과
  mysql/full.mysql.sql.gz       # 별도의 일관 스냅샷으로 만든 네이티브 SQL 덤프
```

JSONL은 UTF-8이며 NULL·정수·소수·바이너리·날짜 타입을 보존한다. JSON 타입 컬럼의 원래 문자열도 보존한다. 단순 배열 JSON이나 CSV로 임의 변환하여 가져오지 않는다. JSONL과 네이티브 SQL은 별개의 스냅샷이므로 하나를 복원 기준으로 선택하고 양쪽을 중복 삽입하지 않는다.

## 동료 PC에서 시작

예시 보관 위치: `C:\educare-transfer\educare-full-data.tar.gz`. 다른 경로를 쓰면 `.env`와 실행 인수를 함께 바꾼다.

```powershell
git clone https://github.com/Ssecsecyee/career-matching.git
cd career-matching
git switch main
python -m venv .venv-migration
.\.venv-migration\Scripts\python.exe -m pip install -r infra/migration/requirements.txt
Copy-Item infra/migration/.env.example .env.migration
```

`.env.migration`에 새 AWS 프로필·계정 ID·리전, 데이터 파일 경로와 별도 전달된 SHA256을 입력한다. 아직 생성하지 않은 버킷·큐·테이블·Secret ARN에는 기존 계정 값을 복사하지 않는다. 새 계정에서 리소스를 만든 뒤 실제 출력값으로 채운다. `.env` 하나가 AWS 리소스나 모델 파일을 생성하는 것은 아니다.

```powershell
aws sso login --profile <동료의 실제 SSO 프로필>
.\.venv-migration\Scripts\python.exe infra/migration/handoff.py doctor --env .env.migration
.\.venv-migration\Scripts\python.exe infra/migration/handoff.py unpack --archive C:\educare-transfer\educare-full-data.tar.gz --sha256 <receipt에 적힌 SHA256> --directory exports\restored-input
```

`unpack`가 출력한 `<실제 데이터 폴더>`를 다음 복원 명령에 사용한다. 무결성이 다르면 중단한다. doctor는 계정 신원만 검사하며 인프라 준비 완료를 뜻하지 않는다.

## 새 서버 구성

현재 구조: React → S3/CloudFront → HTTP API/Lambda → SQS → EC2 worker. DynamoDB는 임시 작업 결과, MySQL은 원문·대화·문답, EC2 내부 Elasticsearch는 일반·벡터 검색이다. EC2 t4g.medium, 암호화 gp3 및 DB/ES의 루프백 전용 포트 정책을 유지한다. AgentCore·RDS·관리형 OpenSearch·다른 팀 자원은 이번 복제 대상이 아니다.

월 80달러는 현재 수준 사용량의 계획 예산이며 비용 상한/자동 중지 기준이 아니다. 새 계정의 유료 자원 생성은 별도의 배포 계획과 동료의 승인을 받은 뒤 실행한다. 개인 계정 Bedrock 모델 접근·할당량도 먼저 확인한다.

주의: `infra/backend.py`의 초기 bootstrap은 예전 seed와 t4g.small/MySQL 중심 구성이다. `infra/deploy.py apply`는 예전 RDS 경로다. 그대로 실행하면 현재 전체 구성이 복제되지 않는다. MCP 에이전트는 이번 백업·기존 구성 코드를 근거로 빈 DB를 만드는 이식 계획을 작성하고, 구형 seed 자동 적재/worker 자동 기동을 피해야 한다. 본 도구는 새 계정을 자동 생성하거나 모든 서비스의 IaC를 새로 작성한 것이 아니다.

## MySQL 복원

새 서버에 MySQL 8.4 계열과 빈 `career_matching` DB를 준비한다. DB 생성·새 관리자 계정 설정은 담당자가 수행한다. 운영 사용자 `career_runtime` 비밀번호는 새 계정 Secrets Manager 값으로 발급하고 필요한 테이블 권한을 적용한다. 기존 계정의 MySQL 시스템 DB/사용자 비밀번호는 데이터 묶음에 포함하지 않는다.

새 서버에서 `.env.migration`의 MYSQL 값은 **복원 대상**을 가리켜야 한다. AWS_PROFILE은 EC2 역할 환경에서 필요 없다. 같은 로컬 Python 환경을 마련한 뒤:

```bash
python infra/migration/portable_data.py verify --directory <실제 데이터 폴더>
python infra/migration/portable_data.py restore-mysql --directory <실제 데이터 폴더> --env .env.migration --confirm-empty-target
```

복원 도구는 기존 테이블이 있으면 중단한다. 임의 DROP/덮어쓰기를 지원하지 않는다. 행 수와 외래키 참조를 검증한다. 실패하면 DDL은 남을 수 있으므로 동일 DB에 무작정 재실행하지 말고 새 빈 테스트 DB로 다시 진행한다. DB 밖 접속에는 검증 가능한 TLS CA가 필요하다.

네이티브 `full.mysql.sql.gz`는 표준 MySQL 덤프 도구로 가져올 수 있는 별도 대안이다. 사용하기 전에 빈 대상인지 확인하고 기존 운영 DB에는 실행하지 않는다. JSONL 복원과 중복 실행하지 않는다. 이 도구를 만든 시점에 실제 새 계정 복원 훈련까지 완료됐다는 뜻은 아니다.

## 검색·벡터와 최신성

- 이번 인계의 기준은 MySQL 전체 원문이다. 검색 노출 대상 수와 전체 DB 수를 구분한다.
- Elasticsearch는 `infra/elasticsearch/Dockerfile`의 기존 버전과 nori 등 플러그인을 확인해 설치한다. 현재 파일 기준 Elasticsearch 9.5.5를 사용하나 실제 서버 버전·이미지 digest는 최종 배포 전 대조한다.
- `app/ingestion/search_index`의 기존 outbox 소비자·인덱스 매핑·별칭으로 DB 기준 재색인한다. 단순히 Outbox 대기 0건이라고 색인 복원이 끝난 것으로 보지 말고 전체 초기 색인이 필요하다.
- 기존 로컬 승인 표기 사전·출처·라이선스는 infra/migration/runtime/terminology/에 인계했다. 실제 ES의 synonym set 이름·분석기 연결과 대조하여 적용한다. 새 도구는 ES 설정·문서 내보내기/복원도 지원하지만 이번 SQL 인계만으로 ES 전체가 자동 복원되지는 않는다.
- 벡터 파일은 MySQL에 없으므로 별도 복원 또는 원문에서 재생성한다. 모델 계약은 `app/ingestion/search_index/section_vectors/`의 pinned revision/int8/CLS/L2/768차원/2,048토큰을 유지한다. 로컬 CPU 임베딩 재생성은 Bedrock 유료 임베딩 대량 호출과 구분한다.
- 실제 worker는 `/opt/career/vector-pilot-20261114/venv/bin/python`과 `txt_query.py`를 호출한다. Git의 벡터 도구를 이 경로로 설치하고 `model` 디렉터리와 `career-job-vectors-pilot-20261114-full` 인덱스를 준비한다. 경로만 .env에 넣어도 해결된다고 가정하지 않는다.
- 벡터 시험 통과 전 `ENABLE_TXT_VECTOR_SEARCH`, `ENABLE_ZERO_RESULT_VECTOR_FALLBACK`을 true로 켜지 않는다.
- `handoff.py render-config --env .env.migration --output exports/runtime-config.json`은 비밀값 없는 설정 초안을 만든다. 동료가 실제 설치된 동의어·벡터·인덱스 상태에 맞춰 검토한 뒤 `/opt/career/config.json`에 적용한다.

## 최종 검증 후 공개

공고·교육 전체 행 수와 원문/버전/해시, 필수·우대 문답 저장·정정, 상담 후 우대 재개, 역량 기반 재추천, 지역·신입·동의어 검색, TXT·0건 벡터 경로, 모바일, 소유권 검사·제한·오류 응답·Outbox를 확인한다. 신규 URL은 기존 교육 계정 CloudFront 주소와 다르므로 QR/안내 링크를 바꾼다. 쓰기 중지/최종 증분 동기화 계획 없이 오래된 덤프만 공개해 최신 운영 DB와 같다고 설명하지 않는다.

## 압축본 업로드가 필요할 때만

PC → 새 AWS 전송은 SSM 터널/SCP 등 승인된 비공개 경로를 사용한다. 선택적으로 새 계정의 전용 버킷에 올릴 경우 `.env.migration`의 MIGRATION_BUCKET은 웹 버킷과 달라야 하고 `Purpose=private-migration` 태그와 모든 공개 차단 설정이 필요하다.

```powershell
python infra/migration/handoff.py upload --env .env.migration --archive C:\educare-transfer\educare-full-data.tar.gz --sha256 <SHA256> --confirm-private-upload
```

이 명령은 기존 전용 버킷에만 업로드하며 버킷을 새로 만들지 않는다. 사용자 대화·민감 데이터가 있으므로 전달 대상과 보존기간을 정하고 인계 후 불필요한 중간본을 정리한다.

추출 완료 수치·파일 해시와 검증 범위는 [2026-11-21 전체 추출 기록](MIGRATION_EXPORT_20261121.md)을 확인한다.
