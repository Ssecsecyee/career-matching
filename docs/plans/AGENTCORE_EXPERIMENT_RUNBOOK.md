# AgentCore 사용감 실험 v1

상태: 구현 · 관리자 제한 실험 배포 준비
기준일: 2026-11-06

## 제공 범위

- 기존 화면·MySQL·Elasticsearch·직접 문답 저장 API를 유지한다.
- `?agentcore=1`에서 자유 입력만 AgentCore Harness로 실행한다. 일반 경로는 기존 라우터다.
- 서버에서 관리자 인증과 기능 활성화를 검사한다. 쿼리 문자열만으로 권한을 얻을 수 없다.
- 대화의 첫 자유 입력에서 엔진을 고정한다. 기존 방식과 실험 방식 전환은 새 대화로 한다.
- get_saved_answers, search_jobs, search_training 3개 inline 도구만 허용한다. DB 자격증명·소유자 ID·SQL·ES DSL은 에이전트에 제공하지 않는다. 도구의 실제 실행은 기존 작업자가 한다.
- 일상 대화는 Harness의 세션과 관리형 Memory를 사용한다. 확정 문답·원문·추천 근거는 MySQL 기준이다. 장기 기억 전략과 삭제 연동을 갖춘 일반 사용자 전환은 아직 하지 않았다.

## 제한과 비용

사용자 승인 추가 실험 예산은 5 USD다. 소량 합성 smoke 이후 서버의 영속 파일에 전체 관리자 실험 자유 입력을 6턴까지만 예약한다. 실패도 예약 횟수를 소비하며 자동으로 환불·초기화하지 않는다. Harness 왕복은 사용자 입력당 최대 3회, 도구 최대 3개, 각 호출 루프 최대 3반복, 출력 900토큰, 시간 45초, 최근 메시지 6개로 제한한다. 플랫폼 청구액 자체를 실시간 차단하는 결제 한도는 아니며, 실제 청구는 AWS 계측으로 별도 확인한다. 추가 호출 확대는 비용 확인 및 사용자 승인 후에만 한다.

메모리 보존은 서비스 최소값인 3일이다. Browser·Code Interpreter·셸·파일 도구는 허용하지 않는다. 조회·스크롤·선택·답변 저장은 모델을 호출하지 않는다. AgentCore 도구 오류 후 기존 엔진으로 같은 요청을 자동 재실행하지 않는다.

## 기록과 관측

기존 model_invocations에 purpose=agentcore로 Harness 턴의 합산 사용량을 기록한다. 이는 내부 개별 모델 호출 수와 같지 않다. state의 agentcore_tool_trace에는 최근 도구 20개 이름·호출 ID·성공/실패·검색 참조를 보관한다. 기존 intent_decisions는 실험 엔진과 도구 실행 참조를 연결한다. 별도 agent_runs/agent_tool_calls DDL과 관리자 타임라인은 후속 작업이다. 내부 추론 텍스트는 저장하지 않는다.

## 검증

프론트 60개 검사, 백엔드 508개 검사 통과(31개 환경 의존 검사 제외). 신규 모의 검증은 inline handoff·동일 세션 toolResult·도구 허용 목록·소유권 주입 거부·비정상 종료 거부·6턴 이후 차단·자유 입력 전용 엔진 선택을 포함한다.

실제 서울 Harness READY 및 짧은 응답 확인. 합성 문답을 get_saved_answers로 조회한 뒤 최종 자연어를 받는 왕복 확인. 초기 도구 허용 이름 문제는 `@*/도구명` 패턴으로 수정했다. 실제 응답에서 unknown을 미답변으로 표현한 사례가 있어 매핑 지침을 명시했지만 정식 품질 평가 완료로 보지 않는다. 50개 비교 평가와 운영 전체 전환은 미완료다.

## 운용·복구

infra/agentcore/setup.py는 create/status, activate.py는 실험 전용 역할 호출 권한과 기존 config의 실험 키를 설정한다. config-before-agentcore.json에 최초 설정을 보존한다. 실제 ARN·명령 ID는 Git 제외 infra/.build에 보관한다. 일반 서비스 주소에는 실험 쿼리를 붙이지 않는다. 실험 비활성화는 ENABLE_AGENTCORE_EXPERIMENT=false 후 작업자 재시작으로 수행하며, DB·ES 원본을 변경하거나 삭제하지 않는다. 역할·Harness·Memory의 정리 절차는 실험 종료 후 별도 실행한다.
