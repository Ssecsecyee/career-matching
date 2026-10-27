# 웹 호스팅 먼저 배포하기

현재 우선 경로는 hosting.py이다. 비용 검토가 끝나지 않은 전체 구성 deploy.py apply는 실행하지 않는다.

이번 구성은 비공개 S3 버킷, 버킷 정책, CloudFront 배포, OAC, 응답 보안 헤더 정책 5개다. RDS, EC2, Elasticsearch, Lambda, VPC 엔드포인트는 생성하지 않는다. S3와 CloudFront의 저장·요청·전송 비용은 발생할 수 있으며 무료를 보장하지 않는다.

CMD에서 한 줄씩 실행한다.

```cmd
conda activate AWS_project
cd /d C:\AWS_project\career_matching
python infra\hosting.py plan
python infra\hosting.py review
```

plan은 변경 세트만 만들며 웹 리소스를 아직 생성하지 않는다. review의 status가 CREATE_COMPLETE인지 확인한다. CREATE_IN_PROGRESS면 잠시 뒤 review만 다시 실행한다. 변경 목록에 S3/CloudFront 관련 5개만 있는지 확인한 뒤 다음으로 진행한다.

```cmd
python infra\hosting.py apply
python infra\hosting.py status
```

apply가 실제 리소스 생성을 시작한다. status를 일정 간격으로 확인해 CREATE_COMPLETE 또는 UPDATE_COMPLETE가 된 후 게시한다. CloudFront 생성은 시간이 걸린다. 실패하면 CloudFormation 콘솔 Events를 확인하고 임의로 관리자 권한을 추가하지 않는다.

```cmd
python infra\hosting.py publish
```

publish는 화면을 새로 빌드하고 정적 파일만 올린 뒤 CloudFront를 무효화한다. 출력의 url이 접속 주소다. 코드나 .env, DB 데이터는 업로드하지 않는다. 공개 화면은 백엔드 연결 준비 중 안내를 표시하며 채팅/API 호출과 접속 코드 입력을 비활성화한다. 웹 주소 확보 완료가 DB/Bedrock 연결 완료를 의미하지 않는다.

실제 웹 주소에서 HTTPS와 안내 화면을 확인한다. 브라우저 캐시가 남으면 새로고침한다. 연결 준비 상태는 배포 버킷의 deploy-config.json에서 apiEnabled=false로 관리하고, 이 파일은 캐시하지 않도록 게시한다. 로컬과 추후 전체 배포용 public/deploy-config.json은 true다. API가 연결되기 전에 false를 true로 바꾸면 동작하지 않는다.

상태 파일은 infra/.build/hosting-state.json이다. 전체 배포용 deployment.json과 구분하며 다른 스택 이름 career-matching-web을 사용한다. 종료 시 S3 버킷은 데이터 보존 설정으로 남으므로 스택 삭제만으로 저장 비용까지 모두 없어지지는 않는다. 삭제는 별도 검토 후 진행한다.

후속 작업: 최소 사양 DB/검색엔진 서버의 실제 메모리·운영 비용 확인 → API와 Bedrock 연결 → 같은 CloudFront 주소에 API 경로 추가 → readiness 설정 전환. 현재는 실제 AWS 배포 미실행이며 사용자가 위 명령으로 진행한다.

검증: 호스팅 전용 템플릿 cfn-lint 통과, 정적 리소스만 포함하는 구조 검사 통과, React 빌드 및 API 테스트 2개 통과. 계정 내 생성 권한과 실제 호스팅 접속은 사용자 실행 후 확인한다.
