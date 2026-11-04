# 고용24 훈련 대량 수집·증분 갱신 운영 절차

상태: 초회 운영 DB 적재·교육 ES 검색 연결 완료 / 일일 자동 수집·적재 예약 연결 전

## 수집 범위와 사실

훈련 4종(내일배움카드·사업주훈련·컨소시엄·일학습병행)이 대상이다. 최초 실행은 훈련 시작일 2026-11-04~2027-02-02 범위를 전 페이지 조회한다. 전 과거 이력을 수집했다는 뜻이 아니다. 목록 조회 중 제공자 총수가 바뀌므로 초기 142,833건을 확정 수량으로 사용하지 않는다.

향후 새 실행은 기본 7일씩(--window-days) 나눠 페이지 이동 중 변경의 영향을 줄인다. 이번 최초 실행의 기존 체크포인트는 그대로 보존한다. 목록 pageSize=100과 페이지 상한을 고려하여 100,000건 초과 검색 구간을 날짜 기준으로 나눈다. 날짜 하루도 상한을 초과하면 중단하고 NCS 등의 추가 분할이 필요하다고 보고한다. 1.25초 이상 요청 간격, 30초 요청 제한, 2MiB 응답 제한, 리다이렉트 차단을 적용한다. 인증·호출 제한·제공자 오류 시 반복하지 않고 중단하여 체크포인트에서 재개한다.

키는 로컬 검증 폴더의 Git 제외 .env에서 서비스별로 읽는다. 인증 URL/키/오류 원문을 출력하지 않는다. 수집 원본은 키를 제거하고 gzip으로 보관한다.

## 로컬 설정 파일과 계획 확인

초기 실험은 C:\AWS_project\고용24_API_검증\.env를 사용했다. 커리어 프로젝트의 일일 실행에는 app/ingestion/.env.work24를 --env-path로 명시한다. 자동으로 backend/.env를 읽는 구조가 아니다.

- app/ingestion/.env: 기존 INGEST_MYSQL_* DB 연결 전용. API 키를 섞으면 기존 로더가 거절한다.
- app/ingestion/.env.work24: 훈련 4종 API 키 전용. 실제 값은 Git 제외.
- app/ingestion/.env.work24.example: 빈 양식이며 Git에 보관.
- app/backend/.env: 챗봇·Bedrock 등 백엔드 설정. 이번 API 수집 키와 분리.

.env.work24.example을 .env.work24로 복사하고 각 서비스의 키를 넣는다. 서비스 간 키를 재사용한다고 가정하지 않는다. 키 값은 로그·채팅·문서에 붙이지 않는다.

--live가 없는 work24_daily.py의 다음 출력은 정상이다.

```text
Plan: rolling list inventory -> offline count reconciliation -> bounded pending detail batch. No API/DB calls.
```

이 단계는 실행 계획만 확인한다. .env 파일 존재·키 유효성·DB 연결까지 확인했다는 뜻이 아니다. --live를 붙이면 실제 목록 수집과 기본 최대 20과정 상세 조회를 수행한다. --read-db-inventory는 별도의 DB 읽기와 신규/변경 파일 생성을 추가하며, 운영 DB에 쓰지는 않는다.

## 매일 실행할 운영 구성

로컬 시험은 위 명령을 직접 실행한다. 운영은 기존 EC2의 별도 작업자와 systemd timer를 우선 검토한다. 개인 PC·SSM 터널·SSO 로그인 유지에 의존하는 예약은 운영 구성으로 사용하지 않는다. 서버는 MySQL에 내부 연결하고, API 키는 서버 비밀 저장소에서 읽도록 별도 배포가 필요하다.

매일 목록 갱신 → DB inventory 대조 → 신규/변경/재확인 큐 → 검증 → MySQL upsert와 Outbox → 교육 ES 순으로 연결한다. 기존 시작일 필터는 매 검색 시 적용하므로 일일 수집이 실패해도 시작일 도래 자료를 신청 후보로 계속 노출하지 않도록 한다. 이 검색 정책 자체의 운영 배포는 아직 필요하다.

운영 예약 전에는 동시 실행 방지 잠금, 마지막 성공 기록, 실패 시 체크포인트 재개, 429/일시 오류의 제한된 재시도, 실패 알림을 추가한다. 기본 상세 20건은 시험 제한이며 운영 처리량은 실제 API 일일 호출 한도와 대기열 증가량을 확인해 정한다. 현재 실행기는 이러한 운영 관제와 DB 자동 쓰기까지 완성한 상태가 아니다.

## 구현 파일

| 파일 | 역할 |
|---|---|
| app/ingestion/work24_collect.py | 날짜 구간별 전체 목록 수집, 재개, 로컬 증분 카탈로그 및 상세 큐 |
| app/ingestion/work24_reconcile.py | 오프라인 중복·고유 ID·제공자 건수·시작일 집계 |
| app/ingestion/inventory_work24.py | 기존 MySQL의 고용24 교육 ID·해시를 읽는 전용 inventory |
| app/ingestion/work24_export.py | 시작 전 자료의 공통 교육 형식 변환 및 DB 신규/변경 분리 |
| app/ingestion/work24_details.py | 제한된 수의 신규·변경·재확인 큐 상세/일정 조회 및 검증 |
| app/ingestion/work24_daily.py | 목록→대조→제한 상세 작업을 순차 실행하는 일일 실행기. 스케줄러 자체는 등록하지 않음 |

위 로컬 수집 도구 자체는 업무 DB·ES에 쓰지 않는다. 초회 운영 반영은 별도 ingest_work24.py·remote_import_work24.py·infra/apply_work24.py로 수행했다. [운영 반영 기록](../deployments/WORK24_INITIAL_IMPORT.md)을 참조한다. 로컬 SQLite는 수집 상태 저장소이며 AWS MySQL과 다르다.

## 신규만 가져온다는 의미

API에 수정일 이후 전체 변경을 제공하는 기능이 검증된 것은 아니다. **목록을 다시 읽어 식별하고, 비싼 상세 조회와 DB 삽입을 신규에 한정**한다. 목록 요청까지 신규만 조회할 수 있다고 주장하지 않는다.

- 식별: 서비스 + trprId + trprDegr + trainstCstId. 문자열·앞자리 0 보존.
- 실제 교육 source_id: 서비스 접두사 + 위 식별자의 결정적 해시. 동일 회차 재수집은 같은 ID.
- 상세 조회: 신규이면서 시작 전인 과정 우선.
- 변경 감지: 제목·교육 기간·대상·NCS·주소·비용 등의 목록 해시가 바뀌면 상세 재확인.
- 관측값: 신청 인원·평점·표시 아이콘만 바뀐 경우 상세를 재호출하지 않음. 원본 값은 보존.
- 제한적 재확인: 시작 전 기존 과정의 상세 확인이 3일을 지나면 다시 큐에 넣음. 이 기간 중 상세 수정 발견이 늦어질 수 있음.
- 시작일 당일·이후 또는 미확인: 상세 신규 큐에서 제외. 실제 모집 상태를 closed로 바꾸지 않음.
- 목록에 없다는 이유만으로 DB 삭제·모집 마감 처리하지 않음.

동일 카탈로그를 계속 재사용해야 한다. 매번 새 빈 카탈로그를 만들면 모두 로컬 신규로 판단한다. 로컬 카탈로그 소실 시 AWS inventory와 수신 원본으로 복구해야 한다. DB 반영 직전에는 최신 DB와 UNIQUE(source,source_id)로 다시 대조해 조회 이후의 동시 삽입을 막는다.

## 상세와 원본의 경계

목록 전체를 먼저 확보한다. 신청 기간·개인 비용·지원 가능을 추정하지 않는다. 목록의 contents가 비어 있으면 세부 커리큘럼 미제공으로 유지한다. 제목만으로 기술 태그를 자동 확정하지 않는다.

상세 작업자는 실행 직전에 시작일을 재확인하고, 상세·일정의 과정 ID·회차·기간·NCS 충돌을 검증한다. 수집 중 목록 버전이 바뀌면 해당 결과를 승인 파일 목록에서 제외한다. 상세·기관 시설·장비 원본은 압축 보관하지만 검색 문서에는 복제하지 않는다. 기관 장비가 과정 커리큘럼이라는 해석을 금지한다.

상세 API 2회씩 전체를 호출하는 작업과 전체 목록 수집은 구분한다. 초기 상세 배치는 기본 20과정(최대 40요청)이다. 이후 처리량은 실제 API 사용 한도를 확인해 정한다. 대기열이 많으면 여러 차례 이어서 처리한다. Bedrock 호출은 없다.

## 집계·검증

- started: 한국시간 기준 시작일이 오늘 또는 과거. 오늘 시작도 포함.
- future: 시작일이 내일 이후. 신청 가능 보증이 아님.
- unknown: 시작일 없음/잘못된 날짜. 신청 후보에서 제외.
- 응답 총수, 실제 반환 행 수, 중복 제거한 고유 ID 수를 분리.
- 페이지 조회 중 제공자 변경과 건수 차이를 경고. 고정 스냅샷 보장으로 표현하지 않음.
- 수집 완료 후 reconciliation.json/REPORT.md 생성. 차이가 있으면 해당 날짜 구간을 재조회해 대조. 이름이 같다는 이유로 중복 제거하지 않음.
- DB inventory가 없으면 신규는 로컬 기준일 뿐이다. 실제 DB inventory와 비교한 결과만 DB 신규라고 부른다.

## CMD 실행 예시

작업 폴더: C:\AWS_project\career_matching\app\ingestion

최초 수집 재개(동일 출력 경로·기간 유지):

```cmd
python work24_collect.py --env-path "C:\AWS_project\career_matching\app\ingestion\.env.work24" --output "C:\AWS_project\career_matching\workspace\work24\bulk_20261104" --start 2026-11-04 --end 2027-02-02 --resume
```

완료 후 대조:

```cmd
python work24_reconcile.py --catalog "C:\AWS_project\career_matching\workspace\work24\bulk_20261104\catalog.sqlite3" --output "C:\AWS_project\career_matching\workspace\work24\bulk_20261104" --run-id 2026-11-04_2027-02-02
```

DB 조회에는 기존 SSM 터널과 ingestion 계정이 필요하다. 파일은 새 경로로 지정한다.

```cmd
python inventory_work24.py --output "C:\AWS_project\career_matching\workspace\work24\inventory_20261104.json"
python work24_export.py --catalog "C:\AWS_project\career_matching\workspace\work24\bulk_20261104\catalog.sqlite3" --run-id 2026-11-04_2027-02-02 --db-inventory "C:\AWS_project\career_matching\workspace\work24\inventory_20261104.json" --output "C:\AWS_project\career_matching\workspace\work24\bulk_20261104\normalized"
```

inventory는 24시간 이내 자료를 사용한다. 기존 DB와 해시가 같은 행은 건너뛰고, 없는 행만 신규 출력에 넣는다. 내용이 다른 기존 행은 training.changed.review.jsonl로 분리하며 상세 검증 자료를 목록의 빈 값으로 덮지 않는다.

일일 실행 계획(네트워크 호출 없음):

```cmd
python work24_daily.py --env-path "C:\AWS_project\career_matching\app\ingestion\.env.work24" --catalog "C:\AWS_project\career_matching\workspace\work24\bulk_20261104\catalog.sqlite3" --output-root "C:\AWS_project\career_matching\workspace\work24\daily"
```

--live를 명시하면 오늘-7일~오늘+90일 목록을 갱신하고 제한된 상세 배치를 처리한다. --read-db-inventory도 지정하면 목록 완료 후 DB를 읽어 신규/변경 공통 교육 파일을 내보낸다. 이 옵션도 DB 수정은 하지 않으며, DB 연결 실패 시 뒷단을 중단한다. 과거 7일 겹침은 늦은 노출·수정을 다시 관측하기 위한 범위다. 동일 카탈로그에서 서로 다른 실행을 동시에 돌리지 않는다.

## 운영 자동화 연결 전 남은 관문

1. 수집 건수 차이·중복·기간을 대조하고 신규 표본을 검수.
2. 합의한 source_payloads/classification_codes/training_classifications 및 교육 확장 마이그레이션을 격리 DB에서 검증.
3. DB inventory→신규/변경 판단→검증된 공통 교육 upsert→같은 트랜잭션 outbox를 연결. 아직 이 문서의 수집 도구가 운영 DB에 자동으로 쓰지는 않는다.
4. 교육 ES 시작일 필드 추가 및 재색인 후 신청 후보 검색 코드 배포. 운영 반영 완료: 총수가 많아도 오류를 내지 않고 상위 100건씩 최대 1,000건 범위에서 검증해 최대 3건을 반환한다.
5. 최종적으로 EC2의 별도 systemd timer/작업자로 정기 실행. API 키는 서버 비밀 저장소로 옮기고 IAM 범위를 제한. 로컬 .env 경로를 서버에서 사용하지 않음.
6. 호출 시간·대기열·원본 용량·429·실패 알림과 서버 밖 원본 보존을 확인. 현재 4GiB 공유 호스트에서 대량 정제·색인 동시 실행은 피함.

목록 전체 조회는 Lambda 한 번에 끝내는 작업으로 가정하지 않는다. 장기 작업은 EC2에서 진행하거나 작은 범위로 쪼개야 한다. 일일 스케줄·서버용 API 키 업로드는 아직 실행하지 않았다. 초회 운영 DB 적재·색인 반영은 별도 배포 기록에 정리했다.
