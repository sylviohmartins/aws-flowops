"""Authentication boundary for standalone development and corporate embedding."""

from __future__ import annotations

from typing import Protocol

from flowops.domain.models import Identity


class IdentityProvider(Protocol):
    """Resolve the already-authenticated user; authentication itself stays host-owned."""

    def current(self) -> Identity: ...


class StaticIdentityProvider:
    """Deterministic provider for standalone/demo mode and automated tests."""

    def __init__(self, identity: Identity):
        self.identity = identity.model_copy(deep=True)

    def current(self) -> Identity:
        return self.identity.model_copy(deep=True)
