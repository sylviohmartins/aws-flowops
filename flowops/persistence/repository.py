"""Transactional persistence for local SQLite and production PostgreSQL.

Immutable published definitions use insert-only rows. Draft updates use compare-and-swap.
No UI/session state is authoritative. SQL stays deliberately portable across both backends.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from flowops.core.security import bounded_output
from flowops.domain.errors import ConflictError, WorkflowValidationError
from flowops.domain.models import Runbook, new_id, utcnow
from flowops.persistence.database import PostgresConnection, is_postgres


def canonical(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Repository:
    """Short-lived transactions are safe to share across UI sessions and worker threads."""

    def __init__(self, database: str | Path = "flowops.db"):
        configured = str(database)
        self._database = configured
        self.backend = "postgres" if is_postgres(configured) else "sqlite"
        self.database = (
            f"postgresql://configured-{hashlib.sha256(configured.encode()).hexdigest()[:12]}"
            if self.backend == "postgres"
            else configured
        )
        if self.backend == "sqlite" and configured == ":memory:":
            raise ValueError("Use a temporary database file: workers require shared persistence.")
        self.migrate()

    @classmethod
    def from_environment(cls) -> Repository:
        """Resolve storage without exposing repository internals to an embedding host."""
        configured = os.getenv("FLOWOPS_DATABASE_URL") or os.getenv("FLOWOPS_DATABASE") or "flowops.db"
        return cls(configured)

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        if self.backend == "postgres":
            try:
                import psycopg
            except ImportError as exc:  # pragma: no cover - environment packaging guard
                raise RuntimeError(
                    "PostgreSQL requires the optional dependency: pip install 'aws-flowops[postgres]'"
                ) from exc
            pg_connection = psycopg.connect(self._database, connect_timeout=5)
            db = PostgresConnection(pg_connection)
            try:
                yield db
                pg_connection.commit()
            except BaseException:
                pg_connection.rollback()
                raise
            finally:
                pg_connection.close()
            return

        sqlite_connection = sqlite3.connect(self._database, timeout=30)
        sqlite_connection.row_factory = sqlite3.Row
        sqlite_connection.execute("PRAGMA foreign_keys=ON")
        sqlite_connection.execute("PRAGMA busy_timeout=30000")
        try:
            sqlite_connection.execute("BEGIN IMMEDIATE")
            yield sqlite_connection
            sqlite_connection.commit()
        except BaseException:
            sqlite_connection.rollback()
            raise
        finally:
            sqlite_connection.close()

    def migrate(self) -> None:
        """Apply each numbered SQL migration once, within a transaction."""
        with self.transaction() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS schema_versions (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            applied = {row[0] for row in db.execute("SELECT version FROM schema_versions")}
            for path in sorted(Path(__file__).with_name("migrations").glob("*.sql")):
                version = int(path.name.split("_")[0])
                if version not in applied:
                    for statement in path.read_text().split(";"):
                        if statement.strip():
                            db.execute(statement)
                    db.execute("INSERT INTO schema_versions VALUES (?, ?)", (version, utcnow()))

    @staticmethod
    def event(
        db: Any,
        actor: str,
        event: str,
        body: dict[str, Any],
        execution_id: str | None = None,
    ) -> None:
        safe = bounded_output(body)
        if not isinstance(safe, dict):
            safe = {"body": safe}
        db.execute(
            "INSERT INTO audit_events VALUES (?, ?, ?, ?, ?, ?)",
            (new_id(), utcnow(), actor, event, execution_id, canonical(safe)),
        )

    def audit(
        self,
        actor: str,
        event: str,
        body: dict[str, Any],
        execution_id: str | None = None,
    ) -> None:
        with self.transaction() as db:
            self.event(db, actor, event, body, execution_id)

    def save_draft(self, runbook: Runbook, actor: str, expected_revision: int = 0) -> int:
        body = runbook.model_copy(deep=True)
        body.updated_at = utcnow()
        with self.transaction() as db:
            current = db.execute("SELECT revision FROM runbooks WHERE id=?", (body.id,)).fetchone()
            if current is None:
                if expected_revision != 0:
                    raise ConflictError("Draft no longer exists.")
                db.execute(
                    "INSERT INTO runbooks (id,name,owner,team,body,revision) VALUES (?,?,?,?,?,1)",
                    (body.id, body.name, body.owner, body.team, body.model_dump_json()),
                )
                event = "RUNBOOK_CREATED"
            else:
                changed = db.execute(
                    "UPDATE runbooks SET name=?,owner=?,team=?,body=?,revision=revision+1 WHERE id=? AND revision=? AND deleted=0",
                    (
                        body.name,
                        body.owner,
                        body.team,
                        body.model_dump_json(),
                        body.id,
                        expected_revision,
                    ),
                ).rowcount
                if changed != 1:
                    raise ConflictError("Draft changed in another session. Reload before saving.")
                event = "RUNBOOK_CHANGED"
            self.event(
                db,
                actor,
                event,
                {"runbook_id": body.id, "revision": expected_revision + 1},
            )
        return expected_revision + 1

    def get_draft(self, runbook_id: str) -> tuple[Runbook, int]:
        with self.transaction() as db:
            row = db.execute(
                "SELECT body,revision FROM runbooks WHERE id=? AND deleted=0", (runbook_id,)
            ).fetchone()
        if row is None:
            raise WorkflowValidationError("Runbook does not exist.")
        return Runbook.model_validate_json(row["body"]), row["revision"]

    def list_runbooks(self, query: str = "", *, archived: bool = False) -> list[Runbook]:
        with self.transaction() as db:
            rows = db.execute(
                "SELECT body FROM runbooks WHERE deleted=0 AND archived=? ORDER BY name",
                (int(archived),),
            ).fetchall()
        books = [Runbook.model_validate_json(row["body"]) for row in rows]
        return [
            book
            for book in books
            if query.casefold()
            in f"{book.name} {book.description} {' '.join(book.tags)} {book.team}".casefold()
        ]

    def publish(self, runbook_id: str, actor: str, expected_revision: int) -> Runbook:
        with self.transaction() as db:
            row = db.execute(
                "SELECT body,revision FROM runbooks WHERE id=? AND deleted=0 AND archived=0",
                (runbook_id,),
            ).fetchone()
            if row is None or row["revision"] != expected_revision:
                raise ConflictError("Save the current draft before publishing.")
            book = Runbook.model_validate_json(row["body"])
            version = db.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM runbook_versions WHERE runbook_id=?",
                (runbook_id,),
            ).fetchone()[0]
            book.version = version
            db.execute(
                "INSERT INTO runbook_versions VALUES (?,?,?,?,?)",
                (book.id, version, book.model_dump_json(), digest(book.model_dump()), utcnow()),
            )
            self.event(
                db,
                actor,
                "RUNBOOK_PUBLISHED",
                {"runbook_id": book.id, "version": version},
            )
        return book

    def version(self, runbook_id: str, version: int | None = None) -> Runbook:
        with self.transaction() as db:
            if version is None:
                row = db.execute(
                    "SELECT body,digest FROM runbook_versions WHERE runbook_id=? ORDER BY version DESC LIMIT 1",
                    (runbook_id,),
                ).fetchone()
            else:
                row = db.execute(
                    "SELECT body,digest FROM runbook_versions WHERE runbook_id=? AND version=?",
                    (runbook_id, version),
                ).fetchone()
        if row is None:
            raise WorkflowValidationError("Publish a runbook version first.")
        book = Runbook.model_validate_json(row["body"])
        if digest(book.model_dump()) != row["digest"]:
            raise ConflictError("Published definition integrity check failed.")
        return book

    def versions(self, runbook_id: str) -> list[int]:
        with self.transaction() as db:
            return [
                row[0]
                for row in db.execute(
                    "SELECT version FROM runbook_versions WHERE runbook_id=? ORDER BY version DESC",
                    (runbook_id,),
                )
            ]

    def archive(
        self,
        runbook_id: str,
        actor: str,
        *,
        deleted: bool = False,
        archived: bool = True,
    ) -> None:
        with self.transaction() as db:
            db.execute(
                "UPDATE runbooks SET archived=?,deleted=?,revision=revision+1 WHERE id=?",
                (int(archived), int(deleted), runbook_id),
            )
            self.event(
                db,
                actor,
                "RUNBOOK_DELETED" if deleted else "RUNBOOK_ARCHIVED",
                {"runbook_id": runbook_id, "archived": archived},
            )

    def events(self, execution_id: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        bounded_limit = min(limit, 2000)
        with self.transaction() as db:
            if execution_id is None:
                rows = db.execute(
                    "SELECT * FROM audit_events ORDER BY created_at DESC LIMIT ?",
                    (bounded_limit,),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM audit_events WHERE execution_id=? ORDER BY created_at DESC LIMIT ?",
                    (execution_id, bounded_limit),
                ).fetchall()
        return [dict(row) | {"body": json.loads(row["body"])} for row in rows]
