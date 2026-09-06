import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from flowops.core.actions import ActionRegistry
from flowops.core.engine import Engine
from flowops.core.worker import LocalWorker
from flowops.domain.models import AWSContext, Identity, Status
from flowops.persistence.repository import Repository, digest
from flowops.templates import blank


class PendingQueueTests(unittest.TestCase):
    def exercise(self, database: str | Path) -> None:
        repository = Repository(database)
        book = blank("queue-review", "ops")
        revision = repository.save_draft(book, "queue-review")
        published = repository.publish(book.id, "queue-review", revision)
        engine = Engine(repository, ActionRegistry())
        pending = engine.submit(
            published,
            Identity(id="queue-review", roles=["ADMIN"]),
            AWSContext(),
            {},
            token=book.id,
        )
        newer = (datetime.fromisoformat(pending.created_at) + timedelta(seconds=1)).isoformat()
        with repository.transaction() as db:
            for index in range(2000):
                completed = pending.model_copy(
                    update={
                        "id": f"{pending.id}-{index}",
                        "status": Status.SUCCESS,
                        "created_at": newer,
                    }
                )
                body = completed.model_dump_json()
                db.execute(
                    "INSERT INTO executions (id,token,request_digest,runbook_id,status,body,created_at) VALUES (?,?,?,?,?,?,?)",
                    (
                        completed.id,
                        completed.id,
                        digest(body),
                        book.id,
                        Status.SUCCESS.value,
                        body,
                        newer,
                    ),
                )
        self.assertNotIn(pending.id, [entry.id for entry in engine.store.history(2000)])
        self.assertEqual(engine.store.pending_ids(0), [])
        self.assertIn(pending.id, engine.store.pending_ids())
        worker = LocalWorker(engine)
        try:
            worker.dispatch_pending()
            self.assertEqual(worker.futures[pending.id].result(timeout=10).status, Status.SUCCESS)
        finally:
            worker.close()
        self.assertNotIn(pending.id, engine.store.pending_ids())

    def test_sqlite_pending_survives_large_completed_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.exercise(Path(directory) / "queue.db")

    @unittest.skipUnless(os.getenv("FLOWOPS_TEST_POSTGRES_DSN"), "PostgreSQL test DSN required")
    def test_postgres_pending_survives_large_completed_history(self) -> None:
        self.exercise(os.environ["FLOWOPS_TEST_POSTGRES_DSN"])
