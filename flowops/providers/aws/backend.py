"""Trusted account-bound boto3 adapter. Credentials remain in the SDK's memory only."""

import base64
import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

from flowops.core.actions import ActionContext
from flowops.domain.errors import PolicyViolation, ProviderError
from flowops.domain.models import AWSContext
from flowops.providers.aws.actions import Limits

LOG = logging.getLogger("flowops.aws")


def resource_scope(parameters: Any, context: AWSContext) -> None:
    """Prevent cross-account/region resources and user-controlled queue endpoints."""
    if isinstance(parameters, dict):
        for key, value in parameters.items():
            if key == "QueueUrl" and isinstance(value, str):
                parsed = urlparse(value)
                suffix = "amazonaws.com.cn" if context.region.startswith("cn-") else "amazonaws.com"
                if (
                    parsed.scheme != "https"
                    or parsed.hostname != f"sqs.{context.region}.{suffix}"
                    or parsed.port not in (None, 443)
                    or parsed.username
                    or parsed.password
                    or parsed.query
                    or parsed.fragment
                    or not parsed.path.startswith(f"/{context.account_id}/")
                ):
                    raise PolicyViolation(
                        "Queue URL must belong to the selected AWS account and region."
                    )
            if isinstance(value, str) and value.startswith("arn:"):
                parts = value.split(":", 5)
                if (
                    len(parts) != 6
                    or parts[4] not in {"", context.account_id}
                    or parts[3] not in {"", context.region}
                ):
                    raise PolicyViolation(
                        "Cross-account or cross-region resource reference denied."
                    )
            resource_scope(value, context)
    elif isinstance(parameters, list):
        for value in parameters:
            resource_scope(value, context)


def normalize_output(value: Any, max_bytes: int) -> Any:
    if hasattr(value, "read") and hasattr(value, "close"):
        try:
            data = value.read(max_bytes + 1)
            if len(data) > max_bytes:
                return {"_truncated": True, "limit": max_bytes, "reason": "stream size"}
            try:
                text = data.decode("utf-8")
                try:
                    return json_load(text)
                except ValueError:
                    return text
            except UnicodeDecodeError:
                return {"encoding": "base64", "data": base64.b64encode(data).decode()}
        finally:
            value.close()
    if isinstance(value, bytes):
        if len(value) > max_bytes:
            return {"_truncated": True, "bytes": len(value)}
        return {"encoding": "base64", "data": base64.b64encode(value).decode()}
    if isinstance(value, dict):
        return {k: normalize_output(v, max_bytes) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize_output(v, max_bytes) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def json_load(value: str) -> Any:
    import json

    return json.loads(value)


class BotoBackend:
    """Trusted contexts are supplied by the host, never by an imported runbook."""

    def __init__(self, contexts: list[AWSContext], *, session_factory: Any = None):
        self.contexts = {c.environment: c.model_copy(deep=True) for c in contexts}
        self.session_factory = session_factory
        self.sessions: dict[str, tuple[Any, datetime]] = {}
        self.clients: dict[tuple[str, str], Any] = {}
        self.lock = threading.RLock()

    def _client(self, service: str, context: ActionContext) -> Any:
        import boto3
        from botocore.config import Config

        aws = context.aws
        trusted = self.contexts.get(aws.environment)
        if trusted != aws or aws.mode != "aws":
            raise PolicyViolation("AWS context was not configured by the trusted host.")
        with self.lock:
            entry = self.sessions.get(context.execution_id)
            if entry is None or entry[1] < datetime.now(UTC) + timedelta(minutes=5):
                session = (self.session_factory or boto3.Session)(
                    profile_name=aws.profile, region_name=aws.region
                )
                expires = datetime.now(UTC) + timedelta(hours=1)
                sdk_config = Config(
                    connect_timeout=5,
                    read_timeout=30,
                    retries={"mode": "standard", "total_max_attempts": 1},
                    user_agent_extra=f"flowops/{context.execution_id}",
                    ignore_configured_endpoint_urls=True,
                )
                if aws.role_arn:
                    role: dict[str, Any] = {
                        "RoleArn": aws.role_arn,
                        "RoleSessionName": f"flowops-{context.execution_id[:40]}",
                        "DurationSeconds": 3600,
                    }
                    if aws.external_id:
                        role["ExternalId"] = aws.external_id
                    credentials = session.client("sts", config=sdk_config).assume_role(**role)[
                        "Credentials"
                    ]
                    session = boto3.Session(
                        aws_access_key_id=credentials["AccessKeyId"],
                        aws_secret_access_key=credentials["SecretAccessKey"],
                        aws_session_token=credentials["SessionToken"],
                        region_name=aws.region,
                    )
                    expires = credentials["Expiration"]
                identity = session.client("sts", config=sdk_config).get_caller_identity()
                if identity["Account"] != aws.account_id:
                    raise PolicyViolation("STS account differs from the selected account.")
                self.sessions[context.execution_id] = (session, expires)
                self.clients = {
                    key: client
                    for key, client in self.clients.items()
                    if key[0] != context.execution_id
                }
                entry = session, expires
            key = (context.execution_id, service)
            if key not in self.clients:
                self.clients[key] = entry[0].client(
                    service,
                    config=Config(
                        connect_timeout=5,
                        read_timeout=30,
                        retries={"mode": "standard", "total_max_attempts": 1},
                        user_agent_extra=f"flowops/{context.execution_id}",
                        ignore_configured_endpoint_urls=True,
                    ),
                )
            return self.clients[key]

    def release(self, execution_id: str) -> None:
        with self.lock:
            self.sessions.pop(execution_id, None)
            for key in [key for key in self.clients if key[0] == execution_id]:
                self.clients.pop(key).close()

    def invoke(
        self,
        service: str,
        operation: str,
        parameters: dict[str, Any],
        context: ActionContext,
        limits: Limits,
    ) -> Any:
        from botocore.exceptions import (
            BotoCoreError,
            ClientError,
            ConnectTimeoutError,
            ReadTimeoutError,
        )

        resource_scope(parameters, context.aws)
        start = time.monotonic()
        try:
            client = self._client(service, context)
            parameters = dict(parameters)
            # Bucket names carry no account. Require owner checks whenever the SDK supports them.
            if service == "s3" and "Bucket" in parameters:
                model = client.meta.service_model.operation_model(
                    client.meta.method_to_api_mapping[operation]
                )
                if "ExpectedBucketOwner" in model.input_shape.members:
                    parameters["ExpectedBucketOwner"] = context.aws.account_id
                if (
                    "CopySource" in parameters
                    and "ExpectedSourceBucketOwner" in model.input_shape.members
                ):
                    parameters["ExpectedSourceBucketOwner"] = context.aws.account_id
            if limits.paginate:
                if not client.can_paginate(operation):
                    raise PolicyViolation("This AWS operation has no SDK paginator.")
                iterator = client.get_paginator(operation).paginate(
                    **parameters, PaginationConfig={"MaxItems": limits.max_items}
                )
                result: dict[str, Any] = {}
                pages = 0
                for page in iterator:
                    pages += 1
                    for key, value in page.items():
                        if isinstance(value, list):
                            result.setdefault(key, []).extend(value)
                        elif key in {"Count", "ScannedCount"}:
                            result[key] = result.get(key, 0) + value
                        else:
                            result[key] = value
                    if pages >= limits.max_pages:
                        break
                result["_flowops"] = {
                    "pages": pages,
                    "bounded": True,
                    "possibly_more": pages >= limits.max_pages,
                    "resume_token": iterator.resume_token,
                }
            else:
                result = getattr(client, operation)(**parameters)
            return normalize_output(result, limits.max_bytes)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", "AWSClientError"))
            # AWS error messages can include user data; retain code/request ID only.
            error = ProviderError(
                code,
                retryable=code
                in {
                    "Throttling",
                    "ThrottlingException",
                    "ProvisionedThroughputExceededException",
                    "ServiceUnavailable",
                },
            )
            error.details = {
                "request_id": exc.response.get("ResponseMetadata", {}).get("RequestId")
            }
            raise error from exc
        except (ReadTimeoutError, ConnectTimeoutError) as exc:
            raise ProviderError("Timeout", ambiguous=True) from exc
        except BotoCoreError as exc:
            raise ProviderError(type(exc).__name__, ambiguous=True) from exc
        finally:
            LOG.info(
                "aws_api_call",
                extra={
                    "execution_id": context.execution_id,
                    "node_id": context.node_id,
                    "service": service,
                    "action": operation,
                    "account": context.aws.account_id,
                    "region": context.aws.region,
                    "duration_seconds": time.monotonic() - start,
                },
            )
