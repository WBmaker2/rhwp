# Staging apply prepare/apply architecture implementation

## Outcome

The previous protected-publication design was removed from the source contract.
The workflow now has a non-protected, non-mutating `prepare` job followed by a
protected `apply` job.

```text
repository-level exact package bytes + approval declaration
                         │
                         ▼
prepare (no Environment, no id-token, no cloud mutation)
  └─ validate exact SHA and declaration
  └─ bind github.run_id / github.run_attempt
  └─ publish same-run staging-infrastructure-approved-evidence
                         │
                         ▼
protected apply (Environment approval, id-token: write)
  └─ consume same-run artifact only
  └─ validate provenance before authentication
  └─ authenticate and mutate only after the gate
```

## Source changes

- `.github/workflows/staging-infrastructure-apply.yml`
  - replaced the old Environment-variable publication job with `prepare`;
  - added the exact package SHA workflow input;
  - removed package/approval JSON from Environment variables;
  - retained WIF authentication and executor mutation only in protected `apply`.
- `scripts/staging_infrastructure_apply_approval.py`
  - added run-free approval declaration validation;
  - added the only run-binding function, `bind_run_approval`;
  - retained full v3 approval validation for the executor.
- `scripts/staging_infrastructure_apply_prepare.py`
  - strict one-line base64 decoding;
  - exact package-byte preservation and SHA verification;
  - atomic run-bound evidence publication.
- review policy, package builder, Environment attestation comments, and the
  staging runbook now describe the two-job contract.
- tests cover declaration binding, exact-byte preservation, SHA mismatch
  fail-closed behavior, and prepare/apply permission ordering.

## Repository variables required by the new workflow

These are non-secret repository-level variables, not protected Environment
variables:

- `STAGING_APPLY_READY_PACKAGE_B64`
- `STAGING_MUTATION_APPROVAL_DECLARATION_B64`

The package must be base64 of the exact JSON bytes whose SHA is entered into the
dispatch input. The declaration must use
`rhwp.staging-infrastructure-mutation-approval-declaration/v1` and must omit
`approvedRunId` and `approvedRunAttempt`. The prepare job supplies those two
fields and emits the full v3 record. The current repository-variable transport
is bounded at 48 KiB encoded; a larger package must use a separately reviewed
artifact-source transport rather than silently truncating or reformatting it.

## Verification

```text
python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v
198 tests passed

python3 scripts/validate_staging_config.py
staging manifest and configuration templates are valid; no deployment was performed
```

No cloud API, IAM, WIF, secret, resource, build, push, deployment, or workflow
dispatch was performed by this local implementation. The existing ignored
`.chatgpt2codex/` path was not added to Git.

## Next external gates

1. Review this source diff and update the immutable WIF `workflow_sha` binding
   for the eventual commit.
2. Remove the two legacy package/approval variables from the protected
   `staging-infrastructure-apply` Environment and verify the 11-variable
   contract.
3. Publish the approved package/declaration as repository variables using an
   explicitly approved, auditable method.
4. Push this implementation, wait for the WIF read-back attestation, and only
   then dispatch with the separately approved exact package SHA.

Each external action remains a separate approval boundary.
