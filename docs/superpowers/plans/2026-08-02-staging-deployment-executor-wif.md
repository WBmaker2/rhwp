# Staging deployment executor·WIF 구현 계획

작성일: 2026-08-02 (Asia/Seoul)
대상 브랜치: `feat/firebase-collaboration-mvp-v1`
상태: 로컬 구현·WIF/IAM/Environment 준비 완료, 최신 `execute_mutation=true` dispatch는 첫 Cloud Run write 후 startup health check 오류로 fail-closed 중단

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
| provider condition | `repository`, repository/owner IDs, `refs/heads/feat/firebase-collaboration-mvp-v1`, `WBmaker2/rhwp/.github/workflows/staging-deployment.yml@refs/heads/feat/firebase-collaboration-mvp-v1`, 현재 `23cfc84eda9ce6ebb68c7b43225651bdd13acfbd` | commit `23cfc84`로 push한 뒤 갱신·read-back했고 run `30745736401`에서 WIF 인증이 성공했다 |
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
5. 새 same-run packet/approval artifact로 `execute_mutation=false` workflow를 먼저 실행한다. **run 30744264388 성공**
6. 사용자가 실제 mutation과 deployment를 별도로 승인한 경우에만 `execute_mutation=true`를
   실행한다. 최신 dispatch `30745736401`은 WIF 인증과 첫 사전관찰을 통과했지만,
   `cloud-run-collaboration` write 뒤 컨테이너 startup health check에서 실패했다.
   따라서 재실행하지 않고 read-only 원인 reconcile 후 별도 recovery 승인으로 되돌린다.
7. Cloud Run revision, Tasks queue, IAM before/after, acceptance/rollback evidence를 생성하고
   실패 시 즉시 중단한다.

## 중단 기준

- provider condition이 최종 workflow SHA와 다름
- executor service account가 예상 이름·project와 다름
- custom role에 최소 범위를 넘는 permission이 포함됨
- Environment secret에 raw credential이 있거나 이름/값 read-back이 불일치함
- packet/approval/source/run/artifact SHA가 하나라도 불일치함
- observer가 permission/API 오류를 missing으로 해석함
- gcloud 리소스 미존재 오류(`Cannot find service`)를 오류로 잘못 처리함
- postcondition 또는 acceptance evidence가 없음

이 기준을 만족하지 못하면 추가 cloud credential, mutation, deployment를 실행하지 않고
보고서와 다음 승인 지점만 남긴다. 최신 run `30745736401`에서는 WIF 인증과 보호 환경 승인은
성공했지만 첫 Cloud Run write가 부분적으로 적용되어 실패한 상태이다. 후속 리소스·IAM
binding·Tasks queue는 실행되지 않았다. 로컬 observer와 실패 evidence 보존 수정은 253개
회귀 테스트를 통과했으며, 다음 단계는 컨테이너 startup 원인의 read-only 진단과 recovery
diff 검토뿐이다. 삭제·재배포·IAM/secret 변경·새 dispatch는 별도 명시 승인을 요구한다.

## 최신 실제 실행의 부분 변경과 중단 상태

commit `23cfc84eda9ce6ebb68c7b43225651bdd13acfbd`를 원격에 push하고 WIF condition을 같은
`workflow_sha`로 read-back한 뒤, 승인된 packet으로 [run 30745736401](https://github.com/WBmaker2/rhwp/actions/runs/30745736401)을
실행했다. prepare, protected Environment 승인, same-run binding, dry-run plan, WIF 인증,
gcloud setup은 모두 성공했다.

executor는 첫 action `cloud-run-collaboration`에서 `gcloud run deploy`를 호출했고, 명령은
비정상 종료했지만 Cloud Run 서비스 객체와 실패 revision이 남았다. read-only 확인 결과:

- service: `rhwp-collaboration-staging`
- revision: `rhwp-collaboration-staging-00001-z6l`
- image digest: `sha256:45ccfbbe83ab5b35e561420d9e5e691403e7f9bb53da942623a1e5cf4201d1bf`
- 상태: `HealthCheckContainerError`, `PORT=8080`에 listen하지 못함
- revision describe에서 `FIREBASE_STORAGE_BUCKET` 및 `INTERNAL_API_TOKEN` env 항목이 관찰되지 않음
- `rhwp-document-api-staging`은 여전히 없음, Cloud Tasks queue도 없음
- apply evidence: `failed-first-error`, `failedActionId=cloud-run-collaboration`,
  `executedActionIds=[]`, `mutationCommands=[]`

소스상 `_fixed_argv()`는 image·runtime·service account만 전달하고, Cloud Run service YAML에
있는 `FIREBASE_STORAGE_BUCKET`과 Secret Manager `INTERNAL_API_TOKEN` 설정을 전달하지 않는다.
따라서 애플리케이션의 필수 환경 검증을 통과하지 못해 컨테이너가 포트를 열지 못한 것이
현재 가장 직접적인 원인이다. 이는 self-review, public invoker, WIF attribute condition
문제가 아니다. 현재 경계에서는 failed service/revision을 삭제하거나 재배포하지 않는다.

## recovery 구현 결과 (2026-08-02)

최신 부분 변경 상태를 삭제하거나 재배포하지 않고, 다음 로컬 recovery 계약을 추가했다.

- `scripts/staging_deployment_runtime_contract.py`
  - Cloud Run 서비스별 승인된 평문 환경변수와 Secret Manager 참조만 도출한다.
  - collaboration은 `FIREBASE_STORAGE_BUCKET`과
    `INTERNAL_API_TOKEN=<secret>:latest`만 전달한다.
  - document worker는 bucket, worker binary path, `ALLOW_EMULATOR_TASKS=false`를 전달한다.
  - document API는 packet의 관찰된 worker target URL과 read-after-deploy로 관찰된
    collaboration `run.app` URL을 사용하며, secret 값은 읽지 않는다.
  - 모든 배포 인자는 `shell=False` 고정 argv로 만들고 raw token·key·secret value를 허용하지 않는다.
- `scripts/staging_deployment_prepare.py`
  - prepared artifact에 secret 이름만 추가하고 packet 원문은 변경하지 않는다.
- `scripts/staging_deployment_executor.py`
  - prepared secret 이름과 packet secret 이름을 exact 비교한다.
  - Cloud Run action은 runtime contract 없이는 argv를 만들 수 없다.
  - observer가 반환한 서비스 URL을 후속 document API action에 명시적으로 전달한다.
- `scripts/staging_deployment_observer.py`
  - 서비스 객체가 존재하지만 `Ready=False`인 경우 삭제하지 않고 `missing`으로 분류해
    단, 승인된 image digest·service account·ingress·runtime이 먼저 일치할 때만
    동일 서비스의 bounded repair를 허용한다.
  - `Ready=True` 서비스는 image, runtime, service account, ingress 및 승인된 env/secret
    reference가 모두 일치해야 present로 인정한다.

## recovery 로컬 검증과 외부 경계

실행한 명령:

```bash
python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v
python3 -m py_compile scripts/staging_deployment_runtime_contract.py scripts/staging_deployment_executor.py scripts/staging_deployment_observer.py scripts/staging_deployment_prepare.py
git diff --check
```

결과:

- 전체 회귀 테스트: **255 passed**
- Cloud Run argv에 평문 secret value가 포함되지 않음을 테스트
- `Ready=False` 기존 service가 승인된 identity와 일치할 때만 삭제 없이 repair 대상이 됨을 테스트
- 다른 image identity의 `Ready=False` service는 incompatible로 차단됨을 테스트
- workflow YAML 계약과 packet prepare 계약 통과
- 아직 commit·push·WIF condition 갱신·새 workflow dispatch·Cloud mutation은 하지 않음

다음 순서는 이 로컬 변경을 별도 commit으로 검토한 뒤, 사용자가 명시적으로 승인할 때만
push하고 새 원격 workflow SHA를 WIF `attribute.workflow_sha`에 read-back하는 것이다. 그
후에도 새 packet/source/run binding과 fresh `execute_mutation=false` 확인을 먼저 거치며,
실제 mutation은 별도 승인 없이는 실행하지 않는다.
