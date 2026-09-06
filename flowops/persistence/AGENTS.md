# Persistence agent instructions

Applies under `flowops/persistence/`.

Read `.agents/rules/persistence-and-migrations.md` and use the `persistence-migrations` skill.

- Preserve the Repository contract across SQLite and PostgreSQL where portability is promised.
- Add ordered migrations; never rewrite already-applied migration history.
- Preserve transaction, lock, checkpoint, approval and audit semantics.
- Do not expose DSNs or credentials in public identifiers/logging.
- Material schema/query changes require SQLite and PostgreSQL tests.
- Applying a production database migration is separate from validating repository code.
