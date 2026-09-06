# AGENTS.md

## Mission

Maintain AWS FlowOps Studio as a conservative, auditable automation system for AWS operations. Preserve execution safety, authorization boundaries, immutable history and deterministic recovery before optimizing convenience or feature breadth.

This is the canonical repository instruction file for AI agents.

## Instruction hierarchy

For repository work, use this order:

1. explicit user request;
2. nearest applicable nested `AGENTS.md`;
3. this root `AGENTS.md`;
4. applicable rule under `.agents/rules/`;
5. task-specific skill under `.agents/skills/`;
6. existing implementation and tests;
7. installed-version framework/AWS SDK documentation.

Vendor-specific files under `.github/` are adapters. They must route to this contract rather than become competing sources of truth.

## Progressive context

Start with `README.md`, `docs/ARCHITECTURE.md`, `docs/SECURITY.md`, `docs/OPERATIONS.md` and the nearest nested `AGENTS.md`. Then load only the rules and skills needed for the task. Follow `.agents/rules/context-efficiency.md`.

## Execution model

Use `.agents/specs/execution-model.md` for implementation work. The normal reversible loop is:

`DISCOVER -> PLAN -> BRANCH -> CHANGE -> VALIDATE -> DIAGNOSE -> REVISE -> REVIEW -> PROMOTION_DECISION`

Use a non-`main` branch for substantive work. CI failure is feedback: inspect the exact failing step, fix the root cause and rerun. Never weaken a gate merely to obtain green CI.

FlowOps does not require a pull request for every change. A PR is useful when collaboration/review needs it; otherwise the validated technical branch may be squash-promoted to `main` under `.agents/rules/change-promotion.md`.

For long-running, multi-requirement, multi-agent or compaction-prone work, use `.agents/specs/completion-contract.md` and a temporary run under `.agents/runs/`. Repository/CI reality wins over conversational summaries.

## Skill routing

- unfamiliar scope / impact mapping: `.agents/skills/repository-discovery/SKILL.md`;
- ambiguous objective / acceptance criteria: `.agents/skills/planning/SKILL.md`;
- requirement/evidence/checkpoint traceability: `.agents/skills/task-completion/SKILL.md`;
- implementation: `.agents/skills/implementation/SKILL.md`;
- dependency-aware concurrent work: `.agents/skills/parallel-work/SKILL.md`;
- tests: `.agents/skills/testing/SKILL.md`;
- failing CI: `.agents/skills/ci-triage/SKILL.md`;
- runtime/integration debugging: `.agents/skills/debugging/SKILL.md`;
- evidence-first review: `.agents/skills/code-review/SKILL.md`;
- security review: `.agents/skills/security-review/SKILL.md`;
- AWS Action/provider changes: `.agents/skills/aws-action-development/SKILL.md`;
- persistence/schema migrations: `.agents/skills/persistence-migrations/SKILL.md`;
- release/readiness assessment: `.agents/skills/release-readiness/SKILL.md`;
- conservative cleanup: `.agents/skills/project-sanitation/SKILL.md`;
- documentation/ADRs/agent guidance: `.agents/skills/documentation/SKILL.md`;
- third-party agent tooling: `.agents/skills/agent-asset-vetting/SKILL.md`.

## Commands

Use repository-native commands:

```bash
python -m pip install -e '.[dev,postgres]'
python scripts/agents/validate.py
ruff format --check .
ruff check .
mypy flowops
pytest --cov=flowops --cov-report=term-missing --cov-fail-under=96
bandit -r flowops -ll
pip-audit
python -m build
```

For a tracked task run:

```bash
python scripts/agents/completion_gate.py .agents/runs/<task-id>.json --final
```

Never claim a check passed when it was not executed.

## FlowOps invariants

Never break these rules:

- Streamlit is presentation; durable execution side effects go through the engine;
- `flowops/core` stays independent of Streamlit and boto3 transport details;
- boto3/AWS SDK calls stay behind the AWS provider;
- published Runbook versions and execution snapshots are immutable historical records;
- FlowOps simulation must not perform real mutations and is distinct from AWS-native `DryRun`;
- production execution remains fail-closed and requires the configured authorization, reason, confirmation and approval controls;
- unknown/unclassified AWS operations are never silently treated as safe;
- Generic AWS Actions require explicit host allowlisting and sensitive services remain blocked;
- retries require idempotency or an equivalent safety guarantee;
- secrets and raw AWS credentials must not be persisted or logged;
- account/region/resource scope checks must not be bypassed;
- failure branches and compensations do not imply transactional rollback;
- SQLite and PostgreSQL semantics must remain intentionally compatible where the Repository contract promises portability;
- old `schema_version`/`node_version` definitions are never silently reinterpreted incompatibly.

## Human gates

Agents do not have implicit authorization to:

- deploy or mutate a real production AWS account merely to validate code;
- create/change real AWS credentials or secrets;
- bypass production confirmations, RBAC, approvals or destructive grants;
- run destructive bulk operations against external accounts;
- apply a production database migration solely as validation;
- force-update `main` for normal promotion.

## Completion evidence

Final reports for substantive work must cover: behavior, files changed, tests/checks executed, checks not executed, requirement coverage when tracked, AWS impact, persistence/migration impact, security impact, deployment impact, rollback path and open risks. Green CI is strong evidence for the checks it actually executes, not proof of untested external AWS behavior.
