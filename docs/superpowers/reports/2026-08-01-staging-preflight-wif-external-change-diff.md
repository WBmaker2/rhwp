# `staging-preflight` 전용 read-only WIF 외부 변경 diff

**작성일:** 2026-08-01
**대상 브랜치:** `feat/firebase-collaboration-mvp-v1`
**상태:** 외부 적용 전 검토 대기

이 문서는 `Staging configuration`의 deployment live preflight가 사용할 **조회 전용** 인증 경계를
정의한다. 이 문서 작성과 검토 준비에서는 GCP·Firebase·GitHub 설정을 변경하지 않았다.

## 현재 관찰 사실

- 현재 Google 계정의 활성 project와 staging project는 read-only로 확인했다.
- 기존 `rhwp-github-actions` pool과 `rhwp-staging-apply` provider는 infrastructure apply 전용이다.
- 기존 apply deployer service account에는 create 계열 권한이 있으므로 preflight identity로 재사용하지 않는다.
- 현재 staging project에는 Cloud Run service와 Cloud Tasks queue가 없다. 최초 runtime 배포는
  worker bootstrap 이후에 task URL을 확정하는 2단계 경로를 사용한다.
- `staging-preflight` Environment에는 비밀이 아닌 운영 변수 9개가 있고, WIF secret은 아직 없다.
- 현재 Task 5 workflow 변경은 로컬 uncommitted 상태다. 따라서 아직 원격에 고정된
  `staging-config-validate.yml` workflow SHA가 없다.

## 제안하는 외부 변경

아래 이름은 기존 `rhwp-*` naming과 workflow secret 이름에서 파생한 제안이다. 실제 적용 전에 이
이름과 권한 범위를 승인받는다.

| 대상 | 제안값 | 변경 |
|---|---|---|
| Workload Identity pool | 기존 `rhwp-github-actions` 재사용 | 없음 |
| OIDC provider ID | `rhwp-staging-preflight` | 신규 생성 |
| service account ID | `rhwp-staging-preflight-reader` | 신규 생성 |
| GitHub Environment | `staging-preflight` | 기존 보호 규칙 유지 |
| Environment secret | `GCP_WORKLOAD_IDENTITY_PROVIDER` | 신규 등록, resource name만 |
| Environment secret | `GCP_PREFLIGHT_SERVICE_ACCOUNT` | 신규 등록, service-account email만 |

서비스 계정 이름은 secret payload나 credential이 아니다. private key, service-account key JSON,
access token, ID token, Authorization header는 생성·저장·출력하지 않는다.

## WIF provider 조건

provider는 기존 apply provider와 분리한다. 다음 값은 고정하고, 마지막 workflow SHA만 실제 원격
commit을 push한 뒤 채운다.

```text
issuer: https://token.actions.githubusercontent.com
audience mode: default provider resource
repository: WBmaker2/rhwp
ref: refs/heads/feat/firebase-collaboration-mvp-v1
workflow ref: WBmaker2/rhwp/.github/workflows/staging-config-validate.yml@refs/heads/feat/firebase-collaboration-mvp-v1
workflow SHA: <REMOTE_COMMIT_SHA_CONTAINING_THIS_WORKFLOW>
```

제안하는 CEL 조건은 다음과 같다.

```text
attribute.repository == 'WBmaker2/rhwp' &&
attribute.repository_id == '<APPROVED_REPOSITORY_ID>' &&
attribute.repository_owner_id == '<APPROVED_REPOSITORY_OWNER_ID>' &&
attribute.ref == 'refs/heads/feat/firebase-collaboration-mvp-v1' &&
attribute.workflow_ref == 'WBmaker2/rhwp/.github/workflows/staging-config-validate.yml@refs/heads/feat/firebase-collaboration-mvp-v1' &&
attribute.workflow_sha == '<REMOTE_COMMIT_SHA_CONTAINING_THIS_WORKFLOW>'
```

workflow SHA를 추측하거나 현재 로컬 HEAD로 대신 입력하지 않는다. push 뒤 `git rev-parse`와
`gh api`로 원격 commit과 workflow bytes를 다시 확인하고, 그 exact SHA로만 provider를 만든다.

## 서비스 계정 권한 diff

읽기 전용 preflight가 호출하는 명령은 project, billing association, enabled API, Cloud Run,
Cloud Tasks, Secret Manager **metadata**, service account, project IAM policy, Artifact Registry
repository metadata, Firebase project 목록 조회뿐이다. secret version payload를 읽지 않는다.

제안하는 binding은 다음과 같다.

```diff
+ project: roles/viewer
+ billing account: roles/billing.viewer
```

`roles/viewer`는 조회 전용이며 `secretmanager.versions.access`, create, update, delete, deploy,
service-account key 생성 권한을 포함하지 않는다. `roles/billing.viewer`는 billing association을
조회하기 위한 billing-scope binding으로만 적용하고, secret·token·payment credential은 취급하지
않는다. 적용 전 IAM diff에서 실제 binding scope가 project/billing-account에 정확히 맞는지 확인한다.

다음 권한은 부여하지 않는다.

```text
roles/owner
roles/editor
roles/iam.serviceAccountUser
roles/iam.workloadIdentityUser
roles/run.admin
roles/cloudtasks.admin
roles/secretmanager.admin
roles/storage.admin
roles/artifactregistry.admin
```

preflight service account에는 다른 service account의 `roles/iam.workloadIdentityUser` binding도
추가하지 않는다. WIF provider는 이 service account에 대해서만 GitHub OIDC subject를 허용한다.

## GitHub Environment diff

Environment 보호 규칙과 9개 비밀 아닌 변수는 기존 상태를 유지한다. 다음 두 secret만 resource
identifier로 추가한다.

```diff
Environment: staging-preflight
+ Secret: GCP_WORKLOAD_IDENTITY_PROVIDER
+ Secret: GCP_PREFLIGHT_SERVICE_ACCOUNT
```

secret values는 local report, commit, log, artifact, screenshot에 남기지 않는다. 적용 후에는
`gh secret list --env staging-preflight`로 **이름만** 확인하고, 값을 read-back하지 않는다.

## 적용 전 순서

1. 현재 local 변경을 테스트·검토하고, 사용자가 승인한 경우에만 PR #1에 commit/push한다. PR은
   Draft/open/unmerged 상태로 유지한다.
2. push된 commit SHA와 `staging-config-validate.yml` bytes를 read-only로 확인한다.
3. 위 provider ID와 service account ID를 exact하게 승인받은 뒤 GCP에서 provider·service account와
   read-only binding을 적용한다.
4. provider resource name과 service account email만 `staging-preflight` Environment secret에
   등록한다.
5. GCP IAM policy, provider mapping/condition/state, GitHub Environment secret names를 다시
   read-only로 attestation한다.
6. source-commit-bound release metadata가 없으면 live preflight를 dispatch하지 않는다.

## 승인 요청

현재 사용자에게 필요한 결정은 다음 두 가지뿐이다.

1. **원격 workflow SHA가 필요하므로**, 현재 Task 5 로컬 변경을 검증한 뒤 PR #1에 commit/push하는
   것을 승인할지 여부
2. 위의 `rhwp-staging-preflight` provider와 `rhwp-staging-preflight-reader` service account,
   `roles/viewer`(project) + `roles/billing.viewer`(billing account) diff를 그대로 적용할지 여부

두 승인이 없으면 외부 WIF/IAM/Environment 변경과 live workflow dispatch를 실행하지 않는다.

## 이 단계에서 수행하지 않은 작업

- Firebase/GCP 리소스 생성·삭제·API 활성화·IAM mutation
- Cloud Run, Cloud Tasks, Firebase Hosting/Rules deployment
- image build/push
- secret value, API key, internal flush token, private key 저장
- workflow dispatch
