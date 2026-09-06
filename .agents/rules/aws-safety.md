# AWS execution safety

Changes under `flowops/providers/aws`, Action metadata, execution policy or production UI controls are high-risk surfaces.

- Validate the expected AWS account before operational calls.
- Preserve region/resource scope checks and bounded pagination/payload behavior.
- Classify each Action for read-only/mutating behavior, risk, idempotency and required IAM permissions.
- Prefer curated Actions when semantics require explicit safety treatment.
- Unknown generic operations remain conservative and require host allowlisting.
- Do not imply an AWS-native `DryRun` exists when it does not; FlowOps simulation is a separate orchestrator control.
- Non-idempotent mutations do not receive automatic retries without an explicit idempotency guarantee.
- Compensating Actions use normal authorization/policy/approval/simulation/retry paths and are not transactional rollback.
- Test AWS behavior using models, fakes or botocore Stubber; live validation belongs in an isolated sandbox/staging account with least privilege.
