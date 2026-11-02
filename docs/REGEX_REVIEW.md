# 정규식 유지·정리 판단

상태: 코드 조사·정리 제안 · 기준일: 2026-11-02

## 집계 범위

app/backend/src의 Python AST에서 re 모듈 직접 호출을 집계했다. 호출 표현식 62개이며 실행 횟수·고유 패턴 수가 아니다. search 34, sub 12, fullmatch 9, compile 2, split 2, findall 1, escape 2다. re.escape 2개는 매칭이 아닌 보조 처리다. 컴파일된 객체 메서드 호출·문자열 in/replace 규칙은 이 집계에 포함하지 않는다. 이전 56이라는 숫자는 같은 기준으로 재현되지 않았다.

## 필요한 처리: 유지 27개 호출

| 위치 | 호출 수 | 이유 |
|---|---:|---|
| config.py | 1 | 환경 변수 키 형식 검증 |
| handlers/dialogue.py | 3 | 공고 ID·요약/수정 버전 해시 형식 검증 |
| handlers/queued.py | 1 | 작업 결과 조회 경로의 ID 형식 제한 |
| repositories/elasticsearch_training.py | 1 | 색인 이름 허용 문자 검증 |
| repositories/job_search_factory.py | 1 | 색인 이름 허용 문자 검증 |
| services/admin_auth.py | 1 | 클라이언트 식별자 형식 검증; 인증 자체는 별도 |
| services/intent_context.py | 6 | 민감 키·Bearer·이메일·전화번호 등의 가림; 완전한 개인정보 탐지 보장은 아님 |
| services/condition_structure.py | 2 | 원문 목록 경계와 이어지는 문장 구분; 원문 위치 검증과 함께 유지 |
| services/condition_display.py | 5 | 공백 정리·표시용 학력/경력/기술/협업 분류; 자격 판정으로 확대 금지 |
| services/assessment_summary.py의 build_summary | 4 | 경력 없음 진술과 경력 충족 선택의 명시적 충돌 경고; 좁은 패턴만 탐지하며 선택을 덮어쓰지 않음 |
| services/learning.py의 topics_in | 2 | 기술 별칭의 단어 경계·대소문자 인식, escape 포함; 불필요한 부분문자열 오탐 방지 |

표시 분류·경력 충돌 경고는 제품 동작을 유지한다는 조건에서 유지한다. 표시 분류를 없애거나 구조화된 경력 진술을 확보하면 대체할 수 있지만, 같은 규칙을 단순 문자열 검색으로 옮기는 것은 복잡성 제거가 아니다.

## 제거 우선 대상: 기존 의도 판정 28개 호출

| 함수 | 호출 수 | 대체 방향·삭제 조건 |
|---|---:|---|
| conversation_policy.assessment_request | 4 | 중단/재개를 v2 assessment_control 및 직접 action으로 통일. remember·consult 경로에서도 호출되어 먼저 이전해야 함 |
| conversation_policy.search_target | 7 | 채용/교육 대상과 전환을 문맥 분류 target으로 통일 |
| consultation.legacy_task | 5 | 상담 task를 문맥 분류/명시적 action으로 통일 |
| assessment_summary.summary_requested | 4 | summary action으로 통일 |
| search_continuation.is_more_request | 2 | next_results action과 문맥 분류로 통일. 제외 ID 누적 로직은 유지 |
| search_review.is_confirmation / needs_review | 2 | confirm_search action 및 서버 검토 정책으로 통일. 표현에 따라 검토 생략하는 예외 제거 |
| learning.retrieve | 4 | 교육 대상·후속 지칭·온라인/오프라인을 구조화된 분류 결과로 받기. 문답 종료 후 교육 연결에도 호출되므로 호출부 분리 후 제거 |

이 코드는 현재 사용처가 남아 있다. v2가 활성화됐다고 일괄 삭제하면 호환 경로·직접 상담·교육 연결이 깨질 수 있다. 기존 경로 비활성화, 참조 제거, 자유 입력/직접 action 회귀 평가 후 삭제한다. 호출 수 감소가 아니라 의도 결정 책임 단일화가 목적이다.

## 애매한 처리: 7개 호출

| 함수 | 호출 수 | 유지 위험 / 즉시 제거 위험 / 판단 |
|---|---:|---|
| conversation_policy.respect_preferences | 3 | 모델이 질문 중단을 어겼을 때 마지막 방어다. 문장 패턴으로 정상 설명을 지우거나 우회 질문을 놓칠 수 있다. 즉시 삭제하면 중단 선호 보장이 약해짐. 구조화된 질문 블록 차단과 평가로 대체한 뒤 제거 |
| model_search.normalize_model_search | 4 | 2개는 지역 무관 표현에 따른 필터 해제, 2개는 legacy 기술 키워드 중복 제거(escape 포함). 모델 결과를 표현 규칙으로 다시 바꾸므로 의미 변경 위험. 새 v2 경로에서는 구조화된 changes가 우선이나 다른 호출부가 남음. v1 호환 폐기·명시적 지역 해제 회귀 평가 후 제거 검토 |

## 실행 순서

1. 상태·행동 계약과 직접 버튼 action을 고정한다.
2. 현 대화 평가셋에 다른 결과·교육 후속·부정문·중단/재개·요약·지역 해제·상담을 포함한다.
3. v2 단일 진입을 보장하고 기존 함수 사용처를 이전한다.
4. 의도 판정 28개 호출 및 사용하지 않는 호환 함수부터 제거한다.
5. 애매한 7개는 대체 안전장치와 평가를 갖춘 후 처리한다.
6. 입력 검증·원문 보존·가림 규칙은 유지하고 필요한 경우 공통화한다.

이번 분류는 코드 삭제 완료나 정확도 입증을 의미하지 않는다. 서비스 코드는 변경하지 않았다.
