# Task 2473 Stage 2 - Safari build failure propagation

## Scope

- Preserve the exit status of the Safari macOS `xcodebuild` invocation when its output is reduced with `tail`.

## Discovery

- `rhwp-safari/build.sh` used `set -e`, but `xcodebuild ... | tail -3` returned `tail`'s successful status when the local build failed because a signing certificate was unavailable.
- A direct `xcodebuild` with `CODE_SIGNING_ALLOWED=NO` compiled the Safari app successfully, so the source package is buildable; the wrapper script was reporting a false success for signed-build failures.

## Validation plan

1. Confirm the shell script parses.
2. Confirm `pipefail` makes a failing producer fail the pipeline.
3. Run the Safari build wrapper and verify its nonzero status is propagated when local signing is unavailable.
