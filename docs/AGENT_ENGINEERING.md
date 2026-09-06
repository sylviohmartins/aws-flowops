# AI/agent engineering in AWS FlowOps Studio

## Why this exists

FlowOps is an operational safety product: an AI agent changing execution, AWS, persistence or production controls needs the same durable guardrails as a human contributor. Repository-local instructions make those constraints reviewable, versioned and tool-neutral instead of depending on one chat session.

The architecture was adapted from useful patterns observed in `sylviohmartins/nexo-financeiro-api`, but intentionally excludes that project's financial semantics, Cloudflare/D1 deployment model, vendor-specific hooks and third-party agent-asset catalog.

## What was adopted

### Canonical persistent instructions

`AGENTS.md` is the always-on contract and routing table. High-risk FlowOps boundaries also have nested instructions:

- `flowops/core/AGENTS.md`;
- `flowops/providers/aws/AGENTS.md`;
- `flowops/persistence/AGENTS.md`;
- `flowops/streamlit/AGENTS.md`.

### Progressive rules and skills

`.agents/rules/` holds durable policy; `.agents/skills/*/SKILL.md` holds short on-demand procedures. This prevents every agent from loading a giant prompt while keeping security/testing/promotion/AWS rules deterministic.

The skill catalog is deliberately FlowOps-focused: discovery, planning, task completion, implementation, parallel work, testing, CI triage, debugging, review, security review, AWS Action development, persistence migrations, readiness, sanitation, documentation and third-party agent-asset vetting.

### Task/evidence continuity

For long tasks, `.agents/runs/` may hold temporary requirement/task/checkpoint/evidence state. `scripts/agents/completion_gate.py` prevents a tracked task from being declared complete while requirements/checks/failures/evidence are incomplete. Durable knowledge belongs in normal docs/ADRs or, only when necessary, `.agents/memory/`.

### GitHub adapters

`.github/copilot-instructions.md`, `.github/instructions/`, `.github/agents/` and `.github/prompts/` expose the canonical contract to GitHub tooling without duplicating full policy. They are adapters, not alternate sources of truth.

### Deterministic validation

`python scripts/agents/validate.py` checks the repository's agent-engineering structure, config safety defaults, skill/agent frontmatter, prompt routing, task runs and CI integration. Quality CI executes it before the normal Python gates.

`python scripts/agents/classify_change.py` provides conservative path-based risk classification for planning/promotion. Semantic review may raise risk; path classification must not be used to silently lower it.

## What was intentionally not adopted

- Cloudflare/D1-specific rules, commands and release workflows;
- mandatory pull requests: FlowOps already uses an exact-tree branch CI + squash promotion model;
- vendor-specific Claude/Gemini adapters when those surfaces are not part of the repository workflow;
- executable third-party agent plugins/hooks merely for feature parity;
- a catalog of external agent tools without demonstrated FlowOps value;
- production deployment as a CI/acceptance mechanism.

## Agent workflow

For substantive work:

1. discover repository scope and nearest instructions;
2. define acceptance criteria/invariants/risk;
3. work on a technical branch;
4. implement the smallest complete change;
5. run focused checks and Quality CI;
6. diagnose exact failures and iterate without weakening gates;
7. review with risk-appropriate lenses;
8. promote only the exact validated tree onto current `main` without force;
9. require the CI run of the resulting `main` SHA to pass before declaring completion.

## Validation commands

```bash
python scripts/agents/validate.py
python scripts/agents/classify_change.py /tmp/changed-files.txt
python scripts/agents/completion_gate.py .agents/runs/<task-id>.json --final
```

The normal Quality commands remain documented in `README.md`, `CONTRIBUTING.md` and `docs/TESTING.md`.
