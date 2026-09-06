# Testing policy

Tests are executable evidence, not a coverage-number exercise.

- Add/update tests when observable behavior or a FlowOps safety invariant changes.
- Prefer deterministic unit/service tests and explicit fakes/Stubber for AWS behavior.
- Automated tests must not require a production AWS account.
- Test trust boundaries explicitly: account/region scope, authorization, approvals, simulation, retry/idempotency and secret redaction.
- Persistence behavior that claims portability needs SQLite and PostgreSQL coverage where material.
- Streamlit changes should cover relevant AppTest journeys and must not mutate merely because a page renders/reruns.
- Never weaken an assertion or lower the 96% coverage gate merely to recover CI.
- Reproduce failures with the narrowest useful command before expanding validation.
- Report checks not executed and why.
