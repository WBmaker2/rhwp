# Staging deployment executor·WIF 로컬 구현 결과

작성일: 2026-08-02 (Asia/Seoul)
대상 브랜치: `feat/firebase-collaboration-mvp-v1`
상태: 로컬 구현·회귀 검증 완료, 외부 WIF/IAM/Environment 적용 전

## 이번 단계에서 구현한 것

### 실행 계약

- `scripts/staging_deployment_executor.py`
  - same-run prepared bundle을 다시 검증합니다.
  - source commit, packet workflow run/attempt, artifact digest, exact-byte packet SHA,
    approval reference를 재검산합니다.
  - Cloud Run 3개, Cloud Tasks queue 2개, 승인된 IAM diff 13개를 canonical action으로
    제한합니다. queue IAM 1개 항목은 실제 queue 2개 binding action으로만 분해됩니다.
  - 기본 모드는 `dry-run`이며 `mutationCommands=[]`를 유지합니다.
  - apply 모드에서도 고정 argv, read-before/write/read-after, first-error evidence를
    요구합니다. shell·자유 형식 명령·credential/key 출력은 허용하지 않습니다.

- `scripts/staging_deployment_observer.py`
  - Cloud Run, Cloud Tasks, project/resource IAM policy의 read-only 관찰만 수행합니다.
  - not-found와 permission/API 오류를 구분합니다. 오류를 `missing`으로 바꾸지 않습니다.
  - desired image digest, runtime, service account, ingress, queue retry/rate limit,
    IAM member/role을 비교합니다.

### protected workflow

`.github/workflows/staging-deployment.yml`의 protected `deploy` job을 다음 순서로 고정했습니다.

```text
same-run artifact 검증
  → credential 없이 bounded plan 생성
  → execute_mutation=true인 경우에만 Environment WIF secret으로 OIDC 인증
  → 고정 executor apply(read-before/write/read-after)
  → execution evidence 업로드
```

`execute_mutation=false`가 기본값이며, `verify` job은 실제 acceptance/rollback evidence가
같은 실행에 존재하지 않으면 fail-closed합니다. 따라서 이번 단계에서는 cloud mutation이나
deployment를 실행하지 않았습니다.

## 검증 결과

실행한 명령:

```bash
python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v
ruby -e 'require "yaml"; YAML.load_file(".github/workflows/staging-deployment.yml")'
git diff --check
```

결과:

- 전체 회귀 테스트: **251 passed**
- workflow YAML parse: 통과
- whitespace check: 통과
- 새 executor contract 테스트: 통과
- 실제 승인 packet을 사용한 local `execute_mutation=false` 실행: 통과
- local dry-run 결과: `dry-run-complete`
- plan evidence SHA-256: `0fa324214aaf075a0b968d1b66e20e2e5b8fec631f536bacfa03052f74aa05aa`
- post evidence SHA-256: `1b0238c2dc1b9c79e170f75e8fde68151b53d5a0d47ff94c50543a3a24d198c3`

실제 packet binding은 기존 승인 값과 일치합니다.

- packet workflow run: `30738684540`, attempt `1`
- source commit: `29c4c037b2a307a056f4801e248558311337b979`
- artifact: `staging-approval-packet-deployment`
- artifact server digest: `sha256:810b5be50c06b513b68487961ef4ca3c2bfc3b336f25a2997eb265660ea7f3e5`
- packet JSON exact-byte SHA-256: `54a54e80b49d6c5693ed08cc34cf7a6c6f75a005afe4779004620575c7de0858`
- approval reference: `staging-bootstrap-approval-2026-07-27-001`

## 외부 적용 전 설계

계획 문서 [`2026-08-02-staging-deployment-executor-wif.md`](../plans/2026-08-02-staging-deployment-executor-wif.md)에
다음 diff를 기록했습니다.

- 기존 WIF provider를 재사용하지 않고 deployment 전용 provider `rhwp-staging-deployment`를
  사용합니다.
- executor 전용 service account
  `rhwp-staging-deploy-executor@rhwp-collaboration-staging-001.iam.gserviceaccount.com`를
  사용합니다.
- GitHub Environment에는 token/key가 아닌 두 공개 식별자만 secret으로 등록합니다.
  - `GCP_DEPLOY_WORKLOAD_IDENTITY_PROVIDER`
  - `GCP_DEPLOY_SERVICE_ACCOUNT`
- provider condition은 최종 workflow commit SHA를 push한 뒤에만 확정합니다.
- 최소 권한 role/IAM binding은 적용 전에 diff와 read-back으로 검토합니다.

## 현재 차단 지점

아직 다음 외부 변경은 하지 않았습니다.

- deployment 전용 WIF provider 생성/변경
- executor service account 생성
- custom role 또는 project/resource IAM binding
- `staging-deployment` Environment secret 등록
- `execute_mutation=true` workflow dispatch
- Cloud Run, Cloud Tasks, Firebase, Secret Manager mutation

workflow 파일이 새 commit으로 바뀌면 provider condition의 workflow SHA도 바뀌므로, 현재
제안값을 바로 외부에 적용하면 fail-closed가 깨질 수 있습니다. 따라서 다음 순서는
의도한 파일의 커밋·push 후 새 workflow SHA를 read-back하고, 그 SHA를 포함한 WIF/IAM/
Environment diff를 별도로 승인받는 것입니다.

## 추적 상태 및 안전성

- PR #1은 Draft/open/unmerged 상태를 유지해야 합니다.
- 실제 packet 원문은 수정·pretty-print·재저장하지 않았습니다.
- access token, ID token, Authorization header, password, private key,
  service-account key, Firebase API key 원문, internal flush token 원문을 파일·로그에
  저장하지 않았습니다.
- 기존 사용자가 만든 dirty/untracked 파일은 staging 대상에서 제외합니다.
- cloud mutation, deployment, secret 변경은 이번 단계에 없었습니다.

## 다음 승인 필요

로컬 구현은 완료되었습니다. 외부 적용을 계속하려면 다음 두 단계가 분리되어야 합니다.

1. 의도한 구현 파일만 PR 브랜치에 커밋·push하고, 새 workflow SHA를 확인합니다.
2. 새 SHA를 반영한 WIF provider·executor SA·최소 IAM·Environment secret의 정확한 diff를
   검토한 뒤, 별도 명시 승인으로 외부에 적용합니다.

그 전까지는 `execute_mutation=false` 검증만 허용하며, cloud credential과 mutation은
실행하지 않습니다.
