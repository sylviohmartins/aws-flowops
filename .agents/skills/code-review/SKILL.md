---
name: code-review
description: Perform evidence-first FlowOps review across correctness, AWS safety, security, concurrency, compatibility, tests, operations and maintainability.
---

# Code review

Review diff plus relevant callers/tests. Prefer high-confidence defects over broad style advice. Give concrete failure mode and evidence. For consequential findings, actively search for guards/callers/tests that could refute the concern.

Inspect authorization, confused-deputy/account scope, retries/idempotency, simulation, approvals, immutable history, migrations, compatibility and missing critical tests. Distinguish demonstrated defects from residual risk or optional improvement. Zero findings is valid.
