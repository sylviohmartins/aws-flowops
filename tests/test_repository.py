import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flowops.domain.errors import ConflictError
from flowops.domain.models import Runbook
from flowops.persistence.repository import Repository


class RepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Repository(Path(self.temp.name) / "test.db")

    def test_migration_and_version_immutability(self) -> None:
        self.repo.migrate()
        book = Runbook(name="Original")
        revision = self.repo.save_draft(book, "author")
        published = self.repo.publish(book.id, "author", revision)
        book.name = "Changed"
        self.repo.save_draft(book, "author", revision)
        self.assertEqual(self.repo.version(book.id, 1).name, "Original")
        self.assertEqual(published.version, 1)
        self.assertEqual(len(self.repo.events()), 3)

    def test_concurrent_draft_updates_only_one_wins(self) -> None:
        book = Runbook(name="Concurrent")
        self.repo.save_draft(book, "author")

        def update(_: int) -> bool:
            try:
                self.repo.save_draft(book, "author", 1)
                return True
            except ConflictError:
                return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(update, range(2))), 1)

    def test_archive_delete_search_and_history(self) -> None:
        book = Runbook(name="Payments", tags=["repair"])
        rev = self.repo.save_draft(book, "author")
        self.repo.publish(book.id, "author", rev)
        self.assertEqual(len(self.repo.list_runbooks("repair")), 1)
        self.repo.archive(book.id, "author")
        self.assertFalse(self.repo.list_runbooks())
        self.assertEqual(len(self.repo.list_runbooks(archived=True)), 1)
        self.repo.archive(book.id, "author", deleted=True)
        self.assertEqual(self.repo.version(book.id).name, "Payments")

    def test_embedded_import_is_inert(self) -> None:
        import sys

        from flowops.streamlit import FlowOpsPage

        self.assertTrue(callable(FlowOpsPage))
        self.assertNotIn("standalone_app", sys.modules)


if __name__ == "__main__":
    unittest.main()
