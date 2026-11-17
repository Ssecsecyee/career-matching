# 모바일 화면 운영 배포 · 2026-11-17

## 적용 범위
- 프런트엔드만 기존 S3/CloudFront에 배포했다. 백엔드·DB·인프라 리소스는 변경하지 않았다.
- 모바일 상담 / 검색 결과 / 내 페이지 전환과 작은 화면·가상 키보드 높이 대응을 적용했다. 데스크톱 좌우 배치는 유지한다.
- 운영 deploy-config.json을 보존하고 정적 파일을 먼저, index.html을 마지막에 업로드했다. 이전 파일은 삭제하지 않았다.

## 검증
- 단위 테스트 80개 통과, 브라우저 모의 시나리오 32개 통과, 프로덕션 빌드 성공.
- 공개 주소: https://d1elpjlek4sj83.cloudfront.net/
- CloudFront 무효화: I3PZ5XYVZUOVSP6YMVKWXTKKKN / Completed.
- 공개 JS index-BmNG5KlN.js, CSS index-adLPtEmo.css의 SHA256이 로컬 배포본과 일치한다.
- 공개 CDN 브라우저에서 모바일 탭과 검색 결과 종류 전환 확인. API는 모의 응답으로 대체했으며 실제 AI 응답 검증은 포함하지 않는다.
- 실제 휴대전화의 소프트 키보드 동작은 추가 확인이 필요하다.

## 복구
배포 전 index.html과 deploy-config.json은 작업 산출물 outputs/mobile_deploy_20261117/previous에 백업했다. 이전 index.html 복원 후 CloudFront 캐시를 무효화하면 된다. 이전 정적 자산은 유지했다.
