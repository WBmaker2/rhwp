# Task 2496 Stage 1 - npm editor package metadata consolidation

## Scope

- Integrate [#2496](https://github.com/edwardkim/rhwp/pull/2496): declare Node.js 18 or newer for the `node:test`-based package test suite and list `README.md` among package files.
- Integrate [#2504](https://github.com/edwardkim/rhwp/pull/2504): add the package funding link and retain the explicit README package-file declaration.
- Do not separately cherry-pick [#2503](https://github.com/edwardkim/rhwp/pull/2503): its funding-only change is fully contained in #2504.

## Validation plan

1. Validate `package.json` and run the editor package tests.
2. Run `npm pack --dry-run` to confirm the published package manifest and README contents without publishing.

## Result

- The consolidated manifest declares `engines.node: >=18.0.0`, explicitly lists `README.md`, and links the project funding page.
- `npm test` passed all 18 editor package tests.
- `npm pack --dry-run` contains the README and the expected five package files without publishing a tarball.
