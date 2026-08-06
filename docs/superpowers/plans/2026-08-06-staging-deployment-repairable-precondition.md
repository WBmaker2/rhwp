---
kind: plan
status: completed
canonical: docs/superpowers/plans/2026-08-06-staging-deployment-repairable-precondition.md
last_verified: 2026-08-06
---

# Staging deployment partial Cloud Run precondition 보정 계획

## 목적

이전 부분 실행으로 남은 `rhwp-collaboration-staging`처럼 승인된 immutable
identity(image digest, service account, ingress)는 맞지만 runtime/env가 아직
완성되지 않았거나 Ready가 아닌 Cloud Run service를 안전하게 repair 대상으로
분류한다. 잘못된 identity를 가진 리소스는 계속 fail-closed한다.

## 범위

- `scripts/staging_deployment_observer.py`의 Cloud Run precondition 분류 보정
- repairable partial service와 incompatible service 회귀 테스트 추가
- 기존 삭제·무조건 재배포·Cloud mutation 경로는 추가하지 않음
- WIF, GitHub Environment, workflow dispatch, Cloud IAM/Run/Tasks 변경은 이 단계에서
  실행하지 않음

## 설계

1. 승인 packet의 service name, image digest, service account, ingress를 immutable
   identity로 비교한다.
2. identity가 하나라도 다르면 기존처럼 `incompatible`로 중단한다.
3. identity가 모두 맞고 runtime/env 또는 Ready만 부족하면 `missing`으로 분류해
   기존 bounded `gcloud run deploy` repair 경로를 허용한다.
4. identity가 맞고 runtime/env/Ready가 모두 맞을 때만 `present` no-op으로 처리한다.
5. 관측 결과에 credential·secret 원문을 넣지 않는다.

## 검증

- repairable partial service fixture: `missing`
- wrong image/service account/ingress fixture: `incompatible`
- 완전 일치 Ready fixture: `present`
- 기존 staging Python unit test 전체 실행
- `git diff --check`

## 다음 경계

로컬 구현·테스트 결과를 검토한 뒤 commit/push를 완료했다. 현재 PR branch HEAD는
`54578c27c7f4ada841802338c520ffffeb6b752e`이며, WIF provider의 기존
`workflow_sha=50e8ad787956754e0a9b8e8e57d1d1e64e9413ba`와 새 HEAD가 다르다. 따라서
다음 단계는 WIF `attributeCondition`의 단일 SHA diff를 별도 승인받고 read-back하는
것이며, 그 뒤에만 새 packet/run-bound dispatch와 protected Environment 승인을
검토한다.
