# GitHub-mediated development execution model

## Objective

Use an AI reasoning surface with GitHub repository operations and GitHub Actions as a deterministic implementation/validation loop while preserving FlowOps safety boundaries.

## State machine

`DISCOVER -> PLAN -> BRANCH -> CHANGE -> VALIDATE -> DIAGNOSE -> REVISE -> REVIEW -> PROMOTION_DECISION`

Validation failures return to `DIAGNOSE`; scope changes return to `PLAN`.

## Sequence

1. **Discover** — read canonical/nearest agent instructions, relevant implementation, tests and config.
2. **Plan** — define observable behavior, acceptance criteria, invariants, AWS/persistence/security/deployment risk and validation.
3. **Branch** — use a non-`main` branch for substantive work.
4. **Change** — make the smallest complete change; update tests/docs/contracts when behavior changes.
5. **Validate** — run focused checks, then the repository Quality workflow.
6. **Diagnose** — inspect exact failing job/step/log; do not infer cause from red status alone.
7. **Revise** — fix root cause without weakening gates.
8. **Review** — apply risk-appropriate correctness/security/operability lenses.
9. **Promotion decision** — follow `.agents/rules/change-promotion.md` and validate the promoted `main` SHA.

A pull request is optional in this repository: use one when collaboration/review requires it. Branch isolation and exact-tree CI evidence are mandatory for substantive autonomous changes.

Parallel work is allowed only for dependency-independent, file-disjoint tasks with a single integration authority and post-integration validation.

Never use a real production AWS mutation as a validation mechanism.
