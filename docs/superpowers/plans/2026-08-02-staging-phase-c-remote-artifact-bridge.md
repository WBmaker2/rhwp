# Staging Phase C — same-run release/worker artifact bridge

작성일: 2026-08-02 (Asia/Seoul)

## 목적

release candidate와 document-worker bootstrap이 만든 원문 evidence를 GitHub
Environment 변수나 추적 파일에 복사하지 않고, deployment preflight의 같은
workflow dispatch에서 run ID·attempt·artifact name·artifact server digest로
직접 내려받아 검증한다. 이 변경은 배포나 인프라 mutation을 수행하지 않으며,
오직 protected `staging-preflight` job이 인증 전에 exact binding을 검증하도록
경로를 고정한다.

## 입력 계약

deployment live dispatch는 다음 8개 run-bound 입력을 모두 요구한다.

- `release_run_id`, `release_run_attempt`
- `release_artifact_name`, `release_artifact_digest`
- `worker_run_id`, `worker_run_attempt`
- `worker_artifact_name`, `worker_artifact_digest`

입력은 지정된 run에 속한 artifact의 server digest와 일치해야 한다. workflow는
각 artifact를 `gh run download`로 내려받고, 각 evidence JSON이 정확히 하나인지
확인한 뒤 원문 바이트를 수정하지 않고 helper로 source SHA, run/attempt, image
digest, worker URL, release artifact binding을 검증한다. 파생 metadata만 새
파일로 만든다.

## 서비스 계정 분류 정책

manifest의 `iam.platformServiceAccounts`에 현재 관찰된 Firebase/admin,
infra-deployer, preflight-reader, release-pusher, runtime-bootstrap 계정을
플랫폼 관리 계정으로 명시한다. 이 목록은 권한 부여 명령이 아니며, preflight가
이미 존재하는 계정을 `unexpectedManagedResources`로 잘못 분류하지 않도록 하는
분류 기준이다. 실제 binding과 역할은 기존 `iam.bindings` 계약에 그대로 둔다.

## 구현 순서

1. manifest에 플랫폼 계정 분류 목록을 추가하고 preflight expected-resource
   계산이 이를 반영하도록 한다. 중복·빈 문자열은 fail-closed 검증한다.
2. deployment workflow에 same-run artifact 입력과 다운로드·digest·source 검증
   단계를 추가하고, 기존 추적 `release_metadata_path` 의존성을 제거한다.
3. helper와 workflow 계약 테스트를 추가하고 전체 unit test, config validator,
   `git diff --check`를 실행한다.
4. 관련 파일만 커밋·feature branch에 push한다. PR #1은 Draft/open/unmerged로
   유지한다.
5. 새 commit SHA를 release/runtime/preflight WIF attribute condition에 반영한
   뒤, release candidate → worker bootstrap → live read-only preflight를 각 한
   번씩 실행한다. 하나라도 실패하면 다음 단계로 진행하지 않는다.

## 금지 경계

- GCP/Firebase 리소스 생성, API enablement, IAM/WIF 변경 외에는 읽기 전용이다.
  WIF SHA 갱신은 별도 외부 설정 적용으로 exact diff를 먼저 기록한다.
- `cloudMutationApproved=false`, `deploymentApproved=false`, `mutationCommands=[]`
  를 유지한다.
- token, ID token, Authorization header, password, private key, service-account
  key, Firebase API key 원문, internal flush token 원문을 파일·로그·스크린샷에
  남기지 않는다.
- fresh deployment packet이 생성되어도 실제 Cloud Run/Tasks/Firebase mutation은
  별도 packet 검토·승인 전에는 실행하지 않는다.

## 중단 조건

- artifact run/attempt/digest/source binding 불일치
- evidence exact-byte 또는 schema 검증 실패
- protected Environment approval 미완료
- WIF condition, manifest, preflight의 현재 SHA 불일치
- static/live preflight 실패 또는 unexpected resource 경고

위 조건에서는 재시도를 반복하지 않고 해당 단계에서 중단하며, run URL과 원인을
Markdown 보고서에 남긴다.
