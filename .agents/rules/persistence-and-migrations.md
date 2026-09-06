# Persistence and migrations

The Repository contract supports SQLite locally and PostgreSQL for shared deployments.

- Add schema changes as new ordered files under `flowops/persistence/migrations/`; do not rewrite an already-applied migration.
- Keep migrations forward-safe and document rollback/recovery implications when destructive or irreversible.
- Preserve transaction boundaries and concurrency/lock semantics.
- Avoid backend-specific SQL unless the adapter intentionally translates or isolates it.
- Test material schema/query changes against SQLite and PostgreSQL.
- Production database application is an operational action, not a test step; do not apply it without explicit human approval.
