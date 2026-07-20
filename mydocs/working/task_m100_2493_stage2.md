# Task 2493 Stage 2 - Browser extension remote HML fetch completion

## Scope

- Complete the remote HML link path exposed by #2511 in Safari's separate background implementation.
- Preserve the existing security gate: a `.hml` suffix alone must not permit arbitrary HTML or JSON responses.

## Discovery

- Chrome and Firefox already apply URL policy without a binary signature gate, so their remote HML paths pass after #2511.
- Safari background fetch validation alone accepts only the HWP CFB and HWPX ZIP signatures.
- HML is XML, so a valid remote HML document reaches the viewer URL but is rejected before the WASM HML parser receives its bytes.

## Validation plan

1. Reuse or extend the shared signature policy for Safari's separate background implementation.
2. Add regression coverage for valid HML and HTML/JSON impostors.
3. Run extension builds and the affected tests without publishing or installing an extension.
