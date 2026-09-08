"""Explicit loopback emulator transport; never resolves real AWS credentials."""

import os
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from flowops.core.actions import ActionContext
from flowops.domain.errors import PolicyViolation
from flowops.domain.models import AWSContext
from flowops.providers.aws.backend import BotoBackend

LOCAL_ENDPOINT = "http://127.0.0.1:5000"
LOCAL_ACCOUNT = "123456789012"


def local_context() -> AWSContext:
    return AWSContext(mode="local", account_id=LOCAL_ACCOUNT, environment="dev", region="sa-east-1")


def validate_local_endpoint(endpoint: str) -> str:
    try:
        url = urlparse(endpoint)
        valid = (
            url.scheme == "http"
            and url.hostname == "127.0.0.1"
            and url.port is not None
            and 1 <= url.port <= 65535
            and url.path in {"", "/"}
            and not (url.username or url.password or url.query or url.fragment)
        )
    except ValueError:
        valid = False
    if not valid:
        raise PolicyViolation("Local AWS endpoint must be http://127.0.0.1:<port>.")
    return endpoint.rstrip("/")


def local_session() -> Any:
    from botocore.session import Session

    # Session-local configuration overrides also ignore an ambient AWS_PROFILE/config file.
    # Do not temporarily modify process environment: other workers may use real AWS.
    session = Session(
        session_vars={
            "profile": (None, None, None, None),
            "config_file": (None, None, os.devnull, None),
            "credentials_file": (None, None, os.devnull, None),
        }
    )
    session.set_credentials("testing", "testing", "testing")
    return session


def local_client(service: str, *, endpoint: str = LOCAL_ENDPOINT, region: str = "sa-east-1") -> Any:
    from botocore.config import Config

    return local_session().create_client(
        service,
        region_name=region,
        endpoint_url=validate_local_endpoint(endpoint),
        config=Config(
            connect_timeout=3,
            read_timeout=30,
            retries={"total_max_attempts": 1},
            proxies={},
            ignore_configured_endpoint_urls=True,
            s3={"addressing_style": "path"},
        ),
    )


class LocalAWSBackend(BotoBackend):
    def __init__(self, contexts: list[AWSContext], *, endpoint: str = LOCAL_ENDPOINT):
        if not contexts or any(
            c.mode != "local"
            or c.environment != "dev"
            or c.account_id != LOCAL_ACCOUNT
            or c.profile
            or c.role_arn
            or c.external_id
            for c in contexts
        ):
            raise PolicyViolation("Local AWS requires dev, the lab account and no profile/role.")
        super().__init__(contexts)
        self.queue_endpoint = validate_local_endpoint(endpoint)

    def _client(self, service: str, context: ActionContext) -> Any:
        aws = context.aws
        if self.contexts.get(aws.environment) != aws or aws.mode != "local":
            raise PolicyViolation("Local AWS context was not configured by the trusted host.")
        with self.lock:
            if context.execution_id not in self.sessions:
                sts = local_client(
                    "sts", endpoint=self.queue_endpoint or LOCAL_ENDPOINT, region=aws.region
                )
                try:
                    if sts.get_caller_identity()["Account"] != LOCAL_ACCOUNT:
                        raise PolicyViolation("Emulator account differs from the configured lab.")
                finally:
                    sts.close()
                self.sessions[context.execution_id] = (None, datetime.now(UTC) + timedelta(hours=1))
            key = (context.execution_id, service)
            if key not in self.clients:
                self.clients[key] = local_client(
                    service, endpoint=self.queue_endpoint or LOCAL_ENDPOINT, region=aws.region
                )
            return self.clients[key]
