# Staging release-candidate 단계 구현 결과

**작성일:** 2026-08-01
**대상 브랜치:** `feat/firebase-collaboration-mvp-v1`
**단계:** Phase A — immutable image build/push candidate evidence

## 구현한 계약

- 비보호 `prepare` job은 지정된 feature branch의 source commit과 정적 계약만 확인합니다.
- protected `build-push` job만 `staging-release` Environment와 OIDC를 사용합니다.
- collaboration, document API, document worker 이미지는 source commit SHA 태그로 빌드하고
  Artifact Registry에 push한 뒤 digest를 다시 관찰합니다.
- Firebase Web App은 `rhwp-staging` display name이 정확히 하나인지 read-only로 확인하고,
  API key 원문 대신 `firebase-web-config/staging` 참조만 증거에 기록합니다.
- 결과는 동일 workflow run의 `staging-release-candidate-evidence` artifact로만 내보냅니다.
- Cloud Run deploy, Cloud Tasks queue 생성, Firebase deploy, Terraform apply는 이 단계에 없습니다.

## 구조 충돌 수정

초기 workflow 초안은 존재하지 않는 `steps.resolve.outputs.*`를 evidence 생성 환경변수로
참조했습니다. 셸에서 실제로 관찰한 project number와 image digest를 Python 단계의 환경변수로
export하도록 수정하여, 빈 값으로 artifact가 생성되는 경로를 제거했습니다.

## 남은 외부 경계

1. 이 workflow가 원격 feature branch에 반영되고 CI가 통과해야 합니다.
2. `staging-release` Environment와 release WIF/service account의 exact diff를 read-back해야 합니다.
3. 별도 승인 후 workflow dispatch를 실행하고, same-run artifact의 exact bytes와 SHA-256을 기록해야 합니다.
4. worker bootstrap 배포 전에는 실제 worker URL·revision·parse/export target URL을 추측하지 않습니다.

## 현재 Firebase 연결 차단

`aiaihnk@gmail.com`으로 인증한 Firebase Management API에서 대상 프로젝트를 확인했으며,
`rhwp-staging` display name의 ACTIVE Web App이 2개 반환되었습니다. 동일한 display name을
가진 두 앱 중 어느 것을 유지할지 자동으로 선택하거나 삭제하지 않습니다. 사용자가 Firebase
Console에서 하나를 명시적으로 유지·정리하기 전에는 release-candidate workflow가 정확히 하나
조건에서 fail-closed로 멈추는 것이 정상입니다.

## 안전 확인

- run-bound record/package를 Environment 변수에 저장하지 않습니다.
- credential, token, API key 원문을 파일·로그·artifact에 기록하지 않습니다.
- 이 문서 작성 단계에서 Cloud Run, Cloud Tasks, Firebase Hosting/Rules 배포는 실행하지 않습니다.
