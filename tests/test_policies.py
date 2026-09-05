import unittest

from flowops.core.actions import Metadata
from flowops.core.policies import PolicyEngine, permissions, require
from flowops.domain.errors import AuthorizationError, PolicyViolation
from flowops.domain.models import AWSContext, Execution, Identity, Risk, Runbook


class PolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.book = Runbook(
            name="Payments recovery",
            team="payments",
            environments=["dev", "production"],
            version=1,
        )

    def execution(
        self, actor: Identity, *, environment: str = "production", reason: str = "INC-1"
    ) -> Execution:
        return Execution(
            runbook_id=self.book.id,
            runbook_version=self.book.version,
            snapshot=self.book,
            snapshot_hash="test-only",
            actor=actor,
            aws_context=AWSContext(environment=environment),
            dry_run=False,
            reason=reason,
        )

    def test_roles_are_additive_and_team_scoped(self) -> None:
        viewer = Identity(id="viewer", roles=["VIEWER"], teams=["payments"])
        self.assertEqual(permissions(viewer), {"runbook.read"})
        require(viewer, "runbook.read", self.book)
        with self.assertRaises(AuthorizationError):
            require(viewer, "runbook.edit", self.book)

        outsider = Identity(id="author", roles=["AUTHOR"], teams=["other"])
        with self.assertRaises(AuthorizationError):
            require(outsider, "runbook.read", self.book)

    def test_production_requires_explicit_permission_and_reason(self) -> None:
        policy = PolicyEngine()
        operator = Identity(id="operator", roles=["OPERATOR"], teams=["payments"])
        with self.assertRaises(AuthorizationError):
            policy.execution(self.execution(operator))

        production_operator = Identity(
            id="operator",
            roles=["OPERATOR"],
            permissions=["runbook.execute.production"],
            teams=["payments"],
        )
        with self.assertRaises(PolicyViolation):
            policy.execution(self.execution(production_operator, reason=""))
        policy.execution(self.execution(production_operator, reason="INC-1234"))

    def test_critical_mutation_requires_destructive_grant_and_approval(self) -> None:
        policy = PolicyEngine()
        metadata = Metadata(
            "test.destroy",
            "aws",
            "test",
            "destroy",
            "Critical mutation",
            risk=Risk.CRITICAL,
            read_only=False,
            idempotent=False,
        )
        operator = Identity(
            id="operator",
            roles=["OPERATOR"],
            permissions=["runbook.execute.production"],
            teams=["payments"],
        )
        execution = self.execution(operator)
        policy.execution(execution)
        with self.assertRaises(AuthorizationError):
            policy.action(execution, metadata)

        destructive = operator.model_copy(
            update={"permissions": ["runbook.execute.production", "aws.destructive"]}
        )
        guarded = self.execution(destructive)
        policy.execution(guarded)
        self.assertTrue(policy.action(guarded, metadata, affected=1))

    def test_bulk_limit_fails_closed(self) -> None:
        policy = PolicyEngine(max_affected=10)
        metadata = Metadata(
            "test.write",
            "aws",
            "test",
            "write",
            "Mutation",
            risk=Risk.HIGH,
            read_only=False,
        )
        operator = Identity(id="operator", roles=["OPERATOR"], teams=["payments"])
        execution = self.execution(operator, environment="dev")
        policy.execution(execution)
        with self.assertRaises(PolicyViolation):
            policy.action(execution, metadata, affected=11)


if __name__ == "__main__":
    unittest.main()
