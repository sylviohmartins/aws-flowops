# AWS provider agent instructions

Applies under `flowops/providers/aws/`.

Read `.agents/rules/aws-safety.md` and use the `aws-action-development` skill.

- Keep boto3 behind this provider boundary.
- Validate expected account and relevant resource/region scope before operations.
- Use botocore models instead of hand-maintained SDK schemas where possible.
- Every Action must have conservative risk/read-only/idempotency/IAM metadata.
- Generic operations stay host-allowlisted and sensitive services fail closed.
- Bound pagination, streams and payloads.
- Do not conflate FlowOps simulation with AWS-native DryRun.
- Use fakes/Stubber/model tests; never require production AWS credentials for automated tests.
