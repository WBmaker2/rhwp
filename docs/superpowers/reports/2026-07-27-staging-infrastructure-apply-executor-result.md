# Staging Infrastructure Apply Executor 구현 결과

**작성일:** 2026-07-30
**상태:** fix round 4 구현·합성 검증 완료, 실제 apply 미실행

## 구현 범위

- `rhwp.staging-infrastructure-mutation-approval/v3` 승인 레코드는 apply-ready package raw SHA-256와 live Environment/WIF attestation digest, 두 plan digest,
  staging project, 순서가 고정된 stage/action ID, Environment·WIF·IAM·rollback acknowledgement,
  `cloudMutationApproved=true`, `deploymentApproved=false`를 strict하게 결합했습니다.
- executor는 approved apply-ready package 안의 strict review subset만 읽고, 네 stage의 allowlist를 내부 고정 `gcloud` argv로
  변환합니다. package의 shell, command, argv, credential, token, secret value는 소비하지 않습니다.
- 기본 동작은 dry-run이며, 실제 apply는 protected Environment attestation, validated provenance,
  validated approved record, `--apply`을 모두 요구합니다. 첫 precondition/command 실패에서 중단하고
  plan evidence와 post evidence를 분리한 atomic 파일로 남깁니다.
- apply workflow는 manual dispatch 전용입니다. 증거 download와 approval/provenance 검증이 OIDC WIF 인증보다
  앞서며, `staging-infrastructure-apply` job에만 `id-token: write`를 부여합니다.
- 이전 review package/approval은 실제 executor·same-run protected evidence transport·run nonce/expiry 계약을 포함하지 않아
  fail-closed로 거부됩니다. 운영 전에는 review→apply-ready promotion과 새 v3 human approval을 다시 생성해야 합니다.

## fix round 4 보완

- `staging_infrastructure_apply_ready.py`는 더 이상 Environment/WIF 관찰 JSON을 CLI 또는 caller-provided JSON
  promotion 입력으로 받지 않습니다. authenticated operator의 고정 read-only `gh api`와 `gcloud` argv가 실제 response를
  조회하고 strict verifier를 통과한 short-lived receipt만 apply-ready v3 exact bytes에 결합합니다.
- WIF receipt는 provider resource name, ACTIVE/disabled state, literal attribute mapping, literal CEL condition,
  deployer service-account IAM policy의 정확히 하나인 `roles/iam.workloadIdentityUser` principal binding과 raw
  response SHA-256을 검증합니다. response body, stderr, token, credential은 receipt에 남기지 않습니다.
- Environment receipt는 required reviewer, rule 내부 `prevent_self_review`, paginated branch policy와 13개
  protected variable name을 검증합니다. 후속 승인된 단일 운영자 예외에서는 official `GET Environment`
  응답이 admin-bypass field를 제공하지 않을 때 이를 관찰된 `false`로 위장하지 않고
  `unavailable-in-official-rest`로 기록합니다. 필드가 제공되면 정확히 `false`만 허용합니다.
- `AIza...`, `ya29...`, `password=`, `api_key=`, OAuth client secret, service-account credential 형태까지 공통
  string-leaf detector가 review, promotion, approval 입력에서 값 원문을 출력하지 않고 거부합니다.
- signed receipt는 raw response digest만 재계산해 위조할 수 없도록 immutable tracked-code Ed25519 public-key
  registry로 검증합니다. registry는 현재 비어 있으므로 signing-key onboarding이 별도 source review와 사용자
  승인을 받기 전에는 actual promotion을 fail-closed로 중단합니다. private signing key는 operator-local 경로에서만
  사용하며 package, protected variable, artifact에 넣지 않습니다.
- WIF provider는 GitHub Actions OIDC issuer와 default provider audience mode까지 exact하게 검증합니다.

## fix round 3 보완 (현재 signed v3로 대체된 v2 설계)

- review package는 절대로 apply authority가 아닙니다. 당시 apply-ready v1 JSON-input promotion은 v2
  fixed-query receipt promotion으로 대체되었고, 현재는 immutable-key signed apply-ready v3와 v3 approval이
  그 계약을 대체합니다.
- 이전 in-workflow GitHub Environment REST probe는 platform read contract가 admin-bypass state를 제공하지 않아
  제거했습니다. apply job은 signed v3 receipt의 exact digest·expiry·runtime context를 auth 전에 검증합니다.
- 모든 string leaf에 credential-shaped value detector를 적용했고, service-account user-managed key query,
  post-write observer failure의 explicit write-attempt evidence를 추가했습니다.

## fix round 2 보완

- package source commit을 claims에 재복사해 비교하지 않습니다. same-run artifact metadata의 source commit은
  checked-out executor commit과 일치해야 하고, package source commit은 실제 Git commit object·tree 및
  approved branch의 ancestor 관계로 별도 검증합니다.
- observer는 exit code만으로 missing을 추론하지 않고, 성공한 read-only JSON list 결과에서 API enabled,
  service-account identity/project, Artifact Registry location/`DOCKER` format, Secret `automatic` replication을
  exact하게 판정합니다. observer/write/postcondition의 첫 오류도 sanitized atomic post evidence로 남깁니다.
- apply-ready package의 모든 executor-신뢰 필드는 exact schema와 expected safe value로 검증합니다. `secrets`와
  `id-token`은 보호 환경 spec의 정해진 inert 경로/값에서만 허용하며, unknown/sensitive/executable injection은 거부합니다.
- approval은 미래 `approvedAt`과 31일 초과 validity window를 거부합니다. pending tracked example도 v3
  schema·합성 digest·빈 승인자/시각·false approval flag를 사용합니다.
- actual apply run 생성 뒤 `publish-approved-evidence` protected job이 cloud auth/id-token 없이 같은 run
  artifact를 게시하고 apply job이 그것만 소비합니다. cross-run ID 추측/입력 계약은 제거했습니다.
- immutable action pins는 `upload-artifact` v4.3.3, `github-script` v8.0.0, 공식 `setup-gcloud` v2.1.5
  release SHA로 일치시켰습니다.

## 검증

- 합성 승인, digest tamper, reordered/duplicate/unknown action, production-like project, false approval,
  acknowledgement 누락, nested sensitive/unknown injection, command injection identifier, future/overlong approval,
  exact observer semantics, post-observer atomic failure, stateful replay zero-write, Git object/branch provenance,
  workflow publication order·권한·pin을 테스트했습니다.
- 이 결과 문서와 fixture는 합성 값만 포함합니다. actual package digest, 승인자, 시각, repository immutable ID,
  WIF/IAM 실값은 기록하지 않았습니다.

## 남은 게이트

실제 apply 전에는 GitHub protected Environment의 exact immutable provenance 값, actual apply-ready v3 package와
v3 approval variables, Environment reviewer policy와 WIF/IAM before/after diff가 모두 사람에게 승인되어야 합니다.
같은 run publication 절차는 구현했지만 GitHub Environment 변수 설정·approval·dispatch, cloud authentication,
resource mutation, build/push/deploy는 실행하지 않았습니다. 또한 current immutable operator signing-key registry는
비어 있으므로 별도 key onboarding source review 없이는 promotion이 의도적으로 blocked입니다.
