# Staging deployment workflow 로컬 구현 결과

작성일: 2026-08-02 (Asia/Seoul)
대상 브랜치: `feat/firebase-collaboration-mvp-v1`
현재 HEAD: `29c4c037b2a307a056f4801e248558311337b979`
상태: 로컬 diff 검토 대기; GitHub push·Environment 적용·workflow dispatch·cloud mutation 미실행

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

## 추적 및 외부 변경 상태

- 새 workflow, helper, tests, 계획/보고서, approval bundle은 현재 작업 tree에서 아직
  **untracked**입니다. 기존 사용자가 만든 dirty 변경은 건드리지 않았습니다.
- 실제 packet과 operator-local artifact는 `.gitignore`의 `/artifacts/`에 의해 계속 제외됩니다.
- access token, ID token, Authorization header, password, private key, service-account key,
  Firebase API key 원문, internal flush token 원문을 추가하지 않았습니다.
- GitHub `staging-deployment` Environment를 만들거나 수정하지 않았습니다.
- GitHub secret/variable, WIF, IAM, Cloud Run, Firebase, Cloud Tasks를 변경하지 않았습니다.
- push와 workflow dispatch를 실행하지 않았습니다.

## 다음 단계

1. 이 로컬 diff를 먼저 검토합니다.
2. [staging-deployment Environment 설정](https://github.com/WBmaker2/rhwp/settings/environments)을
   생성하고 required reviewer/branch restriction/WIF secret·변수를 별도 승인 후 적용합니다.
3. [GitHub Actions](https://github.com/WBmaker2/rhwp/actions)에서 새 workflow를 확인하고,
   packet run/artifact/server digest/exact packet SHA를 입력해 `execute_mutation=false`로
   보호 경계를 먼저 확인합니다.
4. 실제 mutation executor 구현과 `execute_mutation=true` dispatch는 별도 명시 승인을 받은
   뒤에만 진행합니다. 현재 workflow는 그 입력을 의도적으로 거부합니다.
