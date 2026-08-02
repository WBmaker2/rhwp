# Staging deployment workflow 구현 계획

작성일: 2026-08-02 (Asia/Seoul)
대상 브랜치: `feat/firebase-collaboration-mvp-v1`
상태: 로컬 구현·검증 단계; GitHub Environment 적용, push, dispatch, cloud mutation 미실행

## 목표

승인된 deployment packet과 별도 deployment approval record를 동일한 검증 경계로
소비하는 `prepare → protected deploy → verify` workflow를 저장소에 추가한다.
`prepare`는 cloud credential 없이 packet/review/evidence/record를 검증하고, 같은 실행의
artifact만 protected job으로 전달한다. Protected job은 `staging-deployment` Environment의
승인과 same-run artifact 검증을 모두 통과하기 전에는 OIDC 인증이나 cloud 명령을 실행하지
않는다.

## 현재 검증 기준

- packet workflow run: `30738684540`, attempt `1`
- packet artifact: `staging-approval-packet-deployment`
- packet artifact server digest: `sha256:810b5be50c06b513b68487961ef4ca3c2bfc3b336f25a2997eb265660ea7f3e5`
- packet JSON exact-byte SHA-256: `54a54e80b49d6c5693ed08cc34cf7a6c6f75a005afe4779004620575c7de0858`
- approved packet source commit: `29c4c037b2a307a056f4801e248558311337b979`
- approval reference: `staging-bootstrap-approval-2026-07-27-001`
- 현재 approval record의 `deploymentApproved=true`, `cloudMutationApproved=true`,
  `mutationCommands=[]`

Workflow 코드가 추가되는 commit은 packet source commit과 달라질 수 있으므로 dispatch 시
`source_commit_sha`를 별도 입력으로 받아 packet의 승인 source/run과 정확히 결합한다. 배포
workflow는 소스 재빌드가 아니라 packet의 immutable image digest만 소비한다.

## 구현 범위

1. `scripts/staging_deployment_prepare.py`
   - packet 원문 bytes를 읽고 exact-byte SHA-256을 재계산한다.
   - `staging_deployment_approval_record.py`로 review/evidence/record를 독립 재검증한다.
   - source commit, packet run/attempt, artifact 이름/digest, packet SHA를 입력값과 비교한다.
   - 승인 record를 재생성한 값과 파일 값을 비교하고, 승인 flag·acknowledgement·빈 mutation
     목록을 다시 확인한다.
   - packet JSON 원문은 재저장하지 않고 bytes 그대로 same-run artifact에 복사한다.
   - 배포 job이 사용할 비밀값 없는 `deployment-input.json`만 파생 생성한다.
2. `.github/workflows/staging-deployment.yml`
   - `workflow_dispatch` 입력에 source/run/artifact/packet/approval 경계를 명시한다.
   - `prepare`에는 `id-token: none`을 부여하고 same-run approved input artifact만 만든다.
   - `deploy`는 `environment: staging-deployment`와 `id-token: write`를 사용하지만, 먼저
     same-run artifact를 검증한다. 외부 Environment 설정이 없으면 GitHub 보호 규칙에서
     중단된다.
   - 현재 로컬 구현은 `execute_mutation=false` 기본값의 guard까지 포함한다. 실제 OIDC,
     Cloud Run/IAM/Tasks mutation은 Environment read-back과 별도 dispatch 승인을 받은 뒤
     다음 변경에서 활성화한다.
   - `verify`는 mutation이 실행된 경우에도 acceptance/rollback evidence가 없으면 성공을
     보고하지 않는 경계만 정의한다.
3. `scripts/tests/test_staging_deployment_prepare.py`와 workflow contract test를 추가한다.
4. 이 계획과 구현 결과를 보고서로 남기고, 모든 로컬 테스트를 실행한다.

## 불변 규칙

- packet formatter, key sort, pretty-print, newline 변경 금지
- access token, ID token, Authorization header, password, private key, service-account key,
  Firebase API key 원문, internal flush token 원문을 파일·로그·artifact에 남기지 않음
- run-bound record/package를 Environment 변수나 secret에 넣지 않음
- 승인 record의 source/run/artifact/packet SHA 불일치 시 fail-closed
- `mutationCommands=[]`와 packet의 read-only security invariant 유지
- 이 단계에서 GitHub Environment 생성·변경, secret/variable 등록, push, workflow dispatch,
  Cloud Run/Firebase/IAM/Tasks mutation을 실행하지 않음

## 외부 승인 경계

로컬 구현이 통과한 뒤 사용자가 직접 별도 승인해야 하는 항목은 다음과 같다.

1. [staging-deployment Environment 설정](https://github.com/WBmaker2/rhwp/settings/environments)
   을 위 계획과 동일하게 적용하고 read-back한다.
2. [GitHub Actions](https://github.com/WBmaker2/rhwp/actions)에서 source/run/artifact/packet
   입력을 확인하고 workflow dispatch를 승인한다.
3. `execute_mutation=true`를 포함하는 실제 cloud mutation 실행은 별도 명시 승인을 받는다.
