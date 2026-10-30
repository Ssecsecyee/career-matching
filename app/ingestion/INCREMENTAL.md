# 점핏 증분 적재: 파일 계약과 실행 안내

## 2026-10-30 16:38 운영 검색·자동 동기화 연결 완료

채용·교육 검색을 실제 Elasticsearch로 전환하고 기존 EC2에 1분 간격 Outbox 소비 타이머를 설치했다. 원본 공고 942건·교육 7건은 유지하고, 모집 종료/기한 경과 117건을 제외해 검색 색인은 채용 825건·교육 7건이다. Outbox 대기 0건, 타이머 반복 성공, ES green, 대화 작업자 active를 확인했다. React 57건·교육 카드 3건, 주입한 검색 장애의 MySQL 복귀와 다음 요청 ES 재사용도 검증했다. 자동 경보·고용24 수집 자동화·대규모 부하는 별도이며 전체 재색인은 소비 중지 및 변경 경계 보존 절차가 필요하다.

이 상태가 아래 수동 색인/운영 미연결/자동 소비 미구현 설명보다 우선한다. 구현·검증·권한·제한 및 점검 명령은 [검색 동기화 운영 문서](../../docs/SEARCH_SYNC.md)를 따른다.


## 구현 범위
- inventory_jumpit.py: DB를 읽어 기존 ID와 재확인 대상 목록 생성. 기본 3일(날짜형)/7일(상시·미확인), 재확인 최대 100건. 날짜 경과·closed/unavailable는 일상 재확인에서 제외한다. 영구 재개 탐지 정책은 후속 사항이다.
- incremental_jumpit.py: manifest·원본 검증, 기본 오프라인 정제, DB 미리보기, --apply 명시 시 upsert와 search_outbox 원자적 기록.
- 수집 프롬프트: [수집 담당용 지침](../../docs/JUMPIT_INCREMENTAL_COLLECTOR_PROMPT.md).
- 실제 스크래핑, 스케줄러, S3 업로드, Elasticsearch 소비자는 이번 코드에 없다. 기존 최초 적재 SQL을 운영 증분 갱신에 재사용하지 않는다.

## 설정과 권한
`app/ingestion/.env.example`을 `.env`로 복사하고 실제 값을 로컬에서 입력한다. 파일은 Git에서 제외된다. 프로세스 환경 변수가 .env보다 우선하며 .env에는 INGEST_MYSQL_ 키만 허용한다. 비밀번호를 명령 인수·문서·GPT 프롬프트에 넣지 않는다.

별도 ingestion 계정이 필요하다. 현재 career_runtime은 공고 SELECT만 허용하므로 그 계정을 재사용하면 쓰기가 실패한다. 관리자가 대상 DB의 job_postings에 SELECT/INSERT/UPDATE, search_outbox에 INSERT 권한을 가진 계정을 별도로 준비해야 한다. 삭제·DDL·사용자 대화 테이블 권한은 필요 없다. 잠금 함수 사용 가능 여부는 실제 서버에서 확인한다. 이번 작업에서는 계정을 생성하거나 권한을 바꾸지 않았다.

로컬 PC에서 AWS DB에 접근할 때는 기존 SSM 터널(127.0.0.1:13308 → 서버 MySQL:3308)을 사용한다. DB 포트를 외부 공개하지 않는다. 터널이 아닌 원격 호스트는 CA 검증을 사용하는 TLS 설정을 필수로 요구한다.

## CMD 실행 순서

아래 날짜별 폴더는 예시다. 실제 결과 폴더명으로 교체하고 출력 경로는 매번 새 이름을 사용한다.

```cmd
cd /d C:\AWS_project\career_matching\app\ingestion
```

1. 계정·터널 준비 후 읽기 전용 inventory 생성:

```cmd
python inventory_jumpit.py --output "C:\AWS_project\career_matching\workspace\incoming\jumpit\inventory_20261028.json"
```

2. inventory와 수집 프롬프트를 담당 GPT에 전달하고 batch 폴더를 받는다.
3. 네트워크/DB 연결 없는 기본 검증:

```cmd
python incremental_jumpit.py --batch "C:\AWS_project\career_matching\workspace\incoming\jumpit\batch01" --output "C:\AWS_project\career_matching\workspace\ingestion-reports\batch01_validate"
```

4. DB 변경 예상 내역만 확인(트랜잭션 롤백, 영구 쓰기 없음):

```cmd
python incremental_jumpit.py --batch "C:\AWS_project\career_matching\workspace\incoming\jumpit\batch01" --output "C:\AWS_project\career_matching\workspace\ingestion-reports\batch01_preview" --preview-db
```

5. report.json의 신규·변경·동일·건너뜀 및 preserved_fields를 검토한 뒤 명시적 반영:

```cmd
python incremental_jumpit.py --batch "C:\AWS_project\career_matching\workspace\incoming\jumpit\batch01" --output "C:\AWS_project\career_matching\workspace\ingestion-reports\batch01_apply" --apply
```

## 보호 규칙과 제한
- source+source_id로 중복 방지. DB의 fetched_at 이하인 스냅샷은 건너뛴다. 같은 시각에 내용이 다르면 자동 선택하지 않으므로 새 확인 시각과 보고가 필요하다.
- 누락·빈 값·unknown으로 기존 유효 값/상태를 지우지 않는다. 실제로 삭제된 섹션도 자동 삭제되지 않으며 별도 검토가 필요하다.
- 내용 또는 저장 상태가 바뀔 때 source_version을 올리고 같은 트랜잭션에서 검색 Outbox를 남긴다. 동일 내용 재확인은 확인 시각만 갱신한다.
- 합격 판단·조건 의미 분해·LLM 호출을 하지 않는다. 원문 안 SQL/지시문은 문자열 데이터다. SQL 값은 매개변수로 전달하며 테이블·컬럼 이름은 코드 상수다.
- 경로 탈출, ID 불일치, 중복 JSON 키, 해시 불일치, 큰 파일, 미래 시각, 시간대 없는 수집 시각을 거부한다.
- provenance와 해시는 자체 진술·파일 무결성 검증이다. GPT가 잘못 추출한 내용을 독립적으로 사실 검증해 주는 기능은 아니다. 첫 표본은 사람이 원문과 대조해야 한다.
- 입력 배치 전체 검증 후 DB 접근. 적용 중 오류면 배치 전체 롤백. Outbox 저장 실패도 롤백한다. 출력 파일 저장 실패가 커밋 후 발생하면 DB는 이미 반영됐을 수 있으므로 재미리보기로 확인한다.
- 변경 전 원본의 S3 영구 이력과 복구 백업은 아직 연결하지 않았다. 운영 apply 전 원본 배치와 DB 백업을 보관한다.
- 현재 독립 매핑하지 않는 상세 필드는 raw_detail에만 남을 수 있다. 지원 유의사항 등은 실제 원본 구조를 확인한 뒤 어댑터를 추가해야 한다.
- 단위 테스트는 모의 DB 기반이다. 실제 MySQL 계정 권한·잠금·트랜잭션 동작은 격리 DB에서 다음으로 검증해야 한다. 실제 운영 DB에는 실행하지 않았다.


## 2026-10-28 10:21 예약 작업 결과
- page_extraction.py를 추가했다. date_only는 additional_sections.page_extraction.deadline에 날짜·원문·정밀도를 저장하고 deadline_at이나 시간대를 만들어내지 않는다.
- 통합 채용절차·지원 유의사항 원문은 hiring_process와 application_notes가 같은 원문을 참조하며 field_status=present_combined_source로 표시한다. 임의의 구간 분리는 하지 않는다.
- original_sections는 제목·본문·통합 여부를 구조적으로 보존한다. 관측 시각 등 감사 메타데이터는 raw_detail에 남겨 동일 내용 재확인만으로 source_version이 증가하지 않게 한다.
- 원본 10건을 실제 MySQL 8.4의 별도 임시 컨테이너와 전용 시험 계정으로 검증했다. 최초 10건, 중복 재실행, 동일 내용 재확인, 내용 변경 버전 증가, Outbox 권한 오류 시 전체 롤백을 확인했다. 통합 섹션 8건·date_only 10건도 확인했다. 해당 임시 컨테이너는 제거했다.
- 실제 운영 DB에는 쓰지 않았다. 쓰기 계정·백업/복구·자료 재이용 범위 확인이 선행 사항이다.
- date_only 메타데이터를 저장하는 것과 검색에서 날짜만 있는 공고의 노출 만료를 판단하는 것은 별도다. 현 검색은 deadline_at 기준이므로 날짜형 노출 정책·시간대 검증은 후속 작업이다. 모집 상태는 계속 unknown이며 active로 추정하지 않는다.
- 재현용 검증기는 verify_incremental_mysql.py다. 운영 포트 3306/3308/13308을 거부하고 TEST_INGEST_MYSQL_PORT와 별도 임시 root 비밀번호를 요구한다. 임시 DB·계정 생성 권한이 필요하며 운영 서버에서 실행하지 않는다.


## 2026-10-28 운영 표본 반영 완료

사용자의 신규 10건 반영 요청에 따라 quality01 배치를 AWS MySQL에 적용했다. 783 → 793건, 기존 공고 버전·해시 유지, Outbox +10, 통합 유의사항 8건과 date_only 10건 보존, 신규 모집 상태는 모두 unknown이다. 운영 실행에만 임시 최소 권한 DB 계정을 생성하고 작업 후 제거했으며 기존 대화용 계정 권한은 넓히지 않았다. 서버의 보호된 /opt/career/backups 경로에 적용 전 SQL gzip 백업을 만들고 압축 무결성을 확인했다. 이는 실제 복원 훈련 완료를 뜻하지 않는다. 실행 결과는 workspace/ingestion-reports/quality01_1021_mapping_validation/production_apply.json에 보관했다. 원본 실행 패키지는 기존 비공개 S3 버킷의 ingestion-samples 경로에 보관했다. 정기 실행·Elasticsearch 소비자·고용24 연계는 여전히 미구현이다. 현재 로컬 .env는 조회용 계정이므로 후속 자동 적재의 영구 계정/권한 관리는 별도로 준비해야 한다. 자료 재이용 권한이 확인됐다는 뜻은 아니다.


## 2026-10-30 배치 크기 명시

infra/apply_sample.py는 --batch와 --expected-count 1..100으로 검토 건수를 명시한다. 원격 실행에서도 같은 건수와 DB 전후 차이·Outbox 수를 검증한다. 생략 시 기존 10건 동작을 유지하며 신규 전용·백업·배치별 실행 상태·자동 재제출 방지는 유지한다. verify_incremental_mysql.py의 두 번째 인자로 검토 건수를 전달해 격리 시험할 수 있다. 실제 결과는 workspace/ingestion-reports/APPLY_20261030.md 참조.

## 2026-10-30 합의: 자동 동기화와 마감 공고 노출

아래는 확정한 처리 방향이며 이번 문서 수정으로 작업자·스케줄·운영 설정을 실행한 것은 아니다. 현재는 DB 변경과 Outbox 기록, 수동 전체 색인까지 구현했고 자동 소비자는 미구현이다.

- MySQL을 원본으로 보관하고 Elasticsearch는 재생성 가능한 검색용 사본으로 운영한다. 신규·수정·모집 종료·삭제/노출 중단 변경은 DB와 같은 트랜잭션의 Outbox를 통해 전달한다.
- 초기 자동 소비 주기는 1분을 목표로 한다. 수집 주기와 별개이며 처리 시간·장애로 실제 지연이 늘 수 있으므로 실시간 보장은 하지 않는다. 작업자는 성공한 이벤트만 완료 처리하고 실패 시 지연 재시도하며 반복 실패·적체를 관측한다.
- source+source_id와 단조 증가하는 버전을 기준으로 중복 처리·역순 도착을 견딘다. 삭제/노출 중단도 검색 문서 제거 또는 비노출 처리로 반영하며 원본의 물리 삭제와 구분한다. 소비 권한은 대화용 계정과 분리한다.
- 마감일이 경과한 공고는 사용자 검색에서 즉시 제외한다. Elasticsearch 필터와 최종 MySQL 재확인을 함께 사용하고 MySQL 복귀 검색에도 같은 시간·상태 기준을 적용한다. 이미 표시된 카드의 선택·상세 확인 시에도 재확인한다.
- 날짜 경과는 새 수집 이벤트 없이도 발생하므로 별도 주기 작업이 기한 경과를 탐지해 노출 상태를 갱신하고 필요한 Outbox 이벤트를 생성한다. 이 작업의 실행 간격은 구현 시 정한다. 검색 시 필터가 동기화 지연 동안의 노출을 막는다.
- 마감일 경과에 따른 노출 제외와 원문에서 직접 확인한 모집 종료는 별도 근거로 기록한다. 날짜가 지났다는 이유만으로 원문 확인 시각이나 실제 종료 확인을 만들어내지 않는다. 기존 원문·이력은 MySQL에 보관한다.
- 정확한 마감 시각은 출처 시간대를 적용한다. date_only는 원문 날짜·정밀도를 유지하고 한국 날짜 기준 해당 날짜가 지난 뒤 제외한다. 이는 노출 정책이지 실제 마감 시각 추정이 아니다. 날짜 없음·상시채용·상태 미확인은 모집 중으로 단정하지 않으며 정기 원문 재확인 대상으로 둔다. 조기 마감은 출처 재확인으로 탐지한다.

구현 완료 기준: 신규·수정 자동 반영, 중복/역순 이벤트, 실패 후 재시도, 마감 날짜 경계, 조기 마감, 상시/미확인, 검색 장애 시 동일 필터 유지, 원본 보존, 재색인 후 변경 누락 방지를 검증한다. 운영 검색 전환과 자동 동기화 배포는 후속 작업이다.
