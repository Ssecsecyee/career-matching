# 미사용 코드 정리 · 2026-11-20

## 조사·제거 범위
- 프런트엔드: esbuild main.jsx 의존 그래프상 모든 서비스 JS/JSX 모듈이 도달 가능했다. 모듈 파일은 삭제하지 않았다.
- CareerApp의 고정 false noteOnly 조건부 레이블·placeholder·전송 조건을 현재 동작으로 단순화했다.
- 앞선 page!=chat 분기에서 return하므로 실행되지 않는 동일 조건의 스크롤 분기를 제거했다.
- JSX에서 제거된 spark/disclaimer/public-trial-note 스타일을 정리했다. 일반 화면/모바일/평가 영역의 스타일 변경은 브라우저 회귀 확인했다.
- 백엔드 AST에서 사용되지 않는 import 6개 제거: cloud.os, handlers/dialogue.hashlib·hmac, mysql_chat.os, services/dialogue.consultation_context, memory.re.
- 동적 호출·구형 세션·운영 복구·대체 검색 경로는 삭제 근거가 부족해 유지했다. 전체 저장소에 데드코드가 전혀 없다고 보장하는 검사는 아니다.

## 검증
- 프런트엔드 테스트 84개 통과·프로덕션 빌드 성공.
- 백엔드 561개 실행, 530개 통과·31개 조건부 건너뜀.
- PC·휴대전화·작은 휴대전화·가로 화면 가이드 회귀 검증 통과.
- PC·모바일 세로·가로 첨부/전송 정렬과 직접 검색의 채팅 비간섭 확인.
- git diff --check 통과. 실제 Bedrock 호출·운영 DB 변경·배포 없음.

## 남긴 작업
큰 CareerApp/context_router 분리, 화면 스타일의 중복 선언 정리는 별도 변경으로 평가한다. 범위가 넓어 이번 보존적 정리에 섞지 않았다.
