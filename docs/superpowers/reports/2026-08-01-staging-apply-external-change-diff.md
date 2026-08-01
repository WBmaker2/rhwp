# Staging apply external change diff

This file is a review-only proposal. No external setting has been changed.

## Source binding prepared for review

```text
branch: feat/firebase-collaboration-mvp-v1
local source commit/tree: record with `git rev-parse HEAD` immediately before
push; these values are intentionally not embedded in this commit to avoid a
self-referential hash.
workflow path: .github/workflows/staging-infrastructure-apply.yml
workflow content SHA-256: dd2966930f03374443663559fb098ff17e2c8fcace47895a3b5518842c0cdb4a
remote PR head: a627262f27e76de22fce5ee54315f4bda40e432c
```

## WIF attributeCondition proposal

The provider and immutable repository identifiers are carried forward from the
last locally verified package evidence. Only `attribute.workflow_sha` changes.
The provider, project, repository, owner ID, branch, workflow ref, mapping,
issuer, audience mode, principal, and service-account binding are unchanged.

```diff
- attribute.workflow_sha == 'a627262f27e76de22fce5ee54315f4bda40e432c'
+ attribute.workflow_sha == '<new-remote-workflow-commit-sha>'
```

Full proposed condition:

```text
attribute.repository == 'WBmaker2/rhwp' && attribute.repository_id == '1311079356' && attribute.repository_owner_id == '103619091' && attribute.ref == 'refs/heads/feat/firebase-collaboration-mvp-v1' && attribute.workflow_ref == 'WBmaker2/rhwp/.github/workflows/staging-infrastructure-apply.yml@refs/heads/feat/firebase-collaboration-mvp-v1' && attribute.workflow_sha == '<new-remote-workflow-commit-sha>'
```

## GitHub Environment/repository variable proposal

Protected Environment `staging-infrastructure-apply`:

```diff
- STAGING_APPROVED_APPLY_READY_PACKAGE_JSON
- STAGING_APPROVED_MUTATION_APPROVAL_JSON
```

No new secret or cloud credential is proposed. Add these as repository-level,
non-secret variables only after the exact package and run-free human approval
declaration are separately reviewed:

```diff
+ STAGING_APPLY_READY_PACKAGE_B64
+ STAGING_MUTATION_APPROVAL_DECLARATION_B64
```

The declaration must use schema
`rhwp.staging-infrastructure-mutation-approval-declaration/v1` and must omit
`approvedRunId` and `approvedRunAttempt`. The prepare job adds those fields for
the current run. The encoded package is limited to 48 KiB by the local binder;
the current package size is below that limit.

## Required approvals before external action

1. Approve this exact source commit push to PR #1.
2. After push, approve the WIF condition update using the new remote commit SHA
   (the source SHA may change only if the push is not fast-forwarded).
3. Approve removal of the two legacy protected Environment variables and
   registration of the two repository-level variables.
4. Approve a workflow dispatch with the separately approved exact package SHA.

Until those approvals are explicit, no push, WIF mutation, Environment change,
repository-variable write, or workflow dispatch is performed.
