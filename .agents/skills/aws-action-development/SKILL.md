---
name: aws-action-development
description: Add or change FlowOps AWS Actions while preserving botocore contracts, IAM metadata, account/resource scope, simulation, risk and retry safety.
---

# AWS Action development

Read `flowops/providers/aws/AGENTS.md` and `.agents/rules/aws-safety.md`.

- Prefer botocore models for request/response schemas.
- Classify read-only/mutating behavior, risk, idempotency and required permissions explicitly.
- Validate account/region/resource assumptions.
- Define FlowOps simulation behavior and native DryRun distinction.
- Bound list/stream/payload behavior.
- Add provider/contract tests with fakes or Stubber.
- Do not enable generic sensitive-service access as a convenience workaround.
