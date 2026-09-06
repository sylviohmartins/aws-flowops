# Security policy

- Never commit or print AWS access keys, secret keys, session tokens, passwords or production DSNs.
- Never persist raw AWS credentials in Runbooks, execution parameters, audit events or repository memory.
- Preserve central redaction and bounded-output controls for logs/persistence/UI.
- Treat account, region, role, ARN, URL and resource ownership checks as trust boundaries.
- Generic AWS Actions require explicit allowlisting; sensitive services stay fail-closed.
- Production confirmation, RBAC, destructive permission and approval controls must not be bypassed in UI or engine paths.
- Treat dependencies, GitHub workflows and agent assets as software supply-chain inputs.
- Prefer least privilege for GitHub Actions and AWS IAM.
- Real production AWS mutations, secret changes and production DB migrations require explicit human authorization.
