---
name: implementation
description: Implement a bounded FlowOps change while preserving execution safety, compatibility, tests, AWS trust boundaries and repository validation.
---

# Implementation

Read `AGENTS.md`, engineering conventions and task-specific rules first.

- Define observable behavior and acceptance criteria.
- Prefer nearby patterns over new architecture.
- Keep the change local and complete.
- Update tests/docs/contracts when behavior changes.
- Classify AWS, persistence, security, compatibility and deployment impact.
- Run focused checks, then the Quality CI loop.
- Stop before human-gated production AWS/secret/database operations.
