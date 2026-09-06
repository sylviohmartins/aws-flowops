# Agent engineering

`.agents/` is the vendor-neutral source for reusable AI-agent knowledge in AWS FlowOps Studio. It complements the canonical root `AGENTS.md`.

## Layers

- `AGENTS.md` — small always-on repository contract and routing table;
- `rules/` — durable engineering policies;
- `skills/` — on-demand reusable `SKILL.md` procedures;
- `schemas/` — machine-readable task/evidence shapes;
- `specs/` — FlowOps-specific execution/completion contracts;
- `memory/` — durable project knowledge with provenance/staleness discipline;
- `runs/` — temporary transactional state for long-running work.

GitHub-specific adapters live under `.github/agents/`, `.github/prompts/`, `.github/instructions/` and `.github/copilot-instructions.md`.

Do not duplicate long policy across adapters. Keep one canonical rule and route adapters to it.

## Context discipline

Use progressive disclosure:

1. load root/nearest `AGENTS.md`;
2. load only rules relevant to the affected surface;
3. activate only task-relevant skills;
4. read large implementation/reference files only when required.

For compaction-prone work, the active run under `.agents/runs/` is the execution checkpoint; repository and CI reality remain authoritative.
