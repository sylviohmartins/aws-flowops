---
name: parallel-work
description: Decompose work into dependency-aware waves and use real isolated parallelism only when write ownership, integration and recovery are safe.
---

# Parallel work

Parallelism is an optimization, not a default. Same-wave tasks must be dependency-independent and write-file-disjoint. Shared contracts/configuration need a single owner or later integration task.

Do not call work parallel unless the execution surface actually runs independent workers. Prefer isolated branches/worktrees for concurrent writers. A single integration authority combines results and revalidates the integrated tree. Missing worker results are incomplete, not successful silence.
