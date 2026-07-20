# Task 2480 Stage 1 - Undo split FieldRange integration

## Scope

- Integrate contributor PR #2480 on the current maintainer branch.
- Preserve a merged second paragraph's ClickHere field when undo splits the paragraph again.

## Review basis

- PR body: `split_at` previously retained or dropped `field_ranges` without moving a `Control::Field` to the new paragraph.
- PR comments: none.
- Existing `test_split_and_merge_roundtrip` has no field control, so it cannot demonstrate the reported regression.

## Maintainer coverage

- Merge a paragraph containing a ClickHere field into a preceding paragraph, then split at the merge boundary.
- Assert the restored paragraph owns the Field control, its remapped `FieldRange`, matching `CTRL_DATA`, and field-range control mask.

## Validation plan

1. Run the focused paragraph model tests.
2. Run `cargo fmt --all --check` and `cargo clippy --all-targets -- -D warnings`.
3. Include this group in the consolidated full regression before the final integration PR.
