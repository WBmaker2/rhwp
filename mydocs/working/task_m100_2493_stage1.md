# Task 2493 Stage 1 - HML editor and extension discovery integration

## Scope

- Integrate contributor PRs #2493, #2495, and #2511.
- Expose the already-supported HML format through the VS Code custom editor, Marketplace metadata, and browser-extension link detection.

## Review basis

- PR bodies: HML is already loadable in the core, Studio, and CLI, but VS Code had no `*.hml` custom-editor selector and browser extension URL checks accepted only HWP/HWPX.
- PR comments: none on all three PRs when reviewed.
- The shared URL resolver is the common safety gate for ordinary and GitHub raw URLs. Its existing tests only covered HWP/HWPX, so HML acceptance needs explicit regression coverage.

## Maintainer coverage

- Verify HML path recognition and GitHub blob-to-raw resolution alongside the existing HWP/HWPX cases.
- Keep query-only pseudo extensions and non-document GitHub paths rejected.

## Validation plan

1. Run the shared URL resolver Node test suite.
2. Validate VS Code package JSON and package it locally without publishing.
3. Syntax-check all changed browser content scripts and build Chrome/Firefox extensions locally.
4. Include this group in the consolidated full regression before the final integration PR.
