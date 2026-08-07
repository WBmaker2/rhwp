# Staging Infrastructure Deployment 작업 중단·재개 기록

> 이 문서는 Task 3 진행 중 작성된 과거 기록이다. Task 3 완료 이후의 현재 재개 기준은
> `docs/superpowers/reports/2026-07-30-staging-infrastructure-task3-handoff.md`를 따른다.

**기록일:** 2026-07-27  
**중단 사유:** 사용자가 현재 흐름의 안전한 중단점에서 멈추고 다음 작업에서 재개하도록 요청함  
**현재 단계:** SDD Task 3 fix round 1 재리뷰 완료, fix round 2 대기
**실제 배포 상태:** 미실행

## 1. Git 상태

### PR 브랜치 checkout

- 저장소: `WBmaker2/rhwp`
- 로컬 경로: `/Users/kimhongnyeon/Dev/codex/rhwp`
- 브랜치: `feat/firebase-collaboration-mvp-v1`
- 로컬 HEAD: `af54d8eb99ce15d0e75783f9c9283c3dfd60b41a`
- 원격 PR #1 HEAD: `2ae37993e09e0a52350f6be639d8341e880f708d`
- PR 상태: Draft, open, unmerged
- 사용자 소유 untracked 경로: `.chatgpt2codex/` — 변경하거나 추적하지 않음

### SDD 격리 worktree

- 경로: `/Users/kimhongnyeon/Dev/codex/rhwp/.worktrees/staging-deployment-completion`
- 브랜치: `codex/staging-deployment-completion`
- 현재 HEAD: `a519a9cf`
- Task 3 최초 구현: `9155285b`
- Task 3 fix round 1: `a519a9cf`
- SDD ledger:
  `.superpowers/sdd/2026-07-27-staging-infrastructure-deployment-completion/progress.md`
- SDD workspace 전체는 Git ignored scratch이며 제품 산출물로 추적하지 않는다.

Task 3 커밋은 아직 PR 브랜치에 통합하거나 push하지 않았다.

## 2. 완료된 작업

### Task 1 — infrastructure approval validator 계약 충돌 수정

- `plan.security.secretValuesIncluded`는 boolean `false`일 때만 허용한다.
- 문자열 `"false"`, `true`, 다른 타입, flattened dotted key, 중첩·철자 변형은 거부한다.
- 실제 기존 plan의 문자열 타입 문제를 발견하여 안전하게 plan을 재생성했다.
- 사용자가 다음 regenerated plan exact-byte digest를 승인했다.

```text
499f9fcfcc23d84518d244a060eaf8c164fbed9f2fc1a53585a7948a906bb93a
```

- actual validator 결과:
  - `awaiting-cloud-mutation-approval`
  - `cloudMutationApproved=false`
  - `deploymentApproved=false`
  - `mutationCommands=[]`
- Task 1 독립 리뷰: PASS / APPROVED
- PR 브랜치 통합 커밋: `af54d8eb`

### Task 2 — actual apply review package

- actual plan, approval result, execution manifest, readiness, apply review package를
  ignored `artifacts/actual-infrastructure-review/regenerated-safe/`에 생성했다.
- package를 재저장하지 않고 원문 바이트 SHA-256을 계산했다.
- 승인된 v1 package digest:

```text
3a26cb46d37ff8e65c2bdf3e474ff36623d9fcfb14d22582f68a03f5d656256e
```

- 사용자가 package, canonical subset, 제안 설정 diff 및 Task 3 구현을 승인했다.
- Task 2 독립 리뷰: PASS / APPROVED
- actual 산출물 18개는 모두 Git ignored/untracked다.

> 중요: Task 3 fix round 1이 package/approval schema를 v2로 강화했다. 따라서 위 v1 package는
> 실제 apply 권한으로 사용할 수 없으며, 최종 executor commit이 PR 브랜치에 통합된 뒤 v2 package를
> 다시 생성하고 새 exact-byte 사람 승인을 받아야 한다.

## 3. Task 3 현재 구현

Task 3은 실제 외부 실행 없이 apply executor와 protected workflow를 구현하는 단계다.

### 추가·수정된 주요 파일

- `.github/workflows/staging-infrastructure-apply.yml`
- `scripts/staging_infrastructure_apply_approval.py`
- `scripts/staging_infrastructure_apply_executor.py`
- `scripts/staging_infrastructure_apply_provenance.py`
- `scripts/staging_infrastructure_apply_review.py`
- `scripts/tests/test_staging_infrastructure_apply_executor.py`
- `scripts/tests/test_staging_infrastructure_apply_review.py`
- `docs/runbooks/staging-infrastructure-bootstrap.md`
- `docs/superpowers/reports/2026-07-27-staging-infrastructure-apply-executor-result.md`

### 최초 리뷰에서 확인된 Important 결함

1. actual GitHub context가 아니라 protected 변수끼리 비교하는 provenance 자기 검증
2. 실행할 수 없는 cross-run artifact download 계약
3. live read-before/write/read-after와 재실행 no-op 부재
4. package nested schema·sensitive/executable field 검증 부족
5. 폐기된 `upload-artifact` v3 SHA 사용
6. runbook의 구현 상태 모순

최초 Task 3 리뷰 판정은 `Spec FAIL / CHANGES_REQUESTED`였다.

### Fix round 1 구현 내용

- package/approval schema를 v2로 변경했다.
- actual GitHub runtime context와 protected expected 값을 분리했다.
- executor commit/tree, workflow content, repository/ref/workflow identity를 결합했다.
- cross-run artifact source run/ID/name/source commit/archive digest 검증을 추가했다.
- 승인 record에 run ID, run attempt, nonce, expiry를 추가했다.
- actual apply에서 fixed read-only precondition과 postcondition observation을 필수화했다.
- 이미 exact desired state이면 write 없이 `already-present-noop`으로 처리한다.
- package top-level·nested action schema와 action-set digest를 엄격하게 검증한다.
- 지원되는 artifact action의 immutable SHA를 사용하도록 수정했다.
- focused 18개, 전체 172개 테스트, staging validator, `py_compile`, diff check를 통과했다.

### Fix round 1 scoped re-review 결과

- 판정: `Spec FAIL / Quality CHANGES_REQUESTED`
- Critical: 없음
- 기존 Important 2개 해결:
  - cross-run artifact 운반과 metadata 바인딩
  - 폐기된 `upload-artifact` v3 교체
- 아직 해결되지 않은 기존 Important:
  1. `sourceEvidence.sourceCommitSha`가 실제 checked-out Git object 또는 승인 artifact source commit과
     독립 결합되지 않고 package 값의 자기 비교로 남아 있다.
  2. live observer가 모든 `gcloud` exit code 1을 `missing`으로 해석한다. 권한 거부·API 장애도 create
     대상으로 오인할 수 있고, repository format 등 exact desired state를 비교하지 않는다.
  3. write 뒤 postcondition 관찰 실패 시 sanitized failure post-evidence가 남지 않는다.
  4. package 전역에서 `secrets`·`idToken` 등의 키가 과도하게 허용되며 일부 중첩 구조 검증이 부족하다.
  5. v2 package가 `requiredApprovalRecordSchema`를 v1로 광고하지만 executor validator는 v2만 받는다.
  6. runbook, 생성 package, example approval record, 일부 테스트의 v1/v2 계약이 서로 일치하지 않는다.
- 추가 보완 사항:
  - 미래 `approvedAt` 차단과 승인 유효기간 상한
  - pinned action 주석과 실제 release 버전 일치
  - 오래된 non-release `setup-gcloud` pin 교체 또는 공식 지원 근거

따라서 Task 3은 완료되지 않았으며 PR 브랜치에 통합하지 않는다. 다음 작업은 fix round 2로 재개한다.

## 4. 남은 구조적 검토 사항

다음 작업에서 scoped re-review 결과와 함께 아래 항목을 우선 확인한다.

1. `sourceEvidence.sourceCommitSha`가 실제 checked-out Git object 및 승인 artifact source commit과
   독립적으로 결합되는가.
2. v2 package builder가 최종 executor commit을 실제로 결합하여 재생성 가능한가.
3. `github.repository_id`, `github.repository_owner_id`, `github.workflow_sha`,
   `github.workflow_ref`가 실제 GitHub context에서 공급되고 expected 값과 독립 비교되는가.
4. `gcloud` 관찰 명령이 not-found와 permission/API/transient failure를 확실히 구분하는가.
5. Artifact Registry format 등 exact desired state와 postcondition을 검증하는가.
6. write/postcondition 실패 때 partial failure evidence가 원자적으로 남는가.
7. package/approval record를 source artifact로 게시하는 안전한 actual publication workflow가 있는가.
8. 승인 record가 apply `run_id`와 `run_attempt`에 결합되는 현재 계약에서 다음 순서가 실제로 가능한가.
   - apply run 생성
   - run ID 확인
   - 사람 승인 record 작성
   - 승인된 artifact 게시
   - protected environment 승인 후 같은 run에서 다운로드·검증
9. 동일 승인을 재사용해도 두 번째 실행에서 mutation write가 0회인지 실제 stateful test가 보장하는가.
10. API, service account, Artifact Registry, Secret metadata의 observed state가 단순 존재 여부뿐 아니라
   승인된 desired state와 정확히 일치하는지 검증하는가.
11. v2 package, v2 approval example, validator, runbook과 테스트가 같은 schema를 선언하는가.

4번과 5번을 만족하는 actual evidence publication 단계가 없다면 Task 4로 넘어가지 말고 별도 구현
Task를 추가한다.

## 5. 다음 작업의 정확한 재개 순서

1. 격리 worktree와 SDD ledger를 확인한다.
2. Task 3 fix round 1 재리뷰 결과의 미해결 Important 항목을 구현자에게 전달한다.
3. fix round 2로 같은 구현자를 재개한다.
4. 각 수정 뒤 scoped re-review를 반복한다. 최대 5회 breaker를 유지한다.
5. Task 3이 PASS / APPROVED가 되면 전체 브랜치 final review를 수행한다.
6. 검증된 Task 3 순 변경만 PR 브랜치에 통합한다.
7. PR 브랜치에서 전체 테스트·validator·diff check를 다시 실행한다.
8. PR #1을 Draft·open·미병합 상태로 유지한 채 승인된 로컬 커밋을 push한다.
9. 원격에 존재하는 최종 executor commit SHA로 v2 actual apply review package를 재생성한다.
10. v2 package 원문 SHA-256과 actual Environment/WIF/IAM diff를 사용자에게 제시하고 별도 승인을 받는다.
11. 승인 후에만 `staging-infrastructure-apply` Environment와 actual WIF/IAM을 적용한다.
12. cloud mutation approval record와 actual apply workflow dispatch 승인을 별도로 받는다.
13. canonical infrastructure apply 성공·증거 검증 뒤에만 별도 deployment approval 단계로 넘어간다.

## 6. 아직 실행하지 않은 외부 변경

다음 작업은 모두 미실행이다.

- Task 3 변경의 PR 브랜치 통합·push
- GitHub `staging-infrastructure-apply` Environment 생성·수정
- Environment variable 등록
- WIF provider/service account 생성·수정
- IAM binding 또는 custom role 변경
- GCP API enable
- service account 생성
- Artifact Registry repository 생성
- Secret Manager secret metadata 생성
- actual apply workflow dispatch
- cloud authentication
- build·image push
- Cloud Run/Tasks/Firebase deployment
- secret 값 또는 장기 credential 변경

현재까지 cloud mutation, deployment, secret 변경은 0건이다.

## 7. 재개 시 승인 경계

현재 사용자의 승인은 Task 3 구현까지다. 다음 승인은 순서대로 별개다.

1. 최종 v2 actual apply review package exact-byte 승인
2. actual Environment 설정 diff 승인
3. actual WIF identity와 live IAM before/after diff 승인
4. `cloudMutationApproved=true` record 승인
5. actual apply workflow dispatch 승인
6. infrastructure post-apply evidence 승인
7. `deploymentApproved=true` record 승인
8. build·push·deployment workflow dispatch 승인

앞 단계의 승인을 뒤 단계 권한으로 확대 해석하지 않는다.
