# 작업 기준

- docs/의 8개 문서를 설계 기준으로 사용한다. DECISIONS.md의 미정 사항을 확정 사실로 쓰지 않는다.
- workspace/에서 수집·API·교육 자료에 접근한다. 일부는 기존 폴더로 연결된 junction이다.
- archive/는 변경 전 문서 및 복구 스냅샷이다. 수정·삭제하지 않는다.
- .env, 인증키, DB 비밀번호는 출력·문서화·커밋하지 않는다.
- 기존 경로와 junction을 함부로 삭제하지 않는다. Docker 볼륨·원본 데이터를 유지한다.
- 외부 수집은 출처 이용 범위 확인 후 실행한다. 유료 AWS 리소스 생성 전에 예산을 확인한다.
- 현재 구현 완료와 설계 목표를 구분한다.

- 새 서비스 구현은 app/backend, app/frontend, app/ingestion, infra에서 진행한다. workspace는 기존 실험·자료다.
- 기본 로컬 검증은 실제 AWS 호출 없이 수행한다. Bedrock opt-in을 임의로 활성화하지 않는다.
- backend 테스트: app/backend에서 python -m unittest discover -s tests -v.
- 운영 /chat 차단은 인증·영구 세션/근거 저장을 구현하고 검증한 뒤 해제한다.
