"""Source and run binding checks for deployment review evidence."""
from __future__ import annotations

from typing import Any


def source_run_binding_mismatch(
    review: dict[str, Any],
    acceptance: dict[str, Any],
    rollback: dict[str, Any],
) -> str | None:
    """Return a fail-closed message when evidence is not bound to the review run."""
    expected = (
        review["commitSha"],
        review["workflowRunId"],
        review["workflowRunAttempt"],
    )
    for kind, evidence in (("acceptance", acceptance), ("rollback", rollback)):
        actual = (
            evidence["sourceCommitSha"],
            evidence["workflowRunId"],
            evidence["workflowRunAttempt"],
        )
        if actual != expected:
            return f"{kind} evidence source/run binding does not match deployment review"
    return None
