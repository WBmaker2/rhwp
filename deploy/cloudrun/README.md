# Staging Cloud Run templates

These manifests are deployment templates and are not applied by this repository.
They intentionally contain `${...}` release placeholders and immutable image-digest expressions.

## Required release inputs

- collaboration and document API image repositories and SHA-256 digests
- dedicated service-account emails for each service
- Firebase staging project ID and storage bucket
- private parse/export worker URLs and Cloud Tasks service account
- the collaboration internal token stored in Secret Manager
- Cloud Tasks HTTP dispatch deadline fixed at 900 seconds

## Machine-readable staging contract

The staging resource, runtime, IAM, queue, secret, and budget contract is stored in:

```text
deploy/staging/staging-manifest.json
```

The manifest is validated against these Cloud Run templates and `firebase/staging.env.example`. It keeps unapproved values as `${PLACEHOLDER}` strings and must never contain a secret value or service-account key.

## Security boundary

Browser API and WebSocket requests still pass Firebase ID-token and document ACL validation in application code. The collaboration flush endpoint directly verifies the internal token referenced from Secret Manager. Document API also sends a Cloud Run identity token, but the current public collaboration service does not treat that token as an independently enforced application boundary.

The document worker uses internal ingress and Cloud Tasks OIDC. The templates do not create or change IAM bindings. Ingress and invoker policy must be reviewed as a separate, explicit release action.

## Validation only

Static validation:

```bash
python3 scripts/validate_staging_config.py
python3 scripts/staging_preflight.py \
  --manifest deploy/staging/staging-manifest.json \
  --report artifacts/staging-preflight-static.json
```

The static report must contain empty `cloudQueries` and `mutationCommands` arrays.

The optional live validator uses an explicit read-only command allowlist and requires a concrete approved staging project. It does not create, update, delete, deploy, enable, disable, or change IAM resources.

See `docs/runbooks/staging-preflight.md` for the complete workflow, report, and approval gates.
