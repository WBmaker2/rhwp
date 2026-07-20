# Task 2473 Stage 1 - Safari extension source parity integration

## Scope

- Integrate contributor PRs #2473, #2477, and #2491 on the current maintainer branch.
- Restore Safari extension manifest, content-script capability, icon, and locale parity with the supported Chrome/Firefox extensions.

## Review basis

- PR bodies: Safari manifest version must match Chrome/Firefox `0.2.8`; extension readiness must advertise the already-supported `edit` and `print` capabilities; missing Safari package assets and Dependabot ecosystems must be restored.
- PR comments: none on all three PRs when reviewed.
- Chrome/Firefox manifests are both `0.2.8`; Chrome locale JSON and four icon blobs exactly match the #2491 additions.
- `npm/editor/package.json` and `rhwp-vscode/package.json` both exist and parse as JSON, so the new Dependabot directories are valid.

## Validation plan

1. Validate the three changed manifests/locale JSON files and the Safari JavaScript syntax.
2. Run the Safari package build, including its Chrome-extension prerequisite and macOS converter build when the local signing/project state permits it.
3. Check that Chrome, Firefox, VS Code, and npm package source trees are not behaviorally modified by this Safari-focused group.
4. Include this group in the consolidated full regression before the final integration PR.
