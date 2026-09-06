---
name: task-completion
description: Preserve requirement-to-evidence traceability across long tasks, handoffs and context compaction and prevent premature completion claims.
---

# Task completion

For multi-requirement or compaction-prone work, read `.agents/specs/completion-contract.md`, create/resume `.agents/runs/<task>.json`, assign stable `REQ-NNN` IDs and map tasks/dependencies/write-owned files.

Capture evidence while working. Before handoff/compaction, checkpoint exact next action plus branch/files/checks/failures/risks. On resume, reconcile with repository/CI reality.

Finish with `python scripts/agents/completion_gate.py <run> --final`. `BLOCKED` is not success.
