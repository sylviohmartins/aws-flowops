---
name: persistence-migrations
description: Design and validate FlowOps SQLite/PostgreSQL schema changes with ordered migrations, portability, rollback awareness and concurrency safety.
---

# Persistence migrations

Read `flowops/persistence/AGENTS.md` and `.agents/rules/persistence-and-migrations.md`.

Create a new numbered migration; never edit applied migration history. Explain forward and rollback/recovery impact. Validate affected repository/query behavior in SQLite and PostgreSQL. Keep production migration execution separate from code validation and human-gated.
