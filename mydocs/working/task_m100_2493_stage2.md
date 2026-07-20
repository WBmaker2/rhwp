# Task 2493 Stage 2 - Browser extension remote HML fetch completion

## Scope

- Complete the remote HML link path exposed by #2511 across Chrome, Firefox, and Safari extensions.
- Preserve the existing security gate: a `.hml` suffix alone must not permit arbitrary HTML or JSON responses.

## Discovery

- #2511 adds HML to content-script and shared URL detection, but Safari background fetch validation accepts only the HWP CFB and HWPX ZIP signatures.
- HML is XML, so a valid remote HML document reaches the viewer URL but is rejected before the WASM HML parser receives its bytes.

## Validation plan

1. Locate every browser-extension background fetch/signature gate and apply one consistent HML document signature policy.
2. Add regression coverage for valid HML and HTML/JSON impostors.
3. Run extension builds and the affected tests without publishing or installing an extension.
