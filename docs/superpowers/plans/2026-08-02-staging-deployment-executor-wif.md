# Staging deployment executor·WIF 구현 계획

작성일: 2026-08-02 (Asia/Seoul)
대상 브랜치: `feat/firebase-collaboration-mvp-v1`
상태: 로컬 구현·WIF/IAM/Environment 준비 완료, 실제 Cloud mutation 미실행

## 목적

현재 `staging-deployment` workflow는 exact-byte packet과 same-run approval artifact를
검증하고 `execute_mutation=false`에서 안전하게 끝난다. 다음 구현은 이 경계를 유지한 채,
승인된 deployment packet의 immutable image digest와 IAM diff만 사용하는 최소 권한 executor를
로컬에서 검증 가능하게 만든다.

실제 WIF provider, service account, IAM binding, Cloud Run/Tasks/Firebase mutation은 이 계획의
정확한 diff를 외부에서 read-back한 뒤 별도 승인이 없으면 실행하지 않는다.

## 읽기 전용 기준

- project: `rhwp-collaboration-staging-001` (number `598693744358`)
- region: `asia-northeast3`
- deployment 전용 WIF provider: 현재 없음
- 기존 apply provider: `staging-infrastructure-apply.yml`의 다른 workflow SHA에 고정되어
  deployment workflow에 재사용하지 않음
- 현재 Cloud Run: `rhwp-document-worker-staging`만 존재
- 현재 Cloud Tasks queue: 없음
- 현재 secret metadata: `rhwp-collaboration-internal-token-staging` 존재
- 현재 승인 packet의 `mutationCommands`: `[]`
- 현재 승인 packet의 13개 IAM diff: packet 원문과 approval record의 exact binding으로만 소비

## 외부 identity diff 및 적용 상태

| 항목 | 제안값 | 적용 조건 |
| --- | --- | --- |
| WIF pool | `projects/598693744358/locations/global/workloadIdentityPools/rhwp-github-actions` | 기존 pool 유지 |
| WIF provider | `rhwp-staging-deployment` | OIDC provider 신규 생성 완료, mapping·condition·ACTIVE 상태 read-back 완료 |
| provider mapping | `google.subject=assertion.sub`, `attribute.repository=assertion.repository`, `attribute.repository_id=assertion.repository_id`, `attribute.repository_owner_id=assertion.repository_owner_id`, `attribute.ref=assertion.ref`, `attribute.workflow_ref=assertion.workflow_ref`, `attribute.workflow_sha=assertion.workflow_sha` | mapping·condition read-back이 정확히 일치해야 함 |
| provider condition | `repository`, repository/owner IDs, `refs/heads/feat/firebase-collaboration-mvp-v1`, `WBmaker2/rhwp/.github/workflows/staging-deployment.yml@refs/heads/feat/firebase-collaboration-mvp-v1`, 최종 workflow commit SHA | 최종 workflow commit을 push한 뒤 SHA를 확정하고 provider를 원자적으로 갱신 |
| executor service account | `rhwp-staging-deploy-executor@rhwp-collaboration-staging-001.iam.gserviceaccount.com` | 생성 완료, custom role 및 WIF 사용자 바인딩 read-back 완료 |
| GitHub Environment secret | `GCP_DEPLOY_WORKLOAD_IDENTITY_PROVIDER` | provider resource name만 저장, token/key 원문 금지, 등록 완료 |
| GitHub Environment secret | `GCP_DEPLOY_SERVICE_ACCOUNT` | service-account email만 저장, key 원문 금지, 등록 완료 |

## 최소 권한 설계

executor는 project-wide owner/editor 또는 service-account key를 사용하지 않는다. 다음 작업에
필요한 permission만 별도 custom role 또는 Google 관리 role의 최소 조합으로 검토한다.

1. Cloud Run 서비스 create/update와 desired runtime/image digest 관찰
2. 배포 대상 runtime service account를 사용하는 Cloud Run 배포 권한
3. Cloud Run service IAM policy의 `roles/run.invoker` read/set
4. Cloud Tasks queue create/update와 queue IAM policy read/set
5. project IAM binding의 read/set (packet의 세 가지 `roles/datastore.user`만)
6. bucket/secret IAM policy의 read/set (packet에 명시된 principal·role만)
7. 기존 Artifact Registry 이미지 digest read

`roles/owner`, `roles/editor`, `roles/iam.serviceAccountKeyAdmin`, service-account key 생성,
raw secret read, Firebase API key read는 허용하지 않는다. 실제 permission 목록은 custom role
설계 diff에 기록하고, `gcloud iam roles describe`와 project/service IAM read-back으로 확인한다.

## 로컬 구현 순서

1. `scripts/staging_deployment_executor.py`에 cloud-free validator와 고정 argv/observer 계약을
   추가한다.
   - packet/review/evidence/approval record의 exact binding을 재검증한다.
   - 13개 packet IAM diff 중 허용된 resource·role만 canonical order로 허용한다.
   - 모든 write는 `apply=false`에서 명령만 계획하고 실행하지 않는다.
   - `apply=true`에서도 고정된 read-before/write/read-after와 first-error evidence를 필수화한다.
   - not-found와 permission/API 오류를 구분하며, 오류를 `missing`으로 변환하지 않는다.
   - secret value, token, header, key, raw Firebase API key를 출력·저장하지 않는다.
2. `staging-deployment` workflow를 same-run artifact 검증 후에만 OIDC auth와 executor를 호출하도록
   연결한다. OIDC 식별자가 없거나 `execute_mutation=true` 승인 입력이 없으면 fail-closed한다.
3. executor spec·WIF/IAM diff·workflow contract 테스트를 추가한다.
4. 전체 테스트와 실제 packet을 이용한 `execute_mutation=false` 검증을 수행한다.

## 외부 적용 순서 및 현재 경계

1. 최종 workflow commit SHA를 확인한다.
2. WIF provider와 executor service account를 생성하고 provider mapping, condition,
   principal을 read-back한다. **완료**
3. 승인된 custom role/IAM binding을 적용하고 role 권한과 project/service IAM을 read-back한다.
   **완료**
4. `staging-deployment` Environment에 두 공개 식별자만 secret으로 등록하고 값은 로그에
   출력하지 않는다. **완료**
5. 새 same-run packet/approval artifact로 `execute_mutation=false` workflow를 먼저 실행한다.
6. 사용자가 실제 mutation과 deployment를 별도로 승인한 경우에만 `execute_mutation=true`를
   실행한다.
7. Cloud Run revision, Tasks queue, IAM before/after, acceptance/rollback evidence를 생성하고
   실패 시 즉시 중단한다.

## 중단 기준

- provider condition이 최종 workflow SHA와 다름
- executor service account가 예상 이름·project와 다름
- custom role에 최소 범위를 넘는 permission이 포함됨
- Environment secret에 raw credential이 있거나 이름/값 read-back이 불일치함
- packet/approval/source/run/artifact SHA가 하나라도 불일치함
- observer가 permission/API 오류를 missing으로 해석함
- postcondition 또는 acceptance evidence가 없음

이 기준을 만족하지 못하면 cloud credential, mutation, deployment를 실행하지 않고 보고서와
다음 승인 지점만 남긴다. 현재는 identity 준비가 완료되었지만 fresh same-run dry-run과
실제 acceptance/rollback evidence가 아직 남아 있다.
