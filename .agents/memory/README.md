# Durable agent memory

Store only stable project knowledge that remains useful beyond one task and is not better represented by code, tests, docs or an ADR.

Each topic file should include: topic, status (`active|stale|superseded`), `last_validated`, and evidence/source paths. Never store secrets, credentials, production identifiers, raw chat transcripts or transient CI output.

Use `.agents/runs/` for active task state instead.
