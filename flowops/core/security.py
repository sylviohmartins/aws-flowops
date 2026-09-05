"""Central redaction and bounded output persistence, independent of individual actions."""

import json
import re
from typing import Any, Protocol

from flowops.domain.errors import PolicyViolation

SENSITIVE = re.compile(
    r"(?i)(secret|password|passwd|credential|authorization|access.?key|session.?token|private.?key|client.?token|receipt.?handle|security.?token)"
)
AWS_KEY = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")
BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9_.~+/=-]+")
REDACTED = "[REDACTED]"


def redact(value: Any, depth: int = 0) -> Any:
    if depth > 32:
        return {"_truncated": True, "reason": "depth"}
    if isinstance(value, dict):
        return {
            str(k): REDACTED if SENSITIVE.search(str(k)) else redact(v, depth + 1)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(v, depth + 1) for v in value]
    if isinstance(value, str):
        result = BEARER.sub("Bearer [REDACTED]", AWS_KEY.sub(REDACTED, value))
        if result.lstrip().startswith(("{", "[")):
            try:
                parsed = json.loads(result)
                return json.dumps(redact(parsed, depth + 1), ensure_ascii=False)
            except (ValueError, RecursionError):
                pass
        return result
    if value is None or type(value) in (bool, int, float):
        return value
    return f"[{type(value).__name__} omitted]"


def reject_secrets(value: Any) -> None:
    """Definitions/parameters must not contain credentials or literal secret values."""
    value = json.loads(json.dumps(value))
    if redact(value) != value:
        raise PolicyViolation("Sensitive literals are not accepted in runbooks or parameters.")


class PayloadStore(Protocol):
    """Host extension for bounded, encrypted external payload storage."""

    def put(self, key: str, payload: bytes) -> str: ...


def bounded_output(
    value: Any, limit: int = 131072, store: PayloadStore | None = None, key: str = ""
) -> Any:
    sanitized = redact(value)
    encoded = json.dumps(sanitized, ensure_ascii=False, allow_nan=False).encode()
    if len(encoded) <= limit:
        return sanitized
    metadata: dict[str, Any] = {"_truncated": True, "bytes": len(encoded), "limit": limit}
    if store is not None:
        metadata["external_reference"] = store.put(key, encoded)
    return metadata
