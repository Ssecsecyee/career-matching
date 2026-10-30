# 2026-10-30 AWS Elasticsearch 배포 결과

후속 16:38 배포로 운영 검색 전환과 자동 Outbox 소비까지 완료했다. 최신 상태는 [SEARCH_SYNC.md](../../docs/SEARCH_SYNC.md)를 따른다. 아래는 최초 확장·수동 색인 단계의 기록이다.

## 완료

- 기존 EC2 i-0102ab037d03cbb34를 t4g.small에서 t4g.medium(4GiB)으로 변경. 같은 인스턴스와 EBS 볼륨 유지.
- 변경 전 MySQL 전체 gzip 백업 생성·압축 해제 읽기·SHA256 검증 완료. 백업: `/opt/career/backups/before-search-resize-20261030T065955Z.sql.gz`.
- ARM64 Elasticsearch 9.5.5와 analysis-nori 설치. basic 라이선스, 단일 노드, 별도 영속 Docker 볼륨.
- 엔진 메모리 한도 2GiB, JVM 힙 512MiB. 접근은 `127.0.0.1:19200`으로 제한하며 외부 검색 포트를 열지 않음.
- AWS MySQL에서 채용 942건·교육 7건을 읽어 별도 색인 생성. 읽기 별칭: `career-jobs-read`, `career-training-read`.
- Elasticsearch green, Nori 설치 확인, OOM 없음. 최종 점검 시 가용 메모리 2187MiB, career-worker active. 시점 측정값이며 부하 시험 결과가 아님.
- DB 쓰기와 Bedrock 호출 없이 검증. MySQL 채용 942건·교육 7건 유지.

## 검색 검증

React / 리액트 / 리엑트 각각 57건, 프론트엔드 73건, 백엔드 50건, React+서울 35건, React+TypeScript 30건. 없는 검색어는 0건.

교육 React·리액트 참고 카드 각 3건. 현재 신청 가능 후보는 0건으로 유지하며 모집 미확인을 모집 중으로 바꾸지 않음. 검색 후보를 MySQL 현재 데이터와 다시 대조하는 검증도 통과.

## 아직 적용하지 않은 항목

- 운영 챗봇의 검색 선택 설정과 실행 코드는 변경하지 않음. 현재 운영 검색은 MySQL이며, 다음 단계에서 최신 검색 연결 코드·설정 적용과 실패 시 MySQL 복귀를 검증해야 함.
- Outbox 자동 소비자는 미구현. 이번 색인은 수동 전체 스냅샷이며 신규 DB 적재가 자동으로 ES에 전파되는 상태가 아님.
- 대규모 부하 시험은 고용24 연결 단계로 연기한 기존 합의 유지.
- 구조화된 기술 조건의 태그 필터를 본문까지 확장하는 개선은 별도 작업.
- EC2를 직접 확장했으므로 기존 CloudFormation LaunchTemplate의 t4g.small 설정과 실제 t4g.medium 사이에 차이가 있음. 후속 인프라 변경 전 설정을 안전하게 일치시켜야 하며 서버 교체를 유발하는 무검토 적용을 하지 않음.

## 실행 기록

상세 상태·명령 ID는 Git 제외 경로 `infra/.build/resize-search-state.json`, `infra/.build/search-engine-install.json`에 보관. 서버 배포 폴더는 `/opt/career/search-releases/20261030t070159z`이며 기존 앱과 분리되어 있음.

이번 작업은 Git 커밋·푸시를 실행하지 않음.
