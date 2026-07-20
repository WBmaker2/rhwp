# Task 2472 Stage 1 - HML table TextWrap round-trip integration

## Scope

- Integrate contributor PR #2472 on the current maintainer branch.
- Preserve `TextWrap` from a table `SHAPEOBJECT` when reading HML.
- Keep the rectangle path unchanged and cover both table and non-table query behavior through focused HML serializer tests.

## Review basis

- PR body: `write_shape_object` already serializes a table's `common.text_wrap`, but the reader only restored it for rectangles.
- PR comments: none.
- Remote CI failure: `cargo fmt --check` only; repair formatting locally after cherry-pick.

## Validation plan

1. Run the focused HML serializer test.
2. Run `cargo fmt --all --check` and `cargo clippy --all-targets -- -D warnings`.
3. Include this group in the consolidated full regression before the final integration PR.
