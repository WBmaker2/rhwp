# Staging Phase C — platform identity policy and same-run artifact bridge

작성일: 2026-08-02 (Asia/Seoul)

## 현재 경계

- branch: `feat/firebase-collaboration-mvp-v1`
- 현재 작업 시작 HEAD: `71f084d9fad18bf3514da9dcd50d5d833b79b739`
- PR #1: Draft / open / not merged
- 이번 단계는 로컬 구현과 검증만 수행했습니다.
- GCP/Firebase 리소스 생성·삭제, Cloud Run/Tasks 배포, API 활성화, Secret 값 변경,
  IAM 또는 WIF 외부 설정 적용, workflow dispatch는 아직 수행하지 않았습니다.

## 구현 결과

### 플랫폼 서비스 계정 분류

`deploy/staging/staging-manifest.json`의 `iam.platformServiceAccounts`에 다음
5개 계정을 placeholder 기반으로 명시했습니다. 이 필드는 권한을 부여하지 않고,
live preflight에서 관찰된 플랫폼 관리 계정을 예상 자원으로 분류하는 기준입니다.

- Firebase Admin SDK 서비스 계정
- `rhwp-infra-deployer-staging`
- `rhwp-staging-preflight-reader`
- `rhwp-staging-release-pusher`
- `rhwp-staging-runtime-bootstrap`

`scripts/staging_preflight.py`는 이 배열의 빈 값·중복을 거부하고, 배열 항목을
expected service-account set에 포함합니다. 기존 `iam.bindings`와 역할은 변경하지
않았습니다.

### same-run release/worker artifact bridge

`.github/workflows/staging-config-validate.yml`의 protected `deployment` job에
다음 입력을 추가했습니다.

- release run ID / attempt / artifact name / artifact server digest
- worker run ID / attempt / artifact name / artifact server digest

job은 credential 인증 전에 다음을 fail-closed로 검증합니다.

1. 각 run이 같은 `GITHUB_SHA`의 completed/success run인지 확인
2. 지정 run에 해당 artifact가 정확히 하나이고 server digest가 입력과 일치하는지 확인
3. artifact에서 release/worker evidence JSON이 각각 정확히 하나인지 확인
4. 원문 evidence bytes의 SHA-256과 source/run/attempt/artifact binding을 검증
5. `scripts/staging_runtime_release_metadata.py`로 파생 metadata만 생성
6. 파생 metadata로 deployment manifest를 만든 뒤 static preflight 수행
7. 그 이후에만 WIF 인증과 read-only live query 수행

기존 `release_metadata_path` 입력은 호환성 설명만 남기고 deployment metadata의
source로 사용하지 않습니다. metadata는 GitHub Environment 변수나 추적 파일에
넣지 않습니다. 원문 evidence는 formatter, key sort, pretty-print 또는 재저장하지
않습니다.

## 로컬 검증

- `python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v` — **230 tests passed**
- `python3 scripts/validate_staging_config.py` — 통과
- `git diff --check` — 통과
- workflow YAML Ruby parser — 통과
- 새 platform account 분류 단위 테스트 — 통과
- 이전 release/worker evidence를 이전 source SHA로 읽기 전용 재검증 — 통과
- materialized bootstrap/deployment static preflight — `pass`
- 모든 로컬 실행 결과의 `mutationCommands` — `[]`

이전 evidence는 source SHA `71f084d9fad18bf3514da9dcd50d5d833b79b739`에 묶여
있으므로 새 커밋의 원격 release/worker 증거로 사용하지 않습니다.

## 변경 파일 및 추적 상태

이번 단계에서 scope에 포함할 파일:

- 수정: `.github/workflows/staging-config-validate.yml`
- 수정: `deploy/staging/staging-manifest.json`
- 수정: `scripts/staging_preflight.py`
- 수정: `scripts/staging_deployment_manifest.py` (direct script import fallback)
- 수정: `scripts/tests/test_staging_preflight.py`
- 수정: `scripts/tests/test_staging_deployment_manifest.py`
- 신규: `scripts/staging_runtime_release_metadata.py`
- 신규: `scripts/tests/test_staging_runtime_release_metadata.py`
- 신규: `docs/superpowers/plans/2026-08-02-staging-phase-c-remote-artifact-bridge.md`
- 신규: 본 보고서

기존의 다른 untracked 문서, `.chatgpt2codex/`, `node_modules/` 등은 scope 밖이며
stage하지 않습니다. readiness local 입력과 `artifacts/`는 `.gitignore` 대상입니다.

## 다음 단계

1. 위 scope 파일만 stage하고 commit/push합니다.
2. 새 commit SHA를 release, runtime bootstrap, preflight WIF attribute condition에
   반영할 exact diff를 read-only로 확인한 후 적용합니다.
3. 새 SHA로 release candidate를 1회 실행하고, 성공 artifact의 run ID/attempt/name/
   server digest/exact evidence SHA를 기록합니다.
4. 그 release artifact만 worker bootstrap에 전달해 1회 실행하고, worker artifact
   근거를 기록합니다.
5. 두 same-run artifact 입력으로 deployment live preflight를 1회 실행합니다.
6. fresh packet이 생성되면 packet exact-byte SHA와 run-bound 근거를 정리하고,
   실제 Cloud Run/Tasks/Firebase mutation 전 별도 승인 경계에서 중단합니다.

## 안전 확인

`cloudMutationApproved=false`, `deploymentApproved=false`, `mutationCommands=[]`를
유지했습니다. 토큰, ID token, Authorization header, password, private key,
service-account key, Firebase API key 원문, internal flush token 원문은 파일·로그·
스크린샷에 기록하지 않았습니다.
