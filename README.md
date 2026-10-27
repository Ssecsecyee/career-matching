# Career Matching

Amazon Bedrock 기반 대화형 채용·교육 매칭 프로젝트입니다.

## 현재 구현
React 웹, 채용공고 검색, Sonnet 기반 조건 확인 질문, MySQL 대화·근거·사용량 저장.
교육 데이터 연결과 교육 매칭, 검색엔진 도입은 후속 작업입니다.

## 구조
- `app/frontend`: React/Vite 웹
- `app/backend`: Python API, 작업 서버, 테스트, `database/schema.sql`
- `app/ingestion`: 원본 정제 및 MySQL 데이터 변환
- `infra`: AWS 배포 도구와 가이드
- `docs`: 기획·설계·운영 문서

## 실행과 배포
[시작 안내](START_HERE.md), [백엔드](app/backend/README.md), [AWS 백엔드](infra/BACKEND.md), [웹 호스팅](infra/HOSTING.md)를 참고하세요.
배포 시 AWS 비용이 발생합니다. 문서의 계정·프로필·경로는 자신의 환경에 맞게 설정해야 합니다.

## 데이터와 설정
실제 수집 원본, 정제 데이터, 사용자 대화, DB 백업, `.env`, 인증 파일은 저장소에 포함하지 않습니다.
`workspace/`는 로컬 자료 폴더이며 원본 수집은 `--data-root`로 경로를 지정할 수 있습니다.
배포 빌드에는 별도로 준비한 `app/backend/local-data/jumpit_all_v3/jobs.normalized.json`과 `jobs.data.sql`이 필요합니다.
DB 구조는 `app/backend/database/schema.sql`에 포함돼 있습니다. 실제 공고 데이터의 배포·재공개 권한을 보장하지 않습니다.
환경 설정은 `.env.example`을 참고하되 실제 인증정보는 로컬 또는 AWS Secrets Manager에 보관하세요.

## 오프라인 검증
```cmd
cd app\backend
python -m unittest discover -s tests -v
```
MySQL 통합 테스트는 별도 격리 DB 설정이 필요합니다. 기본 테스트는 실제 모델을 호출하지 않습니다.
