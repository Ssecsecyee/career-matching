# 동료 MCP 에이전트에게 입력할 프롬프트

아래 내용을 복사하고 PC 경로 두 곳을 실제 값으로 바꿉니다. 비밀번호·AWS 키·대화 내용은 프롬프트에 붙이지 않습니다.

---

해!듀케 현재 서비스를 내 AWS 계정에 복제 배포하고 싶다. Git main을 clone/pull한 저장소는 `C:\career-matching`, 비공개 전체 데이터 묶음은 `C:\educare-transfer\educare-full-data.tar.gz`, 별도 SHA256 영수증은 같은 폴더의 `.receipt.json`이다. 새 계정 정보는 저장소의 `.env.migration`에 내가 입력한다. 실제 값은 화면·로그·문서·Git에 출력하지 말고 읽어서 사용하라.

먼저 AGENTS.md, docs/CURRENT_STATUS.md, docs/AWS_MIGRATION_HANDOFF.md, infra/migration/를 읽어라. 문서 과거 시점과 실제 구현을 구분하라. 새 계정에서 비용을 발생시키기 전 월 80달러 계획 예산을 기준으로 구성·예상 비용을 보여주고 생성 승인을 받아라. 이 금액은 자동 상한이 아니며 Bedrock 사용량이 늘면 초과할 수 있다.

1. 현재 Git 커밋·미커밋 변경을 확인하고 기존 파일을 덮어쓰지 마라. 데이터는 exports/ 등 Git 제외 경로에 두고 백업 SHA256과 압축 내부 manifest의 모든 파일·행 수를 검증하라. SQL과 JSONL 두 버전은 중복 삽입하지 마라.
2. 내 AWS 프로필의 STS 계정 ID가 AWS_EXPECTED_ACCOUNT_ID와 일치하고 기존 교육 계정과 다른지 확인하라. 새 Bedrock 모델 접근·권한·한도를 확인하되 대량 호출을 하지 마라. 키를 복사하는 대신 새 IAM 역할·Secrets를 구성하라.
3. 기존 기능은 React S3/CloudFront, HTTP API/Lambda, SQS, EC2 worker+MySQL+Elasticsearch+로컬 임베딩, 임시 결과 DynamoDB다. AgentCore·RDS·관리형 OpenSearch·불필요한 팀 자원은 만들지 마라. DB와 ES는 인터넷에 공개하지 말고 EC2 루프백으로 유지하라.
4. 구형 infra/deploy.py apply와 예전 seed를 적재하는 bootstrap을 그대로 실행하지 마라. 실제 코드·신규 전체 덤프를 기준으로 새 빈 DB용 배포 계획을 만들어라. 리전·ARN·계정 하드코딩을 새 환경 설정으로 분리하고 기존 운영 환경은 변경하지 마라.
5. 새 빈 MySQL DB에 portable_data.py restore-mysql로 전체 데이터를 복원하라. 기존 테이블이 있으면 중단하라. 타입·행 수·외래키·원문/버전/해시·세션/문답을 검증하고 운영 사용자에는 최소 권한을 부여하라.
6. Elasticsearch 플러그인·동의어·매핑·별칭을 준비하고 MySQL에서 전체 초기 색인 및 Outbox 동기화를 구성하라. infra/migration/runtime/terminology의 승인 사전·출처·라이선스를 검토하고 실제 분석기에 연결하라. 데이터가 들어있지 않은 Outbox만 돌려서 복원이 끝났다고 판단하지 마라.
7. Git에 있는 pinned ONNX 모델 도구로 로컬 임베딩을 재구성하고, worker가 호출하는 /opt/career/vector-pilot-20261114 경로와 인덱스 계약을 맞춰라. CPU·메모리·운영 영향부터 검토하고 유료 임베딩 대량 호출로 대체하지 마라.
8. `.env.migration`의 새 리소스 출력값으로 worker/Lambda/CloudFront를 연결하라. 프론트엔드는 상대 /api 경로와 새 CloudFront 원점 연결을 확인하라. AWS 키·DB 비밀번호가 웹 빌드에 들어가면 중단하라.
9. 검색·필수/우대 문답·상담 재개·역량 기반 재추천·TXT/0건 벡터·스크랩·모바일·권한·비용 제한을 모의/통합 검증하라. 실제 Bedrock 소량 호출은 별도로 승인받아라. 동작하지 않는 기능을 완료라고 쓰지 마라.
10. 공개 전 최종 증분 데이터·신규/수정/마감 공고 동기화와 되돌리기 계획을 확인하라. 새 URL·QR 교체 정보를 정리하고 실행한 단계/미완료/검증 결과를 docs에 남겨라. 데이터와 .env는 커밋하지 마라.

리소스 생성·운영 복원은 위 단계별 검증과 내 승인을 거쳐 진행하되, 코드 읽기·파일 검증·로컬 테스트·설정 초안 작성은 먼저 수행하라. 기존 교육 계정 리소스를 삭제하지 마라.

---
