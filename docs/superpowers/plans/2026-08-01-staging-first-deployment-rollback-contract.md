# Staging 최초 배포 rollback 계약 보정 계획

**작성일:** 2026-08-01
**대상 브랜치:** `feat/firebase-collaboration-mvp-v1`
**범위:** release metadata와 deployment manifest의 최초 배포 rollback 상태를 명시적으로 표현하는 로컬 계약 변경

## 문제

현재 `scripts/staging_deployment_manifest.py`는 release metadata에 실제 Cloud Run rollback revision
세 개를 항상 요구한다. 그러나 최초 Cloud Run 배포 전에는 이전 revision이 존재하지 않을 수 있다.
이 상태에서 임의 revision ID를 넣으면 승인 packet과 실제 cloud 상태가 불일치하므로 fail-closed가
맞지만, 정상적인 최초 배포도 진행할 수 없는 계약 충돌이 생긴다.

## 제안 계약

release metadata root에 `deploymentStage`를 추가한다.

- `initial`: 최초 배포. `rollbackRevisionIds`는 `[null, null, null]`이며 이전 revision이 없음을 명시한다.
- `upgrade`: 기존 배포 교체. `rollbackRevisionIds`는 실제 값 세 개를 요구하며 placeholder·빈 문자열·null을 금지한다.

resolver는 최종 manifest의 `operations.deploymentStage`에도 같은 값을 복사한다. preflight와 approval
packet은 이 상태를 보존해 최초 배포에서 rollback을 자동으로 주장하지 않도록 한다.

## 구현 순서

1. release metadata resolver의 exact key와 stage별 rollback 검증을 변경한다.
2. staging preflight validator가 최종 manifest의 stage/rollback 조합을 검증하도록 한다.
3. deployment approval packet에 rollback state를 포함한다.
4. 최초·upgrade·혼합/null/placeholder negative 회귀 테스트를 추가한다.
5. runbook·Task 5 계획·결과 보고서에 계약과 중단 조건을 반영한다.
6. 전체 테스트, staging validator, `py_compile`, `git diff --check`를 실행한다.

## 안전 경계

- 실제 rollback revision ID를 생성하거나 추측하지 않는다.
- release metadata 파일·image digest·Firebase 식별자를 생성하지 않는다.
- WIF secret 등록, workflow dispatch, image build/push, Cloud Run/Firebase deployment는 수행하지 않는다.
- `cloudMutationApproved=false`, `deploymentApproved=false`, `mutationCommands=[]`를 유지한다.

## 구현 결과

- resolver exact schema에 `deploymentStage`를 추가했다.
- `initial`은 `[null, null, null]`, `upgrade`는 실제 revision 세 개만 허용한다.
- 최종 manifest와 approval packet이 stage를 보존한다.
- 최초·upgrade·혼합/null/placeholder negative 테스트를 추가했다.
- 전체 `scripts/tests`는 213개 통과했으며 staging validator, `py_compile`, `git diff --check`도 통과했다.
