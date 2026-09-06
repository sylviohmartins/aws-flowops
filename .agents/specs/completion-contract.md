# Completion contract

Long-running agent work must not depend on conversation history as its authoritative execution state.

For a non-trivial tracked task, maintain a JSON run under `.agents/runs/<task-id>.json` conforming to `.agents/schemas/task-run.schema.json`. Remove transient run files before promotion unless the trace has durable audit value; durable conclusions belong in normal documentation/ADRs/memory.

Every user requirement receives a stable `REQ-NNN` identifier. Every `DONE` requirement carries evidence. Tasks declare dependencies, execution wave and write-owned files when parallelism is used.

Final requirement states are `DONE`, `REJECTED_WITH_REASON`, `BLOCKED` or `NOT_APPLICABLE`. `NOT_STARTED`, `IN_PROGRESS` and `VALIDATING` are non-final.

Checkpoint at least: phase, exact next action, branch, changed files, executed/pending checks, open failures, risks and decisions. After resuming, repository and CI reality win over stale checkpoint state.

Run:

```bash
python scripts/agents/completion_gate.py .agents/runs/<task-id>.json --final
```

`PASS` requires terminal requirements/tasks, evidence for each `DONE` requirement, no pending required checks, no open failures and no same-wave write-ownership conflict. External blockers produce `BLOCKED`, not `PASS`.
