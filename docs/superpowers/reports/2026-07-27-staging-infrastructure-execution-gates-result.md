# Staging Infrastructure Execution Gates 구현 결과

## 목표와 결과

목표는 별도 설계·승인이 필요한 staging cloud-mutation executor 이전에, infrastructure plan 검토 증거를 fail-closed로 검증하고 canonical action manifest 및 readiness gate를 제공하는 것이었습니다.

구현 결과는 plan review만 지원합니다. tracked 상태는 `no-tracked-actual-approval-record`이며, 유효한 operator-local reviewed record에 `cloudMutationApproved=false`가 공급되면 evaluator는 `awaiting-cloud-mutation-approval`을 반환합니다. executable command/argv, cloud authentication, resource mutation, deployment 권한을 생성하지 않습니다.

## 작업 기준

- Branch: `codex/staging-infrastructure-executor`
- Worktree: `/Users/kimhongnyeon/Dev/codex/rhwp/.worktrees/staging-infrastructure-executor`
- Plan commit부터 결과 보고서 작성 직전 implementation HEAD까지의 commits:

```text
532509054a9e6af1cd4102a55fc79d9da3ba0440 docs: plan staging infrastructure execution gates
23734855cc2e6eb65ccb9c8b5b3b645a619b5337 feat: validate staging infrastructure approvals
a367d3b0cbadbb83b07a814d4840a04e1c55661a fix: harden infrastructure approval validation
d6c4546b3890bcd5bbd4be3c64cdfcc3f4f4fe46 fix: reject padded infrastructure approvers
0f6b8860bef6198544b9f746f011080f82f2ad85 fix: bind infrastructure approval to plan evidence
5fb892516d62fc02a953a1503419118c4bd42f32 fix: preserve safe infrastructure secret declaration
df48cdcdf0284c710043562ea0fd935752245124 feat: generate staging infrastructure actions
31aca1ba616a62a7b2828dbd4103fb868d34825d fix: harden staging infrastructure actions
5aca4574a82ed1ae57de381a0e401158865d9951 fix: bind infrastructure actions to exact plan bytes
be77d8792a6ea31241b37f7f23d1cbcbeae8ded6 fix: preserve safe infrastructure action details
54e40dc1bd32690863e299bb050ac06feb76eead fix: validate canonical infrastructure action inputs
86219738d470b96a9c194c527d292dfcac13f21d fix: reject labeled infrastructure secrets
59eae4a6dd49ee8bbc602b6cb9de59843edf28f4 fix: harden infrastructure execution provenance
7b694570b3555fd03e95bc1385609b610b896431 chore: remove stale action test note
a93f474187a9681fc2354d67a7a97b9e7bd40ee4 fix: support verified infrastructure action reruns
9cf50f43f95db2f394718377abdb08a348ed1010 fix: support direct infrastructure action CLI
39109ce3143d393e66ae18a82fbeaee4fd943a5e feat: report staging execution readiness
bd858f5479451705a4d9a5f7a5e952675bb4d839 fix: bind execution manifest plan object evidence
6b41972bc4dec6c1834885f08aba506e118ac609 fix: harden staging execution readiness gate
28d64ada9657a8a301de4a0d8a88d15381817e6b fix: bind execution gate to approved source plan
db9172a0053dd2d6e3d18035d625eb77dadd903d fix: harden untrusted infrastructure evidence
e80cd477dbace371c38ea71bbdd2cd4439fd148d docs: document staging infrastructure execution gates
2c3c37653798e6e7bbf974fac1fa15df63f9fd1c docs: clarify staging execution approval gates
af77f122761d25cad4644c4d54dc7c5060125ee4 docs: define local staging evidence policy
dd9ce0e1e4ba91cfba515f789d72960e33aef24e docs: clarify staging review status
7f4ece3c2b44b213a8e4b59e139109ba7b18de8c fix: require exact staging execution provenance
f04d7dc39029908d8fc1435cb44a8d8ddd8d5c96 docs: require exact staging plan provenance
8f63836bbec3a4acbe275d9f4de118bb6308ce8b fix: bound staging infrastructure JSON inputs
```

위 목록은 이 문서 업데이트 직전 implementation HEAD인 `8f63836b`까지의 이력입니다. 이 보고서 자체를 포함하는 새 docs commit은 생성 후 작업 인계에서 SHA를 보고하므로 문서 안에서 자기 자신의 최종 SHA를 예측하지 않습니다.

## 파일과 역할

| 파일 | 역할 |
| --- | --- |
| `scripts/staging_infrastructure_approval.py` | pre-read size 제한, exact plan bytes와 approval record 결합, shared atomic publish/completion marker를 사용하는 strict validator CLI |
| `scripts/staging_infrastructure_actions.py` | mandatory raw `plan_bytes` provenance로 eleven canonical stage를 non-executable structured action manifest로 변환하는 CLI |
| `scripts/staging_infrastructure_execution_gate.py` | 별도 `--plan` raw bytes로 manifest/approval provenance를 재구성·검증하고 필요한 다음 승인을 보고하는 readiness CLI |
| `scripts/staging_infrastructure_action_io.py` | 세 CLI의 paired JSON/Markdown atomic publish와 `.complete` marker 처리 |
| `scripts/staging_infrastructure_validation.py` | shared bounded raw-byte API, single-FD `fstat` regular-file reader, strict UTF-8 JSON domain과 key-sorted canonical JSON helper |
| `scripts/staging_infrastructure_plan.py` | sensitive-data redaction 뒤에도 canonical safe `security.secretValuesIncluded=false` declaration을 유지하도록 수정하여 downstream validation의 deterministic non-secret boundary를 보장 |
| `.gitignore` | `/artifacts/`를 ignore하여 actual operator-local operational metadata가 tracked repository에 들어가지 않도록 함 |
| `scripts/tests/test_staging_infrastructure_approval.py` | approval schema, digest, evidence binding, boundary RED/GREEN coverage |
| `scripts/tests/test_staging_infrastructure_actions.py` | action mapping, deterministic order, unsafe input, provenance RED/GREEN coverage |
| `scripts/tests/test_staging_infrastructure_execution_gate.py` | readiness, blocked 상태, no-execution boundary RED/GREEN coverage |
| `docs/runbooks/staging-infrastructure-bootstrap.md` | 현재 검토 명령과 미래 apply trust/approval boundary |
| `docs/superpowers/plans/2026-07-27-staging-infrastructure-execution-gates.md` | 실제 완료된 구현 단계와 shared helper file structure 추적 |

## 아키텍처와 검토 루프

validator는 approval record를 exact plan bytes SHA-256, key-sorted canonical plan object digest, commit SHA, project/billing, ordered stage IDs, budget, rollback acknowledgement에 결합합니다. action generator와 execution gate는 mandatory raw `plan_bytes`를 받아 canonical table 및 source evidence를 재구성하며, parsed dict만 사용하는 two-argument 경로는 허용하지 않습니다.

TDD는 각 component에서 RED test를 먼저 추가하고 구현 후 GREEN으로 전환했습니다. 이후 approval validation, action provenance, untrusted evidence, gate binding과 최종 integration review를 반복했습니다. `7f4ece3c`에서 raw bytes 필수화, gate `--plan`, validator completion marker, strict Unicode/canonical serialization을 통합했고, `8f63836b`에서 public API byte limit과 single-FD bounded regular-file reader를 공통 validation 계층으로 통합했습니다.

## 보안 경계

- `subprocess` import, cloud CLI, Firebase CLI, authentication, executable shell/argv 직렬화가 없습니다.
- access token, Authorization header, private key, service-account key, Firebase API key 값, credential, password, secret value, internal flush 원문을 저장하거나 출력하지 않습니다.
- unknown stage, provenance mismatch, production-like resource, unsafe key, invalid approval, deployment approval, missing rollback acknowledgement는 fail-closed입니다.
- `cloudMutationApproved=false`는 plan review 결과만 만들며 apply를 허용하지 않습니다.
- approval validator, action manifest, readiness gate 세 CLI의 output `.complete` marker는 paired output publish marker일 뿐 승인·인증·apply·배포의 완료 표시는 아닙니다.
- 모든 JSON file 입력은 single-FD `fstat` regular-file 확인 후 최대 `MAX_JSON_BYTES + 1`만 읽고, public raw-byte API도 1,000,000-byte 제한을 적용합니다. strict UTF-8/JSON-domain 검증 뒤 exact raw digest와 sorted canonical object digest를 별도로 확인하며 raw bytes 없이는 action/gate provenance가 성립하지 않습니다.

## 검증 결과

문서 commit 직전에 fresh verification을 다시 실행했습니다.

| 확인 | 결과 |
| --- | --- |
| `python3 -m py_compile` | 새 production scripts 5개와 tests 3개가 성공했습니다. |
| `python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v` | `Ran 150 tests` / `OK` (0.838초) |
| `python3 scripts/validate_staging_config.py` | configuration templates valid, deployment 미수행 |
| 신규 CLI `--help` | approval validator, action manifest generator, readiness gate 3개 모두 성공 |
| `git diff --check` | 출력 없음, whitespace 오류 없음 |
| secret/execution scan | production code의 sensitive-key regex/marker와 문서의 금지 규칙만 발견했습니다. 실제 secret·key·token·raw internal-flush 값, `subprocess`, cloud CLI/auth 실행은 발견되지 않았습니다. Test fixture/regex marker는 실제 credential가 아닙니다. |
| production line count | 436, 493, 434, 52, 93줄로 모두 500줄 미만입니다. |
| PR #1 read-only 확인 | Draft, open, unmerged (`merged_at=null`), base `devel`이며 PR head SHA는 read-only 조회값과 일치했습니다. push/PR 변경은 하지 않았습니다. |

## 현재 상태와 차단 요인

tracked worktree/repository 상태는 `no-tracked-actual-approval-record`입니다. operator-local reviewed plan record가 존재하고 `cloudMutationApproved=false`라면 `awaiting-cloud-mutation-approval`으로 평가되지만 apply 입력은 아닙니다. actual project/billing/resource 식별자, approval artifact, credential 또는 실행 evidence는 tracked repository에 만들거나 기록하지 않았습니다. Operational metadata는 ignored local `artifacts/actual-infrastructure-review/`에만 둘 수 있으며, `docs/approvals/records/` archival은 별도 사용자 승인과 redaction policy 없이는 수행하지 않습니다.

apply 전 필요한 별도 사용자 승인은 다음과 같습니다.

1. `mutation-architecture`
2. `actual-evidence-transport`
3. `canonical-mutation-subset`
4. `staging-infrastructure-apply-environment`
5. `wif-identity-and-least-privilege-iam-diff`
6. `cloud-mutation-approval-record`
7. `apply-workflow-dispatch`

`implementation branch publish`는 위 apply 승인들을 대체하지 않는 별도 integration approval입니다.

실제 step 7 evidence가 없으므로 lifecycle steps 8-12는 blocked입니다. deployment는 별도 approval과 executor가 필요한 독립 작업입니다.

## 외부 변경 없음

이 구현 범위에서는 cloud mutation, cloud authentication, deployment, GitHub push, PR 생성·수정, merge를 수행하지 않았습니다. PR #1의 상태와 remote head는 read-only로만 확인합니다.
