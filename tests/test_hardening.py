import tempfile
import unittest
from pathlib import Path

from flowops.application import FlowOpsRuntime
from flowops.core.actions import ActionRegistry
from flowops.core.policies import PolicyEngine
from flowops.domain.errors import PolicyViolation
from flowops.domain.models import AWSContext, Identity, Risk, Status
from flowops.persistence.repository import Repository
from flowops.templates import blank


class ReleasingBackend:
    def __init__(self) -> None:
        self.released: list[str] = []

    def release(self, execution_id: str) -> None:
        self.released.append(execution_id)


class HardeningTests(unittest.TestCase):
    def test_audit_payloads_are_centrally_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repository = Repository(Path(temp) / "audit.db")
            repository.audit(
                "operator",
                "TEST_EVENT",
                {
                    "password": "do-not-store",
                    "reason": "Authorization: Bearer token-value",
                },
            )
            body = repository.events(limit=1)[0]["body"]
            self.assertEqual(body["password"], "[REDACTED]")
            self.assertNotIn("token-value", body["reason"])

    def test_worker_releases_provider_resources_even_for_core_only_runbook(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repository = Repository(Path(temp) / "release.db")
            backend = ReleasingBackend()
            runtime = FlowOpsRuntime.from_registry(
                repository,
                ActionRegistry(),
                policy=PolicyEngine(two_person=False),
                backend=backend,
            )
            book = blank("owner", "ops")
            revision = repository.save_draft(book, "owner")
            published = repository.publish(book.id, "owner", revision)
            actor = Identity(id="operator", roles=["ADMIN"], teams=["ops"])
            execution = runtime.engine.submit(
                published,
                actor,
                AWSContext(),
                {},
                token="release-provider-resources",
            )
            completed = runtime.worker.enqueue(execution.id).result(timeout=10)
            runtime.close()

            self.assertEqual(completed.status, Status.SUCCESS)
            self.assertEqual(backend.released, [execution.id])

    def test_generic_aws_operation_must_be_host_allowlisted(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repository = Repository(Path(temp) / "generic.db")
            context = AWSContext(
                environment="dev",
                account_id="123456789012",
                region="us-east-1",
                mode="aws",
            )
            runtime = FlowOpsRuntime.aws(
                repository,
                [context],
                generic_allowlist={"ec2.describe_instances"},
            )
            metadata = runtime.registry.get("ec2.describe_instances").metadata
            runtime.close()

            self.assertEqual(metadata.risk, Risk.CRITICAL)
            self.assertFalse(metadata.read_only)

    def test_blocked_generic_service_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repository = Repository(Path(temp) / "blocked.db")
            context = AWSContext(
                environment="dev",
                account_id="123456789012",
                region="us-east-1",
                mode="aws",
            )
            with self.assertRaises(PolicyViolation):
                FlowOpsRuntime.aws(
                    repository,
                    [context],
                    generic_allowlist={"iam.list_roles"},
                )


if __name__ == "__main__":
    unittest.main()
