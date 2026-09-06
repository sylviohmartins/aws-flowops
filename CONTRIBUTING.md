# Contributing

AWS FlowOps Studio is an operational safety tool. Changes are reviewed first for correctness, security and failure behavior, then for breadth or convenience.

AI-assisted work follows the canonical `AGENTS.md` contract; see `docs/AGENT_ENGINEERING.md` for the repository's agent-engineering architecture.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -e '.[dev,postgres]'
```

## Required quality gates

Before requesting promotion or review:

```bash
python scripts/agents/validate.py
ruff format --check .
ruff check .
mypy flowops
pytest --cov=flowops --cov-report=term-missing --cov-fail-under=96
bandit -r flowops -ll
pip-audit
python -m build
```

GitHub Actions additionally validates PostgreSQL 16.

## Engineering rules

- keep domain/core independent of Streamlit;
- keep boto3 behind the AWS provider;
- never use `eval`, arbitrary Python execution or shell execution for Runbook expressions;
- never persist AWS secret/access/session credentials;
- do not execute mutations during Streamlit render/rerun;
- preserve immutable published Runbook versions and execution snapshots;
- classify new Actions for risk, read-only behavior, idempotency and IAM;
- bound reads, payloads, retries and bulk operations;
- use central redaction/bounded-output helpers for data that can reach persistence/logs;
- fail closed when an operation cannot be classified safely.

## Adding or changing AWS Actions

Prefer curated metadata for operations that need explicit risk or IAM treatment. Use botocore models for schemas rather than recreating SDK contracts manually. Generic operations require an explicit host allowlist and must not bypass sensitive-service blocks.

Every mutation needs a credible preview/simulation story or an explicit statement that no native dry-run exists. Non-idempotent operations must not receive automatic retries without an idempotency guarantee.

## Workflow/node compatibility

Published definitions are historical records. Do not reinterpret an existing `node_version` incompatibly. Introduce a new version and an explicit migration path for imported drafts while retaining compatibility for old execution snapshots.

## Persistence

Schema changes require a new numbered migration in `flowops/persistence/migrations/` and tests for both SQLite and PostgreSQL behavior. Avoid backend-specific SQL unless the persistence adapter intentionally translates it.

## Tests

Cover happy paths plus material failure/edge cases. Prefer explicit fakes and botocore `Stubber`; automated tests must never depend on a production AWS account. Streamlit changes should preserve startup/navigation smoke coverage.

## Security review checklist

For changes affecting execution/provider/UI boundaries, consider:

- authorization bypass;
- confused deputy/account mismatch;
- secret leakage;
- expression/command injection;
- SSRF/endpoint abuse;
- replay/duplicate submission;
- destructive bulk impact;
- browser rerun causing mutation;
- approval bypass/self-approval;
- ambiguous provider failures and unsafe retries.

## Commits and promotion

Keep technical-branch commits focused enough to diagnose CI failures. A completed vertical stage may be squash-promoted to `main` only after the exact branch tree passes all required gates. Re-read `main` immediately before promotion, use the exact validated tree, and validate the resulting `main` SHA. Do not force-update `main` for normal stage promotion.
