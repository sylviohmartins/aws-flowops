import unittest

from flowops.core.actions import ActionContext
from flowops.domain.errors import PolicyViolation, ProviderError, WorkflowValidationError
from flowops.domain.models import AWSContext
from flowops.providers.aws.redrive import RedriveMessages


class Backend:
    def __init__(self, *, fail_at: str = "", empty: bool = False):
        self.calls = []
        self.fail_at = fail_at
        self.empty = empty

    def invoke(self, service, operation, parameters, context, limits):
        self.calls.append((operation, parameters))
        if operation == self.fail_at:
            raise ProviderError("ServiceUnavailable")
        if operation == "receive_message":
            return (
                {}
                if self.empty
                else {
                    "Messages": [
                        {
                            "MessageId": "one",
                            "ReceiptHandle": "private-one",
                            "Body": '{"payment_id":"one"}',
                            "Attributes": {"MessageGroupId": "original"},
                        },
                        {
                            "MessageId": "two",
                            "ReceiptHandle": "private-two",
                            "Body": '{"payment_id":"two"}',
                        },
                    ]
                }
            )
        return {"MessageId": "sent"}


class RedriveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = ActionContext("exec", "redrive", AWSContext(), False)
        root = "https://sqs.sa-east-1.amazonaws.com/000000000000/"
        self.config = {
            "SourceQueueUrl": root + "errors.fifo",
            "DestinationQueueUrl": root + "destination.fifo",
            "MaxMessages": 3,
        }

    def test_handles_never_leave_action_and_originals_are_deleted_after_all_sends(self) -> None:
        backend = Backend()
        action = RedriveMessages(backend)
        self.assertEqual(action.affected_records(self.config), 3)
        self.assertTrue(action.preview(self.config, self.context)["simulation"])
        self.assertEqual(backend.calls, [])
        result = action.execute(self.config, self.context)
        self.assertEqual(
            result, {"received": 2, "sent": 2, "deleted": 2, "message_ids": ["one", "two"]}
        )
        self.assertNotIn("private", str(result))
        self.assertEqual(
            [call[0] for call in backend.calls],
            ["receive_message", "send_message", "send_message", "delete_message", "delete_message"],
        )
        self.assertEqual(backend.calls[1][1]["MessageGroupId"], "original")
        self.assertEqual(backend.calls[2][1]["MessageGroupId"], "flowops-redrive")
        self.assertIn("FlowOpsExecutionId", backend.calls[1][1]["MessageAttributes"])
        backend.calls.clear()
        action.execute(
            self.config
            | {"DestinationQueueUrl": self.config["DestinationQueueUrl"].removesuffix(".fifo")},
            self.context,
        )
        self.assertNotIn("MessageDeduplicationId", backend.calls[1][1])
        self.assertEqual(
            RedriveMessages(Backend(empty=True)).execute(self.config, self.context)["received"], 0
        )

    def test_failed_send_never_acknowledges_and_partial_delete_is_explicit(self) -> None:
        for stage in ("send_message", "delete_message"):
            backend = Backend(fail_at=stage)
            with self.assertRaises(ProviderError) as error:
                RedriveMessages(backend).execute(self.config, self.context)
            self.assertEqual(error.exception.code, "RedrivePartialFailure")
            self.assertTrue(error.exception.ambiguous)
            self.assertNotIn("private", str(error.exception.details))
            if stage == "send_message":
                self.assertNotIn("delete_message", [call[0] for call in backend.calls])
            else:
                self.assertEqual(error.exception.details["sent_message_ids"], ["one", "two"])

    def test_limits_and_both_resource_scopes_checked_before_receive(self) -> None:
        backend = Backend()
        action = RedriveMessages(backend)
        for config in (
            {},
            self.config | {"Extra": 1},
            self.config | {"SourceQueueUrl": 12},
            self.config | {"DestinationQueueUrl": self.config["SourceQueueUrl"]},
            self.config | {"MaxMessages": True},
            self.config | {"MaxMessages": 11},
        ):
            with self.subTest(config=config), self.assertRaises(WorkflowValidationError):
                action.execute(config, self.context)
        with self.assertRaises(PolicyViolation):
            action.execute(
                self.config
                | {"DestinationQueueUrl": "https://example.invalid/000000000000/destination"},
                self.context,
            )
        self.assertEqual(backend.calls, [])
