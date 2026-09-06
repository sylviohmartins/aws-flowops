# Completion and evidence

Use the completion contract for work with multiple requirements, validation surfaces, handoffs or meaningful context-compaction risk.

1. Assign stable `REQ-NNN` IDs before implementation.
2. Map requirements to tasks/dependencies before parallel work.
3. Treat task `files` as write ownership; same-wave writers must not overlap.
4. Capture evidence as work progresses.
5. A `DONE` requirement needs a concrete result and evidence.
6. Record searches when evidence is an asserted absence.
7. Preserve pending checks/open failures in checkpoints.
8. Reconcile checkpoints with repository/CI reality after resuming.
9. Run the deterministic completion gate before claiming a tracked task complete.

Prefer evidence in this order when applicable: repository/config -> executed test/CI -> authoritative documentation -> benchmark -> third-party evidence -> inference.

Do not claim completion while a required check is pending, a requirement remains open, a failure is unresolved, or a `DONE` requirement lacks evidence. External blockers are `BLOCKED`, not false success.
