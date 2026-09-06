import base64
import tempfile
import unittest
from pathlib import Path
from typing import Any

from flowops.core.actions import ActionRegistry
from flowops.domain.errors import AuthorizationError, WorkflowValidationError
from flowops.domain.models import AWSContext, Identity, Node
from flowops.persistence.repository import Repository
from flowops.providers.aws.actions import build_registry
from flowops.providers.aws.demo import DemoBackend
from flowops.providers.aws.lambda_review import change_preview, review_lambda
from flowops.streamlit.canvas import duplicate_node
from flowops.templates import blank


class LambdaReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.current: dict[str, Any] = {
            "Configuration": {
                "FunctionName": "payment-processor",
                "PackageType": "Zip",
                "Runtime": "python3.12",
                "RevisionId": "revision-1",
                "Environment": {"Variables": {"DB_URL": "never-display", "unchanged": "hidden"}},
            },
            "Code": {"Location": "https://example.test/presigned-secret", "RepositoryType": "S3"},
            "Aliases": [{"Name": "live", "FunctionVersion": "1", "RevisionId": "alias-1"}],
        }

    def test_configuration_review_hides_environment_values_and_download_urls(self) -> None:
        result = change_preview(
            self.current,
            "lambda.update_function_configuration",
            {
                "Timeout": 15,
                "Environment": {"Variables": {"DB_URL": "new-secret", "unchanged": "hidden"}},
            },
        )
        self.assertIn("CURRENT", result["diff"])
        self.assertIn("PROPOSED", result["diff"])
        self.assertEqual(result["proposed"]["Configuration"]["Timeout"], 15)
        self.assertEqual(result["proposed"]["EnvironmentVariablesChanged"], ["DB_URL"])
        self.assertEqual(result["revision_id"], "revision-1")
        for secret in ("never-display", "new-secret", "presigned-secret", '"hidden"'):
            self.assertNotIn(secret, str(result))
        self.assertNotIn("Timeout", self.current["Configuration"])

    def test_zip_s3_image_alias_and_version_review(self) -> None:
        content = base64.b64encode(b"zip artifact bytes").decode()
        zip_review = change_preview(
            self.current, "lambda.update_function_code", {"ZipFile": {"base64": content}}
        )
        self.assertEqual(zip_review["proposed"]["ProposedArtifact"]["ZipFile"]["bytes"], 18)
        self.assertNotIn(content, str(zip_review))
        s3 = change_preview(
            self.current,
            "lambda.update_function_code",
            {
                "S3Bucket": "artifacts",
                "S3Key": "payment.zip",
                "S3ObjectVersion": "immutable-version",
            },
        )
        self.assertEqual(s3["proposed"]["ProposedArtifact"]["S3ObjectVersion"], "immutable-version")
        self.current["Configuration"]["PackageType"] = "Image"
        image = change_preview(
            self.current,
            "lambda.update_function_code",
            {"ImageUri": "account.dkr.ecr.region.amazonaws.com/repo@sha256:123"},
        )
        self.assertIn("ImageUri", image["diff"])
        for operation in ("create_alias", "update_alias", "delete_alias"):
            result = change_preview(
                self.current, f"lambda.{operation}", {"Name": "live", "FunctionVersion": "2"}
            )
            if operation == "delete_alias":
                self.assertEqual(result["proposed"]["Aliases"], [])
            else:
                self.assertEqual(result["proposed"]["Aliases"][0]["FunctionVersion"], "2")
            self.assertEqual(
                result["revision_id"], "alias-1" if operation == "update_alias" else None
            )
        published = change_preview(
            self.current, "lambda.publish_version", {"Description": "Release"}
        )
        self.assertIn("PublishVersion", published["proposed"])

    def test_invalid_artifacts_and_unresolved_functions_fail_closed(self) -> None:
        for config in (
            {},
            {"ImageUri": "image", "S3Bucket": "b", "S3Key": "k"},
            {"ImageUri": "image"},
            {"ZipFile": {"base64": "%%%"}},
        ):
            with self.assertRaises(WorkflowValidationError):
                change_preview(self.current, "lambda.update_function_code", config)
        with self.assertRaises(WorkflowValidationError):
            change_preview(self.current, "lambda.update_alias", {})
        with self.assertRaises(WorkflowValidationError):
            change_preview(self.current, "lambda.invoke", {})
        for config in ({}, {"FunctionName": "{{ params.function }}"}):
            with self.assertRaises(WorkflowValidationError):
                review_lambda(
                    ActionRegistry(),
                    Identity(id="admin", roles=["ADMIN"]),
                    AWSContext(),
                    "lambda.update_function_code",
                    config,
                )
        with self.assertRaises(WorkflowValidationError):
            review_lambda(
                ActionRegistry(),
                Identity(id="admin", roles=["ADMIN"]),
                AWSContext(),
                "lambda.invoke",
                {},
            )
        with self.assertRaises(AuthorizationError):
            review_lambda(
                ActionRegistry(),
                Identity(id="viewer", roles=["VIEWER"]),
                AWSContext(),
                "lambda.update_function_code",
                {},
            )

    def test_demo_current_state_and_backend_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            backend = DemoBackend(Repository(Path(directory) / "demo.db"))
            released: list[str] = []
            backend.release = released.append  # type: ignore[attr-defined]
            result = review_lambda(
                build_registry(backend),
                Identity(id="admin", roles=["ADMIN"]),
                AWSContext(),
                "lambda.update_function_configuration",
                {"FunctionName": "payment-processor", "Timeout": 10},
            )
            self.assertEqual(result["current"]["Configuration"]["PackageType"], "Zip")
            self.assertEqual(result["current"]["Aliases"][0]["Name"], "live")
            self.assertEqual(result["current"]["Versions"][0]["Version"], "1")
            self.assertEqual(len(released), 1)

    def test_duplicate_preserves_definition_without_sharing_config_or_edges(self) -> None:
        book = blank("author", "ops")
        book.nodes.insert(1, Node(id="work", action="core.wait", config={"seconds": 1}))
        copied, copied_id = duplicate_node(book, "work")
        duplicate = next(node for node in copied.nodes if node.id == copied_id)
        duplicate.config["seconds"] = 2
        self.assertEqual(book.nodes[1].config["seconds"], 1)
        self.assertEqual(copied.edges, book.edges)
        self.assertNotEqual(duplicate.position, book.nodes[1].position)
        for node_id in ("start", "missing"):
            with self.assertRaises(WorkflowValidationError):
                duplicate_node(book, node_id)
        book.nodes = [Node(id=f"n{i}", action="core.wait") for i in range(200)]
        with self.assertRaises(WorkflowValidationError):
            duplicate_node(book, "n0")
