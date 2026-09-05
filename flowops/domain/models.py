"""JSON-compatible, versioned definitions shared by UI, repositories and workers."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


def new_id() -> str:
    return uuid4().hex


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Status(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"


class Risk(StrEnum):
    READ_ONLY = "READ_ONLY"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RetryPolicy(Model):
    max_attempts: int = Field(default=1, ge=1, le=5)
    backoff_seconds: float = Field(default=0.2, ge=0, le=10)
    retry_codes: list[str] = Field(
        default_factory=lambda: [
            "ThrottlingException",
            "Throttling",
            "ServiceUnavailable",
            "ProvisionedThroughputExceededException",
        ]
    )


class Node(Model):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
    action: str = Field(min_length=1, max_length=120)
    label: str = Field(default="", max_length=120)
    node_version: Literal[1] = 1
    config: dict[str, Any] = Field(default_factory=dict)
    position: tuple[float, float] = (0, 0)
    enabled: bool = True
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    failure_policy: Literal["STOP", "CONTINUE", "RETRY", "FAIL_BRANCH", "MANUAL_INTERVENTION"] = (
        "STOP"
    )
    compensation: dict[str, Any] | None = None


class Edge(Model):
    source: str
    target: str
    branch: str = "default"


class Parameter(Model):
    type: Literal["string", "integer", "number", "boolean", "array", "object"] = "string"
    required: bool = True
    default: Any = None
    description: str = ""


class Runbook(Model):
    schema_version: Literal[1] = 1
    id: str = Field(default_factory=new_id)
    name: str = Field(min_length=1, max_length=160)
    description: str = ""
    owner: str = ""
    team: str = "default"
    tags: list[str] = Field(default_factory=list)
    environments: list[str] = Field(default_factory=lambda: ["dev", "staging"])
    parameters: dict[str, Parameter] = Field(default_factory=dict)
    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    version: int = Field(default=0, ge=0)
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)


class Identity(Model):
    id: str = Field(min_length=1)
    display_name: str = ""
    roles: list[str] = Field(default_factory=lambda: ["VIEWER"])
    permissions: list[str] = Field(default_factory=list)
    teams: list[str] = Field(default_factory=lambda: ["default"])


class AWSContext(Model):
    environment: Literal["dev", "staging", "production"] = "dev"
    account_id: str = Field(default="000000000000", pattern=r"^\d{12}$")
    region: str = Field(default="sa-east-1", pattern=r"^[a-z]{2}(-[a-z]+)+-\d+$")
    mode: Literal["demo", "aws"] = "demo"
    profile: str | None = None
    role_arn: str | None = None
    external_id: str | None = None


class Execution(Model):
    id: str = Field(default_factory=new_id)
    runbook_id: str
    runbook_version: int
    snapshot: Runbook
    snapshot_hash: str
    actor: Identity
    aws_context: AWSContext
    parameters: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = True
    reason: str = ""
    status: Status = Status.PENDING
    started_at: str | None = None
    finished_at: str | None = None
    created_at: str = Field(default_factory=utcnow)
    node_outputs: dict[str, Any] = Field(default_factory=dict)
    node_branches: dict[str, str] = Field(default_factory=dict)
    error: str | None = None
