# Task 2505 Stage 1 - Safari build hygiene cleanup

## Scope

- Integrate [#2505](https://github.com/edwardkim/rhwp/pull/2505): add Safari-local ignored build directories.
- Integrate [#2507](https://github.com/edwardkim/rhwp/pull/2507): remove the unreferenced `escapeHtml` helper from the Safari content script.
- Do not cherry-pick [#2502](https://github.com/edwardkim/rhwp/pull/2502): its only `MAX_FILE_SIZE` deletion is already included by the Safari HML gate correction in commit `7304b385a`.

## Validation plan

1. Compare the new ignore rules with Chrome and Firefox extension directories.
2. Confirm `escapeHtml` has no remaining Safari call sites and run JavaScript syntax checks.
3. Run the affected extension build without publishing or installing an extension.
