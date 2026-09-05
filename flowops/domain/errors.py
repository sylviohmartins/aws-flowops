"""Safe domain failures; provider exceptions are translated at the boundary."""


class FlowOpsError(Exception):
    """An actionable error safe to display without a traceback."""


class WorkflowValidationError(FlowOpsError):
    """The workflow or its inputs violate a contract."""


class ConflictError(FlowOpsError):
    """Concurrent modification or incompatible replay."""


class AuthorizationError(FlowOpsError):
    """The trusted identity is not authorized."""


class PolicyViolation(FlowOpsError):
    """Operational safety policy denied the request."""


class ProviderError(FlowOpsError):
    """A sanitized provider error with explicit retry classification."""

    def __init__(self, code: str, *, retryable: bool = False, ambiguous: bool = False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.ambiguous = ambiguous
