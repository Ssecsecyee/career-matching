# 로컬 공고 색인

## 2026-10-30 운영 자동 동기화

`sync_outbox.py --config 보호된설정경로`가 별도 최소 권한 DB 계정으로 변경을 처리한다. AWS에서는 systemd 타이머가 실행한다. 로컬 회귀는 `python app/ingestion/search_index/verify_sync_local.py`로 격리 DB·색인에 수행한다. 운영 연결과 제한은 [SEARCH_SYNC.md](../../../docs/SEARCH_SYNC.md)를 따른다. 기존 전체 색인 도구는 로컬 용도이며 운영 별칭 교체 전에 소비 중지·변경 경계 보존이 필요하다.

실제 공고 스냅샷을 로컬 Elasticsearch에 적재하고 검색 어댑터로 조회한다. 운영 bootstrap에는 연결하지 않았으며 AWS/DB/Bedrock 호출은 없다.

프로젝트 최상단 CMD:

```cmd
docker compose -f infra\elasticsearch\compose.local.yaml up -d --wait
python app\ingestion\search_index\index_snapshot.py --input app\backend\local-data\jumpit_all_v3\jobs.normalized.json
```

매번 새 career-jobs-local-* 색인을 생성하고 문서 건수·검색 검사 통과 후 career-jobs-local-read 별칭을 원자적으로 전환한다. 이전 색인은 자동 삭제하지 않는다. 실패 시 기존 별칭은 유지되지만 미완성 새 색인이 남을 수 있으므로 진단 후 수동 정리한다. 반복 실행 시 디스크 사용량에 주의한다. 데이터와 보고서는 Git 제외 경로 workspace/search-index/<UTC 실행시각>/report.json에 보관한다.

source+source_id의 JSON 표현을 해시한 문서 ID로 출처 충돌을 방지한다. 동일 배치의 중복 ID는 거부한다. 고용24는 정규화 어댑터가 같은 입력 구조를 제공해야 하며 현재 실제 응답 호환성을 확인한 것은 아니다. 현재 주소 매핑은 입력 스냅샷의 구조에 따라 선택하므로 정식 공통 계약 확정 전에 고용24 데이터를 함께 적재하지 않는다.

제목·회사·업무·자격요건·우대사항·기술 본문을 Nori로 검색하고, 기술 배열은 별도 분석기로 C++/C#/Next.js를 보존한다. 기술 동의어는 엔진의 검색 분석기에 적용한다. 동의어 대상은 현재 React·PostgreSQL·Python의 등록된 별칭이며 임의 의미 추론을 하지 않는다. 본문 Nori에는 같은 기술 동의어가 적용되지 않는다.

검증된 SearchPlan만 쿼리로 바꾸며 기술 조건은 AND, 모집 상태는 기본 active만이다. 로컬 스냅샷 검증에서만 unknown을 명시적으로 허용한다. 마감 필터는 기존 SQL의 always_open/날짜 없음/미래 시각 규칙을 따른다. 시각 미확인 마감일 원문은 보존하되 임의 시각을 생성하지 않는다. 버전과 source는 결과에 포함된다.

2026-10-29 로컬 스냅샷 783건 색인, React/리액트/리엑트 각 42건, 프론트엔드 개발 64건, 백엔드 서버 개발 41건, React+서울 27건, React+TypeScript 22건, 없는 기술 0건을 확인했다. 시각별 마감 제외로 결과가 바뀔 수 있다. 모집 중 검증 또는 사람의 적합성 평가 완료를 뜻하지 않는다.

남은 작업: 실제 DB 최신 상태·버전 재확인 연결, bootstrap에서 명시적 검색 어댑터 선택, 사용자 화면 검증, 전체 매핑 확정, Outbox 증분 소비자/재시도, 동일 기준 시각의 품질 비교, 최소 3배 부하, AWS 배포. 지금 챗봇의 운영 검색은 여전히 MySQL이다.
