# RHWP 개인용 staging deployment 작업 인수인계 기록

작성일: 2026-08-02 (Asia/Seoul)
저장소: `WBmaker2/rhwp`
브랜치: `feat/firebase-collaboration-mvp-v1`
HEAD: `50e8ad787956754e0a9b8e8e57d1d1e64e9413ba`
PR: [#1](https://github.com/WBmaker2/rhwp/pull/1) — Draft / open / unmerged

이 문서는 다음 작업을 재개할 때 사용할 현재 상태와 남은 단계를 기록한다. 이 작업은
사용자의 개인용 fork/브랜치에서 기능을 검증하는 목적이며, 원래 `main`에 병합하는 작업이
아니다.

## 1. 저장소·병합 경계

- 현재 push 대상은 `origin=https://github.com/WBmaker2/rhwp.git`이다.
- `upstream` remote는 설정되어 있지 않다.
- PR #1의 base는 `devel`이며 `main`이 아니다.
- PR #1은 Draft/open/unmerged 상태를 유지하고 있다.
- 이 회차에는 PR을 ready로 바꾸거나 merge/close하지 않았다.

따라서 현재 변경은 `WBmaker2/rhwp` 안의 개인용 feature branch에서만 진행 중이며, 원본
`main`으로 병합된 상태가 아니다.

## 2. 지금까지 완료한 작업

### 2.1 실패 원인 확인

이전 mutation run [30745736401](https://github.com/WBmaker2/rhwp/actions/runs/30745736401)은
WIF와 protected Environment 승인까지 통과했지만, 첫 Cloud Run 배포에서 컨테이너가
`PORT=8080`을 열지 못해 실패했다. read-only 관찰 결과는 다음과 같다.

- `rhwp-collaboration-staging` 서비스와 실패 revision
  `rhwp-collaboration-staging-00001-z6l`이 부분 생성됨
- 실패 원인: 필수 환경변수·Secret Manager reference가 Cloud Run deploy argv에 포함되지 않음
- `rhwp-document-api-staging`은 존재하지 않음
- Cloud Tasks parse/export queue는 존재하지 않음
- Secret 값 자체는 읽지 않았고, secret metadata만 확인함
- 실패 리소스를 이 회차에 삭제하거나 재배포하지 않음

이는 self-review, public invoker, WIF attribute condition 자체가 아니라 실행기에서
runtime configuration을 전달하지 않은 구현 결함이었다.

### 2.2 recovery 구현

다음 8개 파일을 선택적으로 commit했다.

- `scripts/staging_deployment_runtime_contract.py`
- `scripts/staging_deployment_prepare.py`
- `scripts/staging_deployment_executor.py`
- `scripts/staging_deployment_observer.py`
- `scripts/tests/test_staging_deployment_executor.py`
- `scripts/tests/test_staging_deployment_prepare.py`
- `docs/superpowers/plans/2026-08-02-staging-deployment-executor-wif.md`
- `docs/superpowers/reports/2026-08-02-staging-deployment-executor-wif-implementation.md`

주요 변경:

- Cloud Run 서비스별 승인된 평문 환경변수와 Secret Manager reference만 고정 argv에 추가
- secret 원문·token·private key를 argv, 로그, artifact에 넣지 않도록 계약화
- collaboration 배포 후 read-after 관찰된 `run.app` URL을 document API 설정에 전달
- 실패했지만 승인된 image digest/service account/ingress/runtime identity가 일치하는
  기존 service는 삭제하지 않고 bounded repair 대상으로 분류
- 다른 identity의 실패 service는 `incompatible`로 fail-closed 차단
- packet 원문 bytes와 approval reference/source binding은 그대로 유지

Commit/push:

- commit: `50e8ad787956754e0a9b8e8e57d1d1e64e9413ba`
- message: `fix: bind staging Cloud Run runtime configuration`
- 원격 `origin/feat/firebase-collaboration-mvp-v1`과 HEAD 일치 확인

### 2.3 로컬 검증

```text
python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v  -> 256 passed
python3 -m py_compile scripts/staging_deployment_runtime_contract.py \
  scripts/staging_deployment_executor.py \
  scripts/staging_deployment_observer.py \
  scripts/staging_deployment_prepare.py                         -> pass
git diff --check                                                    -> pass
```

### 2.4 WIF와 fresh dry-run

WIF provider read-only 조회 결과:

- provider state: `ACTIVE`
- `attribute.workflow_sha`: `23cfc84eda9ce6ebb68c7b43225651bdd13acfbd`
- 이 값은 workflow YAML의 마지막 변경 commit이며, recovery commit은 workflow YAML을
  바꾸지 않았으므로 조건을 갱신하지 않았다.

fresh dry-run [30747671509](https://github.com/WBmaker2/rhwp/actions/runs/30747671509):

- `execute_mutation=false`
- Prepare job: success
- Protected deployment gate: success
- WIF authentication: skipped
- Cloud mutation: skipped
- Post-deployment evidence guard: skipped by contract
- execution evidence artifact digest:
  `sha256:b2af734533a45f98e21df7029afe0a3ebc6f5bd7dd663ae4292b3fdba715b1ef`
- `mutationCommands=[]`
- `containsCredentials=false`
- `containsSecretValues=false`
- plan/post evidence status: `dry-run-complete`

동일성 검증값:

- packet source commit: `29c4c037b2a307a056f4801e248558311337b979`
- packet workflow run: `30738684540`, attempt `1`
- packet exact-byte SHA-256: `54a54e80b49d6c5693ed08cc34cf7a6c6f75a005afe4779004620575c7de0858`
- approval reference: `staging-bootstrap-approval-2026-07-27-001`

## 3. 현재 외부 상태와 안전 경계

- 기존 partial Cloud Run service/revision은 남아 있다.
- recovery 구현 이후 실제 Cloud mutation/deployment는 아직 실행하지 않았다.
- secret value, access token, ID token, Authorization header, private key는 기록하지 않았다.
- Firebase/GCP 리소스 삭제, 재생성, API 활성화, IAM 변경, WIF 변경, build/push/deploy는
  이 회차에 실행하지 않았다.
- protected Environment 승인은 dry-run job을 통과시키기 위해 사용되었을 뿐, Cloud mutation
  승인으로 간주하지 않는다.

## 4. 다음에 이어서 할 작업

### 단계 A — mutation 직전 read-only 재확인

1. `rhwp-collaboration-staging`의 현재 service/revision/Ready 상태를 다시 조회한다.
2. image digest, service account, ingress, runtime identity가 승인 packet과 일치하는지
   확인한다.
3. document API, worker, Cloud Tasks queue, IAM binding의 현재 상태를 다시 조회한다.
4. 다른 identity가 관찰되면 즉시 fail-closed로 중단하고 새 승인 자료를 만든다.

### 단계 B — 별도 실제 mutation 승인

다음은 dry-run 성공만으로 자동 실행하지 않는다.

- `execute_mutation=true` workflow dispatch
- `staging-deployment` protected Environment 승인
- read-before/write/read-after 방식의 bounded recovery
- 기존 실패 service를 무조건 삭제하지 않고 identity 일치 여부에 따라 repair

Workflow 링크:
https://github.com/WBmaker2/rhwp/actions/workflows/staging-deployment.yml

### 단계 C — 실행 후 증거와 acceptance

1. 각 Cloud Run/Cloud Tasks/IAM action의 plan·post evidence를 수집한다.
2. partial failure가 발생하면 다음 action으로 넘어가지 않고 read-only 상태를 먼저
   재조사한다.
3. 실제 acceptance/rollback evidence가 존재하는지 확인한다. 없는 결과를 생성하거나
   승인자·시각·acknowledgement를 추측하지 않는다.
4. acceptance가 통과한 경우에만 최종 배포 결과와 개인용 사용 경계를 기록한다.

## 5. 재개 시 확인할 명령

```bash
cd /Users/kimhongnyeon/Dev/codex/rhwp
git status --short
git branch --show-current
git rev-parse HEAD
gh pr view 1 --repo WBmaker2/rhwp --json state,isDraft,mergedAt,baseRefName,headRefName,headRefOid,url
gh run view 30747671509 --json status,conclusion,headSha,jobs,url
```

실제 mutation을 실행할 때는 위 dry-run의 packet binding을 다시 대조하고, 새 workflow
run URL과 protected Environment 승인 상태를 먼저 확인한다. 실행 실패 시 같은 명령을
무작정 반복하지 않는다.

## 6. Git 추적·변경 상태

- 이 인수인계 문서는 이번 회차에 새로 작성한 로컬 Markdown이다.
- 이 문서 자체는 아직 commit/push하지 않았다.
- 기존 사용자 변경/미추적 파일은 수정·삭제·정리하지 않았다.
- recovery source commit과 workflow dry-run 결과는 원격에서 확인 가능하다.

이 문서를 기준으로 다음 세션은 **단계 A read-only 재확인**부터 시작하고, 실제 mutation은
그 결과를 사용자에게 보고한 후 별도 명시 승인을 받아 진행한다.

## 7. 2026-08-06 read-only 재확인 결과

이번 재개에서 다음 외부 조회를 수행했다.

```text
gcloud projects describe rhwp-collaboration-staging-001
gcloud run services describe/get-iam-policy (협업·API·worker)
gcloud run services list
gcloud tasks queues list
gcloud projects/secrets/buckets get-iam-policy
gcloud iam workload-identity-pools providers describe
```

결과:

- project `rhwp-collaboration-staging-001` / number `598693744358`: `ACTIVE`
- WIF provider: `ACTIVE`; workflow SHA condition은 여전히 workflow commit
  `23cfc84eda9ce6ebb68c7b43225651bdd13acfbd`와 일치
- `rhwp-collaboration-staging`: 실패 revision
  `rhwp-collaboration-staging-00001-z6l`, `Ready=False`, reason
  `HealthCheckContainerError`
- 협업 service의 image digest, service account, ingress `all`은 승인 packet과 일치하며
  환경변수/Secret reference가 아직 없어 bounded repair 대상으로 확인됨
- `rhwp-document-worker-staging`: 승인된 image digest로 `Ready=True`, latest revision
  `rhwp-document-worker-staging-00004-vpl`, ingress `internal`
- `rhwp-document-api-staging`: 아직 없음
- Cloud Tasks parse/export queue: 아직 없음
- 협업/API/worker service IAM policy: 아직 없음
- secret IAM policy와 project `roles/datastore.user` binding: 아직 없음
- bucket에는 기본 legacy binding만 있고 승인된 object role은 아직 없음
- service account 4개는 존재하고 disabled 상태가 아니며, secret 원문은 읽지 않음

따라서 다음 실제 실행은 새 리소스를 무조건 삭제하는 작업이 아니라, 승인된 identity를
재확인한 뒤 협업 service를 runtime configuration과 함께 repair하고 나머지 승인된
서비스·queue·IAM binding을 순서대로 반영하는 bounded mutation이어야 한다.

## 8. 2026-08-06 실제 mutation dispatch 상태

사용자의 별도 실행 승인을 받아 다음 고정 입력으로 실제 workflow를 한 번 dispatch했다.

```text
run: 31085011423
head: 50e8ad787956754e0a9b8e8e57d1d1e64e9413ba
source commit: 29c4c037b2a307a056f4801e248558311337b979
packet run: 30738684540 (attempt 1)
packet artifact: staging-approval-packet-deployment
packet artifact digest: sha256:810b5be50c06b513b68487961ef4ca3c2bfc3b336f25a2997eb265660ea7f3e5
packet exact-byte SHA-256: 54a54e80b49d6c5693ed08cc34cf7a6c6f75a005afe4779004620575c7de0858
execute_mutation: true
```

현재 결과:

- Prepare exact approved deployment input: 성공
- Protected deployment gate (`staging-deployment`): 사용자 승인 대기
- WIF 인증, gcloud setup, executor apply: 아직 시작되지 않음
- 따라서 이번 run에서는 현재까지 Cloud mutation이 발생하지 않음

실제 보호 승인이 완료된 뒤에만 mutation job을 관찰한다. mutation job 또는 post-
deployment evidence guard가 실패하면 즉시 중단하고 read-only 재조사로 전환하며, 같은
packet/run을 무작정 재실행하지 않는다.

실행 링크: https://github.com/WBmaker2/rhwp/actions/runs/31085011423

## 9. 2026-08-06 실제 dispatch WIF 차단 결과

실행 [31085011423](https://github.com/WBmaker2/rhwp/actions/runs/31085011423)은
protected Environment 승인 후 다음 단계에서 fail-closed 중단되었다.

- Prepare exact approved deployment input: 성공
- same-run approval/source/artifact/packet binding: 성공
- bounded deployment plan: 성공
- WIF 인증: 실패 (`unauthorized_client`, `credential is rejected by the attribute condition`)
- gcloud setup: skip
- bounded deployment actions: skip
- post-deployment evidence guard: skip
- Cloud mutation: 없음

read-only provider read-back과 run head:

```text
provider: projects/598693744358/locations/global/workloadIdentityPools/rhwp-github-actions/providers/rhwp-staging-deployment
state: ACTIVE
workflow_ref: WBmaker2/rhwp/.github/workflows/staging-deployment.yml@refs/heads/feat/firebase-collaboration-mvp-v1
현재 attribute.workflow_sha: 23cfc84eda9ce6ebb68c7b43225651bdd13acfbd
실제 run head SHA:          50e8ad787956754e0a9b8e8e57d1d1e64e9413ba
```

따라서 self-review, public invoker, packet, Environment 승인이 원인이 아니다.
현재 WIF 조건이 이전 workflow provenance SHA에 고정되어 실제 dispatch의
`workflow_sha` claim을 거부한 것이다. GitHub OIDC reference의 `workflow_sha`는
workflow file에 대한 commit SHA claim이며, 이 저장소의 이전 worker run에서도 run
head SHA와 provider 조건을 맞춘 뒤 인증이 성공한 기록이 있다.

다음 변경은 아래 한 항목뿐이다. 사용자의 별도 승인 없이는 적용하거나 재실행하지
않는다.

```diff
- attribute.workflow_sha == '23cfc84eda9ce6ebb68c7b43225651bdd13acfbd'
+ attribute.workflow_sha == '50e8ad787956754e0a9b8e8e57d1d1e64e9413ba'
```

WIF 조건을 갱신할 때도 issuer, mapping, repository/ref/workflow_ref, provider state는
그대로 유지하고, read-back으로 exact match를 확인한 뒤에만 새 dispatch를 검토한다.

## 10. 2026-08-06 WIF 단일 SHA 갱신 결과

사용자의 별도 승인을 받아 `rhwp-staging-deployment` provider의
`attributeCondition`에서 `attribute.workflow_sha` 한 항목만 갱신했다.

```diff
- attribute.workflow_sha == '23cfc84eda9ce6ebb68c7b43225651bdd13acfbd'
+ attribute.workflow_sha == '50e8ad787956754e0a9b8e8e57d1d1e64e9413ba'
```

read-back 결과:

- provider state: `ACTIVE`
- issuer: `https://token.actions.githubusercontent.com/`
- attribute mapping: 기존 7개 mapping과 exact 일치
- repository, repository_id, repository_owner_id, ref, workflow_ref: 변경 없음
- `attribute.workflow_sha`: 승인된 새 HEAD와 exact 일치

이번 단계에서는 workflow dispatch나 Cloud mutation을 실행하지 않았다. 새
`execute_mutation=true` dispatch는 별도 승인 후 진행한다.

## 11. 2026-08-06 WIF 갱신 후 새 dispatch 상태

WIF read-back 이후 사용자의 별도 dispatch 승인을 받아 새 run을 한 번 생성했다.

```text
run: 31086064036
head: 50e8ad787956754e0a9b8e8e57d1d1e64e9413ba
source commit: 29c4c037b2a307a056f4801e248558311337b979
packet run: 30738684540 (attempt 1)
packet artifact digest: sha256:810b5be50c06b513b68487961ef4ca3c2bfc3b336f25a2997eb265660ea7f3e5
packet exact-byte SHA-256: 54a54e80b49d6c5693ed08cc34cf7a6c6f75a005afe4779004620575c7de0858
execute_mutation: true
```

현재 결과:

- Prepare exact approved deployment input: 성공
- `staging-deployment` protected gate: 사용자 승인 대기
- WIF 인증 및 Cloud mutation: 아직 시작되지 않음

실행 링크: https://github.com/WBmaker2/rhwp/actions/runs/31086064036

## 12. 2026-08-06 executor precondition mismatch 결과

새 run [31086064036](https://github.com/WBmaker2/rhwp/actions/runs/31086064036)은 WIF와
gcloud 설정까지 성공했지만, 첫 승인 action인 `cloud-run-collaboration`에서
fail-closed 중단되었다.

```text
error: staging deployment executor failed: precondition mismatch for cloud-run-collaboration
apply-post-evidence.status: failed-first-error
apply-post-evidence.executedActionIds: []
apply-post-evidence.mutationCommands: []
```

run artifact의 `apply-post-evidence.json`과 executor log를 read-only로 확인했으며, 이
run에서 Cloud write는 호출되지 않았다.

### 관측된 collaboration service

값 원문은 출력하지 않고 identity·env 이름·Secret reference·상태만 조회했다.

- service: `rhwp-collaboration-staging`
- generation: `1`
- image digest: 승인 packet digest와 일치
- service account: 승인 packet service account와 일치
- 환경변수 이름: 없음
- Secret reference: 없음
- latest created revision: `rhwp-collaboration-staging-00001-z6l`
- Ready: `False`
- reason: `HealthCheckContainerError` (PORT=8080으로 listen하지 못함)

### 구현상의 실제 blocker

현재 `scripts/staging_deployment_observer.py`는 Cloud Run의 image·service account·
ingress·runtime 전체가 원하는 값과 일치하고 Ready인 경우만 `present`로 분류한다.
기존 부분 실행 서비스는 image와 service account는 맞지만 runtime/env configuration이
불완전하고 Ready가 아니므로 `incompatible`로 분류된다. executor는
`incompatible`에서 즉시 중단하도록 설계되어 있어, 승인된 digest와 identity를 가진
실패 service를 bounded repair할 수 없다.

이것은 self-review, WIF, public invoker, packet 또는 Environment 승인 문제가 아니라
**partial Cloud Run service를 repair 대상으로 분류하지 못하는 executor precondition
contract gap**이다.

### 다음 구현 경계

새 dispatch나 기존 run 재시도 전에 다음을 별도 구현·검증해야 한다.

1. immutable identity(image digest, service name, service account, ingress)가 승인값과
   일치하지만 runtime/env가 불완전하고 Ready가 아닌 경우를 `repairable-missing`으로
   분류한다.
2. image digest·service account·ingress가 다르거나 다른 service identity인 경우에는
   계속 `incompatible`로 fail-closed한다.
3. repairable fixture와 incompatible fixture를 각각 추가해 precondition 회귀 테스트를
   작성한다. 삭제·무조건 재배포 경로는 추가하지 않는다.
4. 코드 push 후 새 HEAD에 맞는 WIF `workflow_sha` exact diff를 다시 검토하고, 별도
   dispatch 및 protected Environment 승인을 거친다.

현재는 이 구현 gap 때문에 중단하며, 같은 packet/run의 재시도·Cloud Run 삭제·수동
   gcloud deploy를 실행하지 않는다.

## 13. 2026-08-06 partial Cloud Run precondition 로컬 보정 결과

사용자의 구현 승인을 받아 이번 단계에서 로컬 계약만 수정했다. 실제 Cloud Run,
WIF, GitHub Environment, IAM, Firebase, Cloud Tasks 변경과 workflow 재실행은 하지
않았다.

### 구현 내용

- `scripts/staging_deployment_observer.py`
  - Cloud Run repair 안전 경계를 service name, 승인 image digest, service account,
    ingress의 immutable identity로 분리했다.
  - identity가 일치하고 runtime/env 또는 Ready가 부족한 service는 `missing`으로
    분류해 기존 bounded deploy argv가 repair하도록 했다.
  - image, service account, ingress 중 하나라도 다르면 계속 `incompatible`로
    fail-closed한다.
- `scripts/tests/test_staging_deployment_executor.py`
  - 실제 관측 형태처럼 runtime/env가 빠진 non-ready partial service가 `missing`인지
    검증했다.
  - identity는 맞지만 runtime이 불완전한 Ready service도 `missing`으로 분류되는지
    검증했다.
  - 기존 wrong-image fixture의 `incompatible` 차단을 유지했다.

### 로컬 검증

```text
focused: python3 -m unittest scripts.tests.test_staging_deployment_executor -v
         11 tests, OK
full:    python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v
         258 tests, OK
syntax:  python3 -m py_compile scripts/staging_deployment_observer.py scripts/tests/test_staging_deployment_executor.py
diff:    git diff --check
config:  python3 scripts/validate_staging_config.py
         staging manifest and configuration templates are valid; no deployment was performed
```

로컬 보정 커밋 `54578c27c7f4ada841802338c520ffffeb6b752e`를 생성하고 PR branch에
push했다. PR #1은 계속 Draft·Open·미병합이다. 다음 외부 경계는 새 HEAD에 맞춘 WIF
`workflow_sha` 단일 diff의 별도 승인과 read-back, 새 packet/run-bound dispatch 및
protected Environment 승인이다. 그 경계를 통과하기 전에는 같은 packet 재실행이나
Cloud mutation을 하지 않는다.

## 14. 2026-08-06 보정 커밋 push 및 WIF 재확인

### Git 상태

- branch: `feat/firebase-collaboration-mvp-v1`
- pushed HEAD: `54578c27c7f4ada841802338c520ffffeb6b752e`
- PR: https://github.com/WBmaker2/rhwp/pull/1
- PR 상태: Draft·Open·미병합

### WIF read-only 결과

provider `rhwp-staging-deployment`는 `ACTIVE`이고 issuer/mapping/repository/ref/
workflow ref는 유지되고 있다. 현재 read-back에서 확인된 차이는 다음 한 항목뿐이다.

```diff
- attribute.workflow_sha == '50e8ad787956754e0a9b8e8e57d1d1e64e9413ba'
+ attribute.workflow_sha == '54578c27c7f4ada841802338c520ffffeb6b752e'
```

이 diff는 아직 적용하지 않았다. WIF 변경, 새 workflow dispatch, protected
Environment 승인, Cloud Run/IAM/Firebase/Cloud Tasks mutation은 수행하지 않았다.
