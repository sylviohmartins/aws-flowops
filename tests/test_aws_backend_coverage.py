from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from flowops.core.actions import ActionContext
from flowops.domain.errors import PolicyViolation, ProviderError
from flowops.domain.models import AWSContext
from flowops.providers.aws.actions import Limits
from flowops.providers.aws.backend import BotoBackend, normalize_output, resource_scope


def aws_context(**overrides: Any) -> AWSContext:
    values: dict[str, Any] = {
        "environment": "dev",
        "account_id": "123456789012",
        "region": "sa-east-1",
        "mode": "aws",
    }
    values.update(overrides)
    return AWSContext(**values)


def action_context(aws: AWSContext | None = None, execution_id: str = "run") -> ActionContext:
    return ActionContext(execution_id, "node", aws or aws_context(), False)


class FakeSTS:
    def __init__(
        self,
        account: str = "123456789012",
        credentials: dict[str, Any] | None = None,
    ) -> None:
        self.account = account
        self.credentials = credentials
        self.assume_calls: list[dict[str, Any]] = []

    def get_caller_identity(self) -> dict[str, str]:
        return {"Account": self.account}

    def assume_role(self, **kwargs: Any) -> dict[str, Any]:
        self.assume_calls.append(kwargs)
        assert self.credentials is not None
        return {"Credentials": self.credentials}


class FakeServiceClient:
    def __init__(self) -> None:
        self.closed = False
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.meta = SimpleNamespace(
            method_to_api_mapping={"copy_object": "CopyObject"},
            service_model=SimpleNamespace(
                operation_model=lambda name: SimpleNamespace(
                    input_shape=SimpleNamespace(
                        members={"ExpectedBucketOwner": {}, "ExpectedSourceBucketOwner": {}}
                    )
                )
            ),
        )

    def close(self) -> None:
        self.closed = True

    def copy_object(self, **parameters: Any) -> dict[str, Any]:
        self.calls.append(("copy_object", parameters))
        return {"ok": True}


class FakeSession:
    def __init__(self, sts: FakeSTS, service_client: FakeServiceClient | None = None) -> None:
        self.sts = sts
        self.service_client = service_client or FakeServiceClient()
        self.client_calls: list[str] = []

    def client(self, service: str, **kwargs: Any) -> Any:
        self.client_calls.append(service)
        if service == "sts":
            return self.sts
        return self.service_client


class FakePaginator:
    def __init__(self, pages: list[dict[str, Any]], resume_token: str | None = "resume") -> None:
        self.pages = pages
        self.resume_token = resume_token
        self.calls: list[dict[str, Any]] = []

    def paginate(self, **kwargs: Any):
        self.calls.append(kwargs)
        yield from self.pages


class InvokeClient(FakeServiceClient):
    def __init__(self) -> None:
        super().__init__()
        self.paginatable = True
        self.paginator = FakePaginator([])
        self.direct_result: Any = {"value": 1}
        self.error: BaseException | None = None

    def can_paginate(self, operation: str) -> bool:
        return self.paginatable

    def get_paginator(self, operation: str) -> FakePaginator:
        return self.paginator

    def get_item(self, **parameters: Any) -> Any:
        self.calls.append(("get_item", parameters))
        if self.error is not None:
            raise self.error
        return self.direct_result


def test_resource_scope_supports_nested_cn_and_rejects_endpoint_tricks() -> None:
    context = aws_context()
    resource_scope(
        {
            "nested": [
                {"QueueUrl": "https://sqs.sa-east-1.amazonaws.com/123456789012/q"},
                {"Arn": "arn:aws:lambda:sa-east-1:123456789012:function:x"},
            ]
        },
        context,
    )
    cn = aws_context(region="cn-north-1")
    resource_scope(
        {"QueueUrl": "https://sqs.cn-north-1.amazonaws.com.cn/123456789012/q"}, cn
    )

    invalid_urls = [
        "http://sqs.sa-east-1.amazonaws.com/123456789012/q",
        "https://user@sqs.sa-east-1.amazonaws.com/123456789012/q",
        "https://sqs.sa-east-1.amazonaws.com:444/123456789012/q",
        "https://sqs.sa-east-1.amazonaws.com/123456789012/q?x=1",
        "https://sqs.sa-east-1.amazonaws.com/123456789012/q#x",
        "https://sqs.us-east-1.amazonaws.com/123456789012/q",
    ]
    for url in invalid_urls:
        with pytest.raises(PolicyViolation, match="Queue URL"):
            resource_scope({"QueueUrl": url}, context)

    for arn in (
        "arn:aws:lambda:us-east-1:123456789012:function:x",
        "arn:aws:lambda:sa-east-1:999999999999:function:x",
    ):
        with pytest.raises(PolicyViolation, match="Cross-account"):
            resource_scope({"Arn": arn}, context)


def test_normalize_output_covers_stream_bytes_dates_decimal_and_recursion() -> None:
    text = io.BytesIO(b"plain text")
    assert normalize_output(text, 100) == "plain text"
    assert text.closed

    binary_stream = io.BytesIO(b"\xff\xfe")
    assert normalize_output(binary_stream, 100) == {"encoding": "base64", "data": "//4="}
    assert binary_stream.closed
    assert normalize_output(b"abc", 100) == {"encoding": "base64", "data": "YWJj"}
    assert normalize_output(b"abcdef", 3) == {"_truncated": True, "bytes": 6}

    now = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
    value = {
        "when": now,
        "amount": Decimal("1.25"),
        "nested": [b"x", {"plain": 7}],
    }
    assert normalize_output(value, 100) == {
        "when": now.isoformat(),
        "amount": "1.25",
        "nested": [{"encoding": "base64", "data": "eA=="}, {"plain": 7}],
    }


def test_client_rejects_untrusted_context_caches_and_releases() -> None:
    trusted = aws_context()
    service_client = FakeServiceClient()
    session = FakeSession(FakeSTS(), service_client)
    factory_calls: list[dict[str, Any]] = []

    def factory(**kwargs: Any) -> FakeSession:
        factory_calls.append(kwargs)
        return session

    backend = BotoBackend([trusted], session_factory=factory)
    context = action_context(trusted)
    first = backend._client("sqs", context)
    second = backend._client("sqs", context)
    assert first is second is service_client
    assert len(factory_calls) == 1
    assert session.client_calls.count("sts") == 1
    assert session.client_calls.count("sqs") == 1

    backend.release(context.execution_id)
    assert service_client.closed is True
    assert context.execution_id not in backend.sessions
    assert (context.execution_id, "sqs") not in backend.clients

    with pytest.raises(PolicyViolation, match="trusted host"):
        backend._client("sqs", action_context(aws_context(account_id="999999999999"), "other"))


def test_client_rejects_sts_account_and_refreshes_expiring_session() -> None:
    trusted = aws_context()
    mismatched = BotoBackend(
        [trusted], session_factory=lambda **kwargs: FakeSession(FakeSTS(account="999999999999"))
    )
    with pytest.raises(PolicyViolation, match="STS account"):
        mismatched._client("sqs", action_context(trusted))

    fresh_client = FakeServiceClient()
    fresh_session = FakeSession(FakeSTS(), fresh_client)
    calls = 0

    def factory(**kwargs: Any) -> FakeSession:
        nonlocal calls
        calls += 1
        return fresh_session

    backend = BotoBackend([trusted], session_factory=factory)
    old_client = FakeServiceClient()
    backend.sessions["run"] = (fresh_session, datetime.now(UTC) + timedelta(minutes=1))
    backend.clients[("run", "old")] = old_client
    assert backend._client("sqs", action_context(trusted)) is fresh_client
    assert calls == 1
    assert ("run", "old") not in backend.clients


def test_client_assume_role_uses_external_id_and_temporary_session(monkeypatch: pytest.MonkeyPatch) -> None:
    import boto3

    expiration = datetime.now(UTC) + timedelta(hours=1)
    credentials = {
        "AccessKeyId": "A" * 20,
        "SecretAccessKey": "S" * 40,
        "SessionToken": "token",
        "Expiration": expiration,
    }
    source_sts = FakeSTS(credentials=credentials)
    source_session = FakeSession(source_sts)
    assumed_session = FakeSession(FakeSTS())
    captured: list[dict[str, Any]] = []

    def assumed_factory(**kwargs: Any) -> FakeSession:
        captured.append(kwargs)
        return assumed_session

    monkeypatch.setattr(boto3, "Session", assumed_factory)
    trusted = aws_context(
        role_arn="arn:aws:iam::123456789012:role/FlowOps",
        external_id="external",
    )
    backend = BotoBackend([trusted], session_factory=lambda **kwargs: source_session)
    assert backend._client("lambda", action_context(trusted)) is assumed_session.service_client
    assert source_sts.assume_calls == [
        {
            "RoleArn": trusted.role_arn,
            "RoleSessionName": "flowops-run",
            "DurationSeconds": 3600,
            "ExternalId": "external",
        }
    ]
    assert captured[0]["aws_session_token"] == "token"
    assert backend.sessions["run"][1] == expiration


def test_invoke_s3_owner_guards_direct_and_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    trusted = aws_context()
    context = action_context(trusted)
    backend = BotoBackend([trusted])

    s3 = InvokeClient()
    monkeypatch.setattr(backend, "_client", lambda service, ctx: s3)
    result = backend.invoke(
        "s3",
        "copy_object",
        {"Bucket": "bucket", "CopySource": "source/key"},
        context,
        Limits(),
    )
    assert result == {"ok": True}
    sent = s3.calls[-1][1]
    assert sent["ExpectedBucketOwner"] == trusted.account_id
    assert sent["ExpectedSourceBucketOwner"] == trusted.account_id

    pager_client = InvokeClient()
    pager_client.paginator = FakePaginator(
        [
            {"Items": [1, 2], "Count": 2, "Marker": "a"},
            {"Items": [3], "Count": 1, "Marker": "b"},
            {"Items": [4], "Count": 1, "Marker": "c"},
        ],
        resume_token="next",
    )
    monkeypatch.setattr(backend, "_client", lambda service, ctx: pager_client)
    paged = backend.invoke(
        "dynamodb",
        "scan",
        {},
        context,
        Limits(max_items=5, max_pages=2, paginate=True),
    )
    assert paged["Items"] == [1, 2, 3]
    assert paged["Count"] == 3
    assert paged["Marker"] == "b"
    assert paged["_flowops"] == {
        "pages": 2,
        "bounded": True,
        "possibly_more": True,
        "resume_token": "next",
    }
    assert pager_client.paginator.calls[0]["PaginationConfig"] == {"MaxItems": 5}

    pager_client.paginatable = False
    with pytest.raises(PolicyViolation, match="no SDK paginator"):
        backend.invoke(
            "dynamodb",
            "scan",
            {},
            context,
            Limits(paginate=True),
        )


def test_invoke_translates_client_timeout_and_botocore_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    from botocore.exceptions import ClientError, EndpointConnectionError, ReadTimeoutError

    trusted = aws_context()
    context = action_context(trusted)
    backend = BotoBackend([trusted])
    client = InvokeClient()
    monkeypatch.setattr(backend, "_client", lambda service, ctx: client)

    client.error = ClientError(
        {
            "Error": {"Code": "ThrottlingException", "Message": "do-not-leak"},
            "ResponseMetadata": {"RequestId": "req-1"},
        },
        "GetItem",
    )
    with pytest.raises(ProviderError) as throttled:
        backend.invoke("dynamodb", "get_item", {}, context, Limits())
    assert throttled.value.code == "ThrottlingException"
    assert throttled.value.retryable is True
    assert throttled.value.details == {"request_id": "req-1"}
    assert "do-not-leak" not in str(throttled.value)

    client.error = ClientError({"Error": {}, "ResponseMetadata": {}}, "GetItem")
    with pytest.raises(ProviderError) as generic:
        backend.invoke("dynamodb", "get_item", {}, context, Limits())
    assert generic.value.code == "AWSClientError"
    assert generic.value.retryable is False

    client.error = ReadTimeoutError(endpoint_url="https://example.invalid")
    with pytest.raises(ProviderError) as timeout:
        backend.invoke("dynamodb", "get_item", {}, context, Limits())
    assert timeout.value.code == "Timeout"
    assert timeout.value.ambiguous is True

    client.error = EndpointConnectionError(endpoint_url="https://example.invalid")
    with pytest.raises(ProviderError) as core:
        backend.invoke("dynamodb", "get_item", {}, context, Limits())
    assert core.value.code == "EndpointConnectionError"
    assert core.value.ambiguous is True
