# Staging deployment executor·WIF 로컬 구현 결과

작성일: 2026-08-02 (Asia/Seoul)
대상 브랜치: `feat/firebase-collaboration-mvp-v1`
상태: 로컬 구현·회귀 검증 및 WIF/IAM/Environment 준비 완료, 최신 `execute_mutation=true` dispatch는 첫 사전관찰 오류에서 fail-closed 중단

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
같은 실행에 존재하지 않으면 fail-closed합니다. 따라서 이번 단계에서는 Cloud Run·Cloud
Tasks·Firebase·Secret Manager 리소스 mutation이나 deployment를 실행하지 않았습니다.

## 검증 결과

실행한 명령:

```bash
python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v
ruby -e 'require "yaml"; YAML.load_file(".github/workflows/staging-deployment.yml")'
git diff --check
```

결과:

- 전체 회귀 테스트: **253 passed**
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

## 외부 identity 준비와 이전 차단 기록

이번 외부 준비에서 다음 항목을 적용했습니다.

- deployment 전용 WIF provider `rhwp-staging-deployment`를 생성했습니다.
- provider 상태·mapping·condition을 read-back했으며 `ACTIVE`입니다. 당시 첫 적용은
  `90ddf598ff3b1f0fc100cfde17cdcbde9a6a3043`에 고정되었습니다.
- executor 서비스 계정
  `rhwp-staging-deploy-executor@rhwp-collaboration-staging-001.iam.gserviceaccount.com`를
  생성했습니다.
- 해당 서비스 계정에는 지정된 repository ID principalSet에만
  `roles/iam.workloadIdentityUser`를 바인딩했습니다.

다음 외부 준비를 추가로 적용하고 모두 read-back했습니다.

- `stagingDeploymentExecutor` custom role 생성
- executor service account에 custom role 프로젝트 바인딩
- `staging-deployment` Environment에 다음 식별자 secret 2개 등록
  - `GCP_DEPLOY_WORKLOAD_IDENTITY_PROVIDER`
  - `GCP_DEPLOY_SERVICE_ACCOUNT`

`execute_mutation=true` workflow dispatch는 승인 후 실행했지만, WIF attribute condition
불일치로 Cloud 인증 전에 fail-closed 중단되었습니다. Cloud Run, Cloud Tasks, Firebase,
Secret Manager mutation은 시작되지 않았습니다.

## 보호 dry-run 첫 시도와 수정

첫 보호 dry-run [run 30744046298](https://github.com/WBmaker2/rhwp/actions/runs/30744046298)은
prepare 단계와 Environment 승인까지 통과했지만, deploy job이 executor Python 모듈을
읽을 `actions/checkout`을 누락하여 `ModuleNotFoundError: No module named 'scripts'`로
fail-closed 중단되었습니다. credential 발급과 Cloud mutation 단계는 실행되지 않았습니다.

deploy job에 보호 executor source checkout과 계약 테스트를 추가해 커밋
`90ddf598ff3b1f0fc100cfde17cdcbde9a6a3043`로 push했고, 그 결과 WIF provider condition도
동일 SHA로 갱신·read-back했습니다. 다음 dispatch는 이 새 workflow SHA를 사용해야 합니다.

수정 후 재실행한 보호 dry-run [run 30744264388](https://github.com/WBmaker2/rhwp/actions/runs/30744264388)은
prepare와 보호 Environment 승인, same-run packet 검증 및 bounded plan 생성에 성공했습니다.
`execute_mutation=false`이므로 WIF auth와 apply 단계는 `skipped`였고, Cloud mutation은
없었습니다. execution evidence artifact의 exact-byte SHA-256은 다음과 같습니다.

- `plan-evidence.json`: `0fa324214aaf075a0b968d1b66e20e2e5b8fec631f536bacfa03052f74aa05aa`
- `post-evidence.json`: `1b0238c2dc1b9c79e170f75e8fde68151b53d5a0d47ff94c50543a3a24d198c3`
- 두 evidence 모두 packet SHA `54a54e80b49d6c5693ed08cc34cf7a6c6f75a005afe4779004620575c7de0858`,
  source commit `29c4c037b2a307a056f4801e248558311337b979`, approval reference
  `staging-bootstrap-approval-2026-07-27-001`에 묶여 있습니다.
- 계획된 canonical action은 19개이며 `mutationCommands=[]`, `executedActionIds=[]`입니다.

workflow 파일이 새 commit으로 바뀌면 provider condition의 workflow SHA도 바뀌므로, 현재
제안값을 바로 외부에 적용하면 fail-closed가 깨질 수 있습니다. 따라서 다음 순서는
의도한 파일의 커밋·push 후 새 workflow SHA를 read-back하고, 그 SHA를 포함한 WIF/IAM/
Environment diff를 별도로 승인받는 것입니다.

## 실제 `execute_mutation=true` dispatch 결과

사용자가 실제 Cloud mutation dispatch를 승인한 뒤 [run 30744607226](https://github.com/WBmaker2/rhwp/actions/runs/30744607226)을
실행했습니다. 결과는 다음과 같습니다.

- `Prepare exact approved deployment input`: 성공
- `staging-deployment` protected Environment: 사용자 승인 완료
- same-run packet/artifact/approval/source binding: 성공
- bounded plan 생성: 성공, `mode=dry-run`, `executedActionIds=[]`, `mutationCommands=[]`
- `Authenticate deployment executor with Workload Identity Federation`: 실패
- 오류: `unauthorized_client: The given credential is rejected by the attribute condition.`
- gcloud 설정·executor apply·execution evidence upload: 실행 전 skip
- run conclusion: `failure`

실패 원인은 self-review 또는 public invoker가 아닙니다. read-only로 확인한 WIF provider
조건은 다음 workflow SHA에 고정되어 있습니다.

```text
현재 WIF attribute.workflow_sha = 90ddf598ff3b1f0fc100cfde17cdcbde9a6a3043 (이전 run 시점)
실제 dispatch head SHA           = f29c0fcb8997bbd8915e6bf202d2501afb5c4743
```

GitHub OIDC의 `workflow_sha`는 workflow provenance에 묶인 commit SHA이며, 이 저장소의
앞선 WIF 차단·수정 사례와 같은 방식으로 실행 source commit과 비교해야 합니다. 이번
run은 조건 불일치가 인증 응답으로 확인되었지만, OIDC token 원문은 로그에 남기지 않았습니다.
이후 사용자의 승인으로 provider의 `attribute.workflow_sha`를 실제 dispatch source SHA인
`f29c0fcb8997bbd8915e6bf202d2501afb5c4743`로 갱신·read-back했고, 최신 run에서 WIF 인증이
성공했습니다. 이 값은 현재 원격 workflow에 대한 값이며, 아래 로컬 수정 push 후에는 새
원격 workflow SHA로 다시 갱신해야 합니다.

제안 diff:

```diff
- attribute.workflow_sha == '90ddf598ff3b1f0fc100cfde17cdcbde9a6a3043'
+ attribute.workflow_sha == 'f29c0fcb8997bbd8915e6bf202d2501afb5c4743'
```

이번 실패는 OIDC 인증 단계에서 발생했으므로 Cloud credential 발급, Cloud Run/Tasks/IAM
write, Firebase/Secret Manager mutation, deployment는 없었습니다. 동일 run 재시도는 하지
않으며, WIF diff 승인 전에는 새 dispatch도 하지 않습니다.

## 권한 부여 차단 기록

`stagingDeploymentExecutor` custom role은 사용자가 아래 최소 후보 권한 전체를 명시 승인한
뒤 생성했습니다. 역할이나 더 넓은 predefined role로 우회하지 않았습니다.

후보 permission 목록:

```text
run.locations.get
run.operations.get
run.revisions.get
run.services.create
run.services.get
run.services.update
run.services.getIamPolicy
run.services.setIamPolicy
cloudtasks.locations.get
cloudtasks.queues.create
cloudtasks.queues.get
cloudtasks.queues.getIamPolicy
cloudtasks.queues.setIamPolicy
resourcemanager.projects.get
resourcemanager.projects.getIamPolicy
resourcemanager.projects.setIamPolicy
storage.buckets.getIamPolicy
storage.buckets.setIamPolicy
secretmanager.secrets.getIamPolicy
secretmanager.secrets.setIamPolicy
iam.serviceAccounts.get
iam.serviceAccounts.getIamPolicy
iam.serviceAccounts.setIamPolicy
iam.serviceAccounts.actAs
artifactregistry.repositories.get
artifactregistry.repositories.downloadArtifacts
serviceusage.services.get
serviceusage.services.use
```

read-back 결과 custom role의 stage는 `GA`이고 위 목록과 정확히 일치했습니다. 프로젝트
IAM에는 executor 서비스 계정의 해당 role 바인딩이 하나만 존재하며, 서비스 계정 정책에는
지정된 repository ID principalSet의 `roles/iam.workloadIdentityUser`만 존재합니다.
Environment에는 secret 이름 2개가 존재하고 secret 원문은 출력하지 않았습니다.

## 추적 상태 및 안전성

- PR #1은 Draft/open/unmerged 상태를 유지해야 합니다.
- 실제 packet 원문은 수정·pretty-print·재저장하지 않았습니다.
- access token, ID token, Authorization header, password, private key,
  service-account key, Firebase API key 원문, internal flush token 원문을 파일·로그에
  저장하지 않았습니다.
- 기존 사용자가 만든 dirty/untracked 파일은 staging 대상에서 제외합니다.
- Cloud Run·Cloud Tasks·Firebase·Secret Manager 리소스 mutation과 deployment는 없었습니다.
- 다만 승인된 외부 준비의 일환으로 WIF provider, executor service account와 해당 계정의
  `roles/iam.workloadIdentityUser` 바인딩은 적용되었습니다.
- executor custom role, 프로젝트 IAM role binding과 GitHub Environment 식별자 secret은
  적용되었습니다.

## 최신 실제 실행과 원인 분석

WIF 조건을 실제 dispatch head에 맞춘 뒤 실행한 [run 30745179965](https://github.com/WBmaker2/rhwp/actions/runs/30745179965)은 다음까지 성공했습니다.

- prepare job: 성공
- `staging-deployment` protected Environment 승인: 성공
- same-run packet/artifact/approval/source binding: 성공
- WIF 인증: 성공
- bounded executor apply: 첫 action `cloud-run-collaboration`의 read-only 사전관찰에서 중단

실패 메시지는 `precondition observation failed for cloud-run-collaboration`입니다. 이는
self-review, public invoker, WIF 인증 실패가 아닙니다. read-only Cloud 확인 결과 대상
서비스 `rhwp-collaboration-staging`은 아직 존재하지 않고, 현재 존재하는 Cloud Run 서비스는
`rhwp-document-worker-staging`뿐이며 Cloud Tasks queue도 없습니다. executor는 첫 action의
관찰 단계에서 중단했으므로 write 단계에 진입하지 않았습니다.

원인은 gcloud의 미존재 오류가 `Cannot find service [...]` 형태인데 observer가 이를
`not found`로 인식하지 못한 구현 결함이었습니다. 다음 로컬 수정으로 이를 교정했습니다.

- `scripts/staging_deployment_observer.py`: `cannot find service`를 명시적 not-found 관찰로
  처리하되 permission/API 오류는 계속 오류로 유지
- `.github/workflows/staging-deployment.yml`: 실패 시에도 execution evidence를 보존하도록
  artifact upload를 `if: always()`와 `if-no-files-found: warn`으로 변경
- observer/workflow contract 회귀 테스트 추가

로컬 수정은 전체 253개 테스트, workflow YAML parse, `git diff --check`를 통과했습니다.
이 수정은 아직 원격에 push하지 않았습니다. 따라서 Cloud mutation을 다시 실행하지 않았고,
실행 evidence artifact가 없는 최신 실패는 원격 workflow의 기존 성공 조건 때문이며 다음
workflow commit부터는 실패 evidence를 보존합니다.

## 다음 승인 필요

로컬 구현과 외부 identity 준비가 완료되었습니다. 외부 실행을 계속하려면 다음 두 단계가
분리되어야 합니다.

1. **완료:** fresh packet/preflight artifact로 `execute_mutation=false` 보호 workflow를 실행했습니다.
2. **완료:** WIF 조건을 `f29c0fcb8997bbd8915e6bf202d2501afb5c4743`에 맞춘 뒤 `run 30745179965`에서
   WIF 인증까지 성공했습니다.
3. **완료:** 최신 실패를 read-only로 reconcile했고 Cloud write가 없음을 확인했습니다.
4. **로컬 준비 완료:** observer와 실패 evidence 보존 수정 및 253개 회귀 테스트를 완료했습니다.
5. 다음 외부 작업은 이 수정의 커밋·push입니다. push 후 원격 workflow commit SHA가 바뀌므로
   WIF provider의 `attribute.workflow_sha`도 새 원격 SHA로 별도 갱신·read-back해야 합니다.
6. WIF read-back이 exact 일치한 뒤에만 새 `execute_mutation=true` dispatch를 요청합니다.
7. 실제 mutation 성공 후에도 acceptance/rollback evidence가 없으면 verify job은
   fail-closed이며, 다음 배포 단계로 진행하지 않습니다.

현재는 로컬 수정과 문서 기록까지만 진행하고, push·WIF 갱신·새 실제 mutation dispatch는
사용자의 새 명시 승인 전에는 실행하지 않습니다.
