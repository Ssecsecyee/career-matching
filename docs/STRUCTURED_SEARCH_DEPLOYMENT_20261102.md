# 복합 검색·검색 확인 흐름 AWS 배포 결과

> Git 기록(2026-11-02): 배포된 구현 코드와 테스트를 `4f2e0dbca27e0707945df60dc61986c03a42b83d`로 커밋했다. 배포 ZIP의 src 파일과 현재 구현 소스의 바이트 일치를 확인했다. 원격 푸시 결과는 이번 작업 완료 보고에서 확인한다.

기준일: 2026-11-02. 배포 릴리스: `20261102T023141Z`. 상태: **AWS 백엔드·웹 반영 및 소량 실제 요청 검증 완료**.

## 반영 범위

- 기존 Lambda Python 3.11 x86_64 API 코드와 Linux용 Pydantic 의존성 반영.
- 기존 EC2 ARM worker의 Pydantic 설치·import 검사, 코드 교체와 서비스 재시작 성공.
- 새 검색 스키마, 지역/직무 OR와 보유/필수 기술 분리, 검색 설명 → 확인 → 공고 표시 반영.
- 검색 계획/확인 기록을 기존 MySQL JSON 컬럼과 응답 캐시에 저장. 테이블 생성·원본 공고 데이터 수정·새 인프라 생성 없음.
- 기존 S3/CloudFront 웹 publish와 캐시 무효화 요청. 실제 서비스에서 `index-DTes7qzS.js` 및 확인 흐름 포함 확인.

## 실제 검증

사용자가 제공한 ‘컴퓨터공학 전공, Python/C/C++/FFI 파이프라인 경험, AWS/EC2, 부산이나 경남, 백엔드/데이터 엔지니어링, 신입~주니어’ 문장을 실제 Sonnet으로 한 번 실행했다.

| 항목 | 확인 결과 |
|---|---|
| 검색 backend | Elasticsearch, MySQL 복귀 아님 |
| 지역/직무 처리 | 부산 OR 경남, 백엔드/데이터 관련 직무 대안 적용 |
| 기술 처리 | 경험 기술을 전부 필수 AND로 제한하지 않음 |
| 검색 결과 | 검증 시점 후보 10건 |
| 확인 전 | search_review, 카드 미표시 |
| 확인 후 | 같은 search_id로 choose_job, 상위 5건 표시 |
| 모델 호출 | 정확히 1회, 확인 시 추가 호출 없음 |
| 사용량 | 입력 3823 / 출력 116 토큰 |
| MySQL | 해당 세션의 검색 설명·확인 응답 2개에 검색 기록 보존, confirmed_at 확인 |
| worker | active |

테스트 요청은 운영 서비스의 대화·사용량 기록에 남았다. 추가 실제 모델 호출은 하지 않았다. 10건은 당시 검색 조건으로 확인한 저장 후보 수이며 현재 모집·신입 지원 자격 충족을 확정한 수가 아니다.

## 남은 범위

- 경력 선호는 저장·설명하지만 자동 경력 필터는 미적용이며 화면에서 확인 필요를 안내한다.
- 개별 공고의 실제 일치 필드/원문과 사용자 발언을 연결하는 추천 근거 writer·과거 검색 이유 전용 조회는 후속 과제다.
- 이번 단일 실제 문장의 성공은 모든 복합 문장·직군에 대한 추출 정확도나 검색 품질 검증 완료를 뜻하지 않는다.
- 이전 상태를 가진 브라우저는 새 대화로 검증한다. 기존 응답 캐시를 새 정책으로 소급 변경하지 않았다.

## 배포 재현·복구 참조

설계 MD는 `bb5931ab3a2d9333cb2b2b8f0c97bfb688077cf1`로 푸시됐고 이번 구현은 작업 트리에서 빌드·배포했다. 이번 배포 요청에 Git 커밋/푸시는 수행하지 않았다.

- API ZIP SHA-256: `f9dfea6b8ab7006a1c5245eb38ee763cdf30e7ba87204b5e2cdc5adc1f23bcaa`
- worker ZIP SHA-256: `f0cffae6eca925675456d32c8526ec82fe5bb44d3150bd311beb521a2452e24e`
- 로컬 `infra/.build/code-release.json`과 해당 릴리스 폴더에 이전 API ZIP 보관.
- 서버 `/opt/career/releases/20261102T023141Z/previous-app`에 이전 앱 보관. 실제 복귀 작업은 실행하지 않았다.
- 검증 원시 집계는 Git 제외 `infra/.build/structured-search-deployment-smoke.json`, `structured-search-deployment-verify.json`에 보관. 토큰·비밀번호를 기록하지 않는다.

연결: [구현 기록](STRUCTURED_SEARCH_IMPLEMENTATION.md), [설계 방향](COMPLEX_SEARCH_CONFIRMATION_DESIGN.md).
