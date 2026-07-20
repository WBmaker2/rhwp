# Task 2493 Stage 2 - Browser extension remote HML fetch completion

## Scope

- Complete the remote HML link path exposed by #2511 in Safari's separate background implementation.
- Preserve the existing security gate: a `.hml` suffix alone must not permit arbitrary HTML or JSON responses.

## Discovery

- Chrome and Firefox already apply URL policy without a binary signature gate, so their remote HML paths pass after #2511.
- Safari background fetch validation alone accepts only the HWP CFB and HWPX ZIP signatures.
- HML is XML, so a valid remote HML document reaches the viewer URL but is rejected before the WASM HML parser receives its bytes.

## Validation plan

1. Extend the shared document signature policy with the Rust parser-compatible HML prefix check, and load it before Safari's background script.
2. Add regression coverage for valid HML and HTML/JSON impostors.
3. Run extension builds and the affected tests without publishing or installing an extension.

## Result

- `rhwp-shared/security/file-signature.js` now recognizes HML only after a bounded UTF-8/UTF-16 prefix decodes to an `HWPML` root with a nonempty `Version` attribute.
- Safari loads that helper before `background.js`, copies it into `dist`, and accepts `.hml` in automatic URL policy.
- Regression coverage accepts UTF-8, UTF-16, and the two repository HML samples while rejecting HTML, JSON, and invalid HWPML lookalikes.
- Chrome and Firefox production builds completed. Safari `dist` generation completed; the signed build remains blocked by the local Mac certificate, while `CODE_SIGNING_ALLOWED=NO` Xcode build succeeded.
