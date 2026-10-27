# 작업 시작

- [현재 설계](docs/README.md): 상단 설계 문서 8개.
- [DB 구조](workspace/database/mysql/README.md): 데이터 없는 MySQL 스키마 9개 테이블.
- [대화·캐시 계약](workspace/database/mysql/CONVERSATION_STORAGE.md).
- [수집 코드·데이터](workspace/api추출테스트/).
- [추가 결정 사항](DECISIONS.md).
- [사용하지 않는 이전 자료](retired/README.md).

archive는 변경 전 문서와 복구용 스냅샷이다. retired는 현재 작업에서 분리한 자료다. 현재 구현과 목표 설계는 docs에서 구분한다.

## 구현 코드

- [백엔드 실행 안내](app/backend/README.md)
- [오프라인 정제](app/ingestion/README.md)
- [React 영역](app/frontend/README.md)
- [AWS 배포 준비](infra/README.md)

로컬 검증은 Docker나 AWS 자격증명 없이 가능하다. 실제 Bedrock 호출은 기본 비활성이다.

- [MySQL 대화 실행](app/backend/DIALOGUE_LOCAL.md): 34개 테스트 통과, 직접 실행할 로컬 데모·API 안내.

- [React 화면 실행](app/frontend/README.md): 터미널 두 개로 API와 화면을 실행한다. 로컬 UI 빌드·프록시·인증 차단 검증 완료.

- 백엔드 자동 반영: app/backend에서 python dev.py. 기존 local_server.py 실행은 처음 한 번 종료한다. React는 npm run dev를 유지한다.


## AWS 배포 다음 단계

배포와 사용량·S3·DB 점검은 [infra/README.md](infra/README.md)를 따른다. 현재는 배포 파일 준비 단계이며 AWS 리소스는 아직 생성하지 않았다. 사용자 CMD에서 `python infra\deploy.py preflight`를 먼저 실행한다. 이후 로컬 build → 비용 알림 기준 결정 → plan/review → apply → initialize → inspect → publish 순서다. 비밀값은 채팅에 붙여넣지 않는다.


## 현재 우선 실행 경로: 웹 호스팅만

비용 검토 후 웹 주소부터 확보하기로 변경했다. 전체 deploy.py apply 대신 [호스팅 안내](infra/HOSTING.md)를 따라 hosting.py plan/review/apply/status/publish 순서로 진행한다. 이 단계는 S3·CloudFront만 생성하고 DB/Bedrock 연결은 후속이다.


## 현재 백엔드 실행 경로 보완

웹 호스팅 완료 후 저비용 백엔드 연결을 준비했다. 현재 우선안은 서울 t4g.small 단일 서버의 MySQL+Python 작업 코드와 Lambda/HTTP API/SQS/임시 DynamoDB 작업 상태이며 RDS/유료 VPC 엔드포인트는 사용하지 않는다. Elasticsearch는 아직 미포함이다. 기존 전체 배포 대신 infra/BACKEND.md의 backend.py를 따른다. 단일 서버/수동 운영의 한계가 있으며 월 6만 원은 목표이지 비용 상한 보장이 아니다. 실제 서버·DB·Bedrock 연결은 사용자 실행 후 검증해야 한다.
