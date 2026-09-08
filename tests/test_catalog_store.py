from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest
from botocore.exceptions import BotoCoreError, ClientError

from flowops.domain.models import AWSContext, Runbook
from flowops.providers.aws.catalog_store import DynamoRunbookCatalog


def not_found(operation: str) -> ClientError:
    return ClientError({"Error": {"Code": "ResourceNotFoundException"}}, operation)


class FakeClient:
    def __init__(
        self,
        *,
        fail: Exception | None = None,
        create_error: Exception | None = None,
        statuses: list[str] | None = None,
        malformed: bool = False,
    ) -> None:
        self.fail = fail
        self.create_error = create_error
        self.statuses = list(statuses or ["ACTIVE"])
        self.malformed = malformed
        self.created: list[dict[str, Any]] = []
        self.items: list[dict[str, Any]] = []
        self.described = False

    def describe_table(self, **kwargs: Any) -> dict[str, Any]:
        if not self.described:
            raise not_found("DescribeTable")
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return {"Table": {"TableStatus": status, "TableName": kwargs["TableName"]}}

    def create_table(self, **kwargs: Any) -> dict[str, Any]:
        if self.create_error:
            self.described = True
            raise self.create_error
        self.described = True
        self.created.append(kwargs)
        return {"TableDescription": {"TableStatus": "CREATING"}}

    def put_item(self, **kwargs: Any) -> dict[str, Any]:
        if self.fail:
            raise self.fail
        self.items.append(kwargs["Item"])
        return {}

    def query(self, **kwargs: Any) -> dict[str, Any]:
        items: list[dict[str, Any]] = self.items[: kwargs["Limit"]]
        if self.malformed:
            items.append({"body": {"N": "not-json"}})
        return {"Items": items}


class FakeBackend:
    def __init__(self, client: FakeClient) -> None:
        self.client = client
        self.released: list[str] = []

    def client_for_host(self, service: str, context: Any) -> FakeClient:
        assert service == "dynamodb"
        return self.client

    def release(self, execution_id: str) -> None:
        self.released.append(execution_id)


def test_missing_table_is_created_on_demand_and_scoped_by_account_team() -> None:
    client = FakeClient()
    backend = FakeBackend(client)
    catalog = DynamoRunbookCatalog(
        backend, AWSContext(account_id="123456789012", mode="local"), table_name="catalog-test"
    )
    book = Runbook(name="XPTO", team="payments", version=1)
    result = catalog.save(book)
    assert result.ok is True
    assert result.mode == "dynamodb"
    assert client.created[0]["BillingMode"] == "PAY_PER_REQUEST"
    assert client.created[0]["KeySchema"] == [
        {"AttributeName": "pk", "KeyType": "HASH"},
        {"AttributeName": "sk", "KeyType": "RANGE"},
    ]
    assert client.items[0]["pk"]["S"] == "ACCOUNT#123456789012#TEAM#payments"
    assert client.items[0]["sk"]["S"].endswith("VERSION#0000000001")
    assert catalog.list("payments")[0].id == book.id
    assert len(backend.released) == 2


def test_catalog_failure_returns_browser_fallback_without_exposing_error_payload() -> None:
    client = FakeClient(
        fail=ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "secret"}}, "PutItem"
        )
    )
    catalog = DynamoRunbookCatalog(FakeBackend(client), AWSContext(mode="local"))
    result = catalog.save(Runbook(name="Fallback", version=0))
    assert result.ok is False
    assert result.mode == "fallback"
    assert "AccessDeniedException" in result.message
    assert "secret" not in result.message


def test_invalid_catalog_name_and_item_size_fail_closed() -> None:
    with pytest.raises(ValueError):
        DynamoRunbookCatalog(FakeBackend(FakeClient()), AWSContext(), table_name="bad/name")
    book = Runbook(name="Huge")
    book.description = "x" * 300_001
    result = DynamoRunbookCatalog(FakeBackend(FakeClient()), AWSContext()).save(book)
    assert result.mode == "fallback"
    assert "size" in result.message


def test_saved_body_is_json_without_credentials() -> None:
    client = FakeClient()
    catalog = DynamoRunbookCatalog(FakeBackend(client), AWSContext(mode="local"))
    book = Runbook(name="Safe")
    catalog.save(book)
    assert json.loads(client.items[0]["body"]["S"])["name"] == "Safe"
    assert "secret" not in client.items[0]["body"]["S"].lower()


def test_catalog_handles_races_delayed_activation_and_malformed_items() -> None:
    race = ClientError({"Error": {"Code": "ResourceInUseException"}}, "CreateTable")
    client = FakeClient(create_error=race, statuses=["CREATING", "ACTIVE"], malformed=True)
    backend = FakeBackend(client)
    catalog = DynamoRunbookCatalog(backend, AWSContext(mode="local"))
    with patch("flowops.providers.aws.catalog_store.time.sleep"):
        result = catalog.save(Runbook(name="Race"))
    assert result.ok is True
    assert catalog.list()[0].name == "Race"
    assert catalog.list(limit=100)[0].name == "Race"
    with pytest.raises(ValueError):
        catalog.list(limit=0)


def test_catalog_converts_transport_timeout_and_non_not_found_errors_to_fallback() -> None:
    transport = FakeClient(fail=BotoCoreError())
    result = DynamoRunbookCatalog(FakeBackend(transport), AWSContext(mode="local")).save(
        Runbook(name="Transport")
    )
    assert result.mode == "fallback"
    stuck = FakeClient(statuses=["CREATING"])
    with patch("flowops.providers.aws.catalog_store.time.sleep"):
        result = DynamoRunbookCatalog(FakeBackend(stuck), AWSContext(mode="local")).save(
            Runbook(name="Timeout")
        )
    assert result.mode == "fallback"
    unexpected = FakeClient()
    unexpected.described = False
    unexpected.describe_table = lambda **kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        ClientError({"Error": {"Code": "AccessDeniedException"}}, "DescribeTable")
    )
    with pytest.raises(ClientError):
        DynamoRunbookCatalog(FakeBackend(unexpected), AWSContext(mode="local")).list()
