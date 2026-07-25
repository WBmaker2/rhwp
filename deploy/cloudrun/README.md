# Staging Cloud Run templates

These manifests are deployment templates and are not applied by this repository.
They intentionally contain `${...}` release placeholders and immutable image-digest expressions.

## Required release inputs

- collaboration and document API image repositories and SHA-256 digests
- dedicated service-account emails for each service
- Firebase staging project ID and storage bucket
- private parse/export worker URLs and Cloud Tasks service account
- the collaboration internal token stored in Secret Manager

## Security boundary

Browser API and WebSocket requests still pass Firebase ID-token and document ACL validation in application code. The collaboration flush endpoint additionally requires a Cloud Run identity token plus the internal token referenced from Secret Manager. No secret value is stored in these files.

The templates do not create or change IAM bindings. Ingress and invoker policy must be reviewed as a separate, explicit release action.

## Validation only

Run `python3 scripts/validate_staging_config.py` to check placeholder usage, immutable image references, Secret Manager references, and common credential leaks. CI does not run deployment commands or mutate cloud resources.
