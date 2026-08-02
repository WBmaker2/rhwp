# Staging deployment workflow 로컬 구현 결과

작성일: 2026-08-02 (Asia/Seoul)
대상 브랜치: `feat/firebase-collaboration-mvp-v1`
현재 구현 commit: `03d8079563a8681217d56da66559e4aba150778f`
상태: PR 브랜치 push·protected Environment 적용·execute_mutation=false dry-run 완료; cloud mutation 미실행

## 구현한 내용

### 1. prepare validator

`scripts/staging_deployment_prepare.py`를 추가했습니다.

- deployment packet 원문 bytes의 SHA-256을 재계산합니다.
- review declaration, acceptance evidence, rollback evidence, approval record를
  `staging_deployment_approval_record.py`로 재검증합니다.
- source commit, packet workflow run/attempt, artifact 이름/digest, packet SHA를 모두
  dispatch 입력과 비교합니다.
- 승인 record를 다시 생성한 결과와 저장된 record가 다르면 중단합니다.
- `deploymentApproved=true`, `cloudMutationApproved=true`, `mutationCommands=[]`를
  확인합니다.
- packet/review/evidence/record 원문 bytes를 same-run artifact로 복사하고, 별도
  비밀값 없는 `deployment-input.json`만 파생합니다.

### 2. workflow contract

`.github/workflows/staging-deployment.yml`을 추가했습니다.

```text
prepare (id-token: none)
  → same-run staging-deployment-approved-input artifact
  → protected deploy (environment: staging-deployment, id-token: write)
  → verify guard
```

`prepare`는 GitHub API로 packet run의 head SHA, attempt, conclusion, artifact 이름, server
digest와 workflow run 결합을 확인한 후 artifact를 내려받습니다. `deploy`는 same-run
artifact의 packet bytes와 approval record를 재검증한 뒤에만 다음 단계로 넘어갑니다.
workflow dispatch ref도 `feat/firebase-collaboration-mvp-v1`로 제한합니다.

현재 구현은 `execute_mutation=false`를 안전한 기본값으로 사용합니다. `true`가 입력되어도
실제 OIDC 인증이나 cloud 명령을 실행하지 않고 명시적인 fail-closed 메시지로 중단합니다.
따라서 이 구현 자체로는 Cloud Run/Firebase/IAM/Cloud Tasks를 변경하지 않습니다.

### 3. tracked approval bundle

다음 검토용 파일을 `docs/approvals/records/staging-bootstrap-approval-2026-07-27-001/`
아래에 추가했습니다.

- `staging-deployment-packet-review.json`
- `staging-deployment-acceptance-evidence.json`
- `staging-deployment-rollback-evidence.json`
- `staging-deployment-approval-record.json`
- `staging-deployment-packet-review-result.json`
- `staging-deployment-packet-review-result.md`

이 파일들은 packet 자체가 아니며 packet 원문은 계속 GitHub artifact에서 exact bytes로
받습니다. 승인 record의 결합 기준은 다음과 같습니다.

- packet workflow run: `30738684540`, attempt `1`
- packet source commit: `29c4c037b2a307a056f4801e248558311337b979`
- packet artifact: `staging-approval-packet-deployment`
- artifact server digest: `sha256:810b5be50c06b513b68487961ef4ca3c2bfc3b336f25a2997eb265660ea7f3e5`
- packet JSON exact-byte SHA-256: `54a54e80b49d6c5693ed08cc34cf7a6c6f75a005afe4779004620575c7de0858`
- approval reference: `staging-bootstrap-approval-2026-07-27-001`

## 검증 결과

실행한 명령:

```bash
python3 -m unittest \
  scripts.tests.test_staging_deployment_prepare \
  scripts.tests.test_staging_deployment_workflow_contract \
  scripts.tests.test_staging_deployment_approval_record \
  scripts.tests.test_staging_deployment_manifest -v
python3 -m compileall -q scripts/staging_deployment_prepare.py \
  scripts/staging_deployment_approval_record.py scripts/staging_deployment_binding.py
ruby -e 'require "yaml"; YAML.load_file(".github/workflows/staging-deployment.yml")'
git diff --check
```

결과:

- 전체 `scripts/tests` 회귀 테스트: `247 passed`
- deployment prepare/approval/manifest/contract 테스트: `26 passed`
- Python compileall: 통과
- YAML parse: 통과
- whitespace check: 통과
- 실제 packet을 사용한 prepare 실행: `ready-for-protected-deployment`
- 검증된 packet SHA, source/run, approval reference: 위 결합값과 일치

## 외부 적용 및 dry-run 결과

- PR #1은 `feat/firebase-collaboration-mvp-v1`에 push했으며 Draft/open/unmerged 상태를 유지했습니다.
- workflow dispatch를 활성화하기 위해 동일한 workflow 파일만 main에 bootstrap commit
  `ce3abbedf6963e4aa01ff81cf6e750af9f441e16`으로 추가했습니다. PR #1을 merge하지 않았습니다.
- `staging-deployment` Environment에 `WBmaker2` required reviewer,
  `prevent_self_review=false`, `feat/firebase-collaboration-mvp-v1` branch policy를 적용했습니다.
- 비밀 없는 Environment 변수 12개의 이름·값을 API로 read-back했습니다.
- WIF secret은 등록하지 않았습니다. deployment 전용 WIF provider가 없고 기존 apply provider가
  다른 workflow SHA에 엄격히 묶여 있어 재사용·추측을 하지 않았습니다.
- [dry-run run 30741198223](https://github.com/WBmaker2/rhwp/actions/runs/30741198223)은
  `prepare`와 protected deploy gate가 성공했습니다. `execute_mutation=false`이므로 OIDC와
  cloud mutation은 실행되지 않았고 post-deployment verify는 skip됐습니다.
- same-run artifact의 `staging-approval-packet.json`은 원본과 `cmp`가 일치하고 exact-byte
  SHA-256은 `54a54e80b49d6c5693ed08cc34cf7a6c6f75a005afe4779004620575c7de0858`입니다.
- dry-run artifact 민감정보 scan은 clean이며 `mutationCommands=[]`를 유지했습니다.

## 추적 및 외부 변경 상태

- 새 workflow, helper, tests, 계획/보고서, approval bundle은 구현 commit으로 추적됩니다.
  기존 사용자가 만든 dirty 변경은 건드리지 않았습니다.
- 실제 packet과 operator-local artifact는 `.gitignore`의 `/artifacts/`에 의해 계속 제외됩니다.
- access token, ID token, Authorization header, password, private key, service-account key,
  Firebase API key 원문, internal flush token 원문을 추가하지 않았습니다.
- GitHub `staging-deployment` Environment 보호 규칙과 비밀 없는 변수만 변경했습니다.
- WIF secret, WIF provider, IAM, Cloud Run, Firebase, Cloud Tasks mutation은 실행하지 않았습니다.
- PR 브랜치 push와 dry-run workflow dispatch는 실행했습니다.

## 다음 단계

1. deployment 전용 WIF provider와 최소 권한 executor service account의 설계·승인을 확정합니다.
2. 공개 식별자만 `GCP_DEPLOY_WORKLOAD_IDENTITY_PROVIDER`와
   `GCP_DEPLOY_SERVICE_ACCOUNT` Environment secret에 등록합니다. 원문은 문서·로그에 남기지 않습니다.
3. 실제 OIDC/mutation executor와 post-deployment acceptance/rollback evidence를 별도 review합니다.
4. 별도 명시 승인 후에만 `execute_mutation=true`를 활성화합니다. 현재 workflow는 그 입력을
   의도적으로 fail-closed 합니다.
