"""Low-volume DynamoDB catalog for reusable runbooks.

The catalog is an index of definitions, not the execution journal. Execution snapshots,
approvals and audit events continue using Repository so workers can recover after a browser
closes. A missing table is created on an explicit save/publish operation with on-demand
capacity; transient failures are returned to the host so it can offer browser-local storage.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from flowops.core.actions import ActionContext
from flowops.domain.models import AWSContext, Runbook, new_id

TABLE_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,255}$")
MAX_ITEM_BYTES = 300_000


@dataclass(frozen=True)
class CatalogResult:
    ok: bool
    mode: str
    message: str
    item: dict[str, Any] | None = None


class DynamoRunbookCatalog:
    def __init__(self, backend: Any, context: AWSContext, *, table_name: str | None = None):
        self.backend = backend
        self.context = context.model_copy(deep=True)
        candidate = table_name or os.getenv("FLOWOPS_CATALOG_TABLE") or "flowops-runbook-catalog"
        if not TABLE_PATTERN.fullmatch(candidate):
            raise ValueError("FLOWOPS_CATALOG_TABLE must contain only AWS table-name characters.")
        self.table_name = candidate

    def _client(self) -> tuple[Any, str]:
        execution_id = f"catalog-{new_id()}"
        client = self.backend.client_for_host(
            "dynamodb", ActionContext(execution_id, "catalog", self.context, False)
        )
        return client, execution_id

    def _ensure_table(self, client: Any) -> None:
        try:
            client.describe_table(TableName=self.table_name)
            return
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
                raise
        try:
            client.create_table(
                TableName=self.table_name,
                KeySchema=[
                    {"AttributeName": "pk", "KeyType": "HASH"},
                    {"AttributeName": "sk", "KeyType": "RANGE"},
                ],
                AttributeDefinitions=[
                    {"AttributeName": "pk", "AttributeType": "S"},
                    {"AttributeName": "sk", "AttributeType": "S"},
                ],
                BillingMode="PAY_PER_REQUEST",
                Tags=[{"Key": "managed-by", "Value": "aws-flowops"}],
            )
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") != "ResourceInUseException":
                raise
        for _ in range(20):
            table = client.describe_table(TableName=self.table_name).get("Table", {})
            if table.get("TableStatus") in {None, "ACTIVE"}:
                return
            time.sleep(0.25)
        raise TimeoutError("Catalog DynamoDB table did not become ACTIVE within 5 seconds.")

    def _keys(self, book: Runbook) -> dict[str, dict[str, str]]:
        return {
            "pk": {"S": f"ACCOUNT#{self.context.account_id}#TEAM#{book.team}"},
            "sk": {"S": f"RUNBOOK#{book.id}#VERSION#{book.version:010d}"},
        }

    def save(self, book: Runbook) -> CatalogResult:
        body = book.model_dump(mode="json")
        encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        if len(encoded) > MAX_ITEM_BYTES:
            return CatalogResult(
                False, "fallback", "Runbook exceeds the bounded catalog item size."
            )
        client = None
        execution_id = ""
        try:
            client, execution_id = self._client()
            self._ensure_table(client)
            item = self._keys(book) | {
                "runbook_id": {"S": book.id},
                "name": {"S": book.name},
                "version": {"N": str(book.version)},
                "updated_at": {"S": book.updated_at},
                "body": {"S": encoded.decode()},
            }
            client.put_item(TableName=self.table_name, Item=item)
            return CatalogResult(True, "dynamodb", "Runbook catalog synchronized.", item)
        except (BotoCoreError, ClientError, TimeoutError, OSError) as error:
            code = (
                error.response.get("Error", {}).get("Code", "transport")
                if isinstance(error, ClientError)
                else type(error).__name__
            )
            return CatalogResult(
                False,
                "fallback",
                f"DynamoDB catalog unavailable ({code}); browser copy is available.",
            )
        finally:
            if execution_id:
                release = getattr(self.backend, "release", None)
                if callable(release):
                    release(execution_id)

    def list(self, team: str = "default", *, limit: int = 100) -> list[Runbook]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Catalog list limit must be between 1 and 1000.")
        client, execution_id = self._client()
        try:
            self._ensure_table(client)
            response = client.query(
                TableName=self.table_name,
                KeyConditionExpression="#pk = :pk",
                ExpressionAttributeNames={"#pk": "pk"},
                ExpressionAttributeValues={
                    ":pk": {"S": f"ACCOUNT#{self.context.account_id}#TEAM#{team}"}
                },
                Limit=limit,
                ScanIndexForward=False,
            )
            books: list[Runbook] = []
            for item in response.get("Items", []):
                try:
                    books.append(Runbook.model_validate_json(item["body"]["S"]))
                except (KeyError, TypeError, ValueError):
                    continue
            return books
        finally:
            release = getattr(self.backend, "release", None)
            if callable(release):
                release(execution_id)
