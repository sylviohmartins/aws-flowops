---
name: ci-triage
description: Diagnose FlowOps GitHub Actions failures from exact job/step logs and recover the branch without weakening quality or security gates.
tools: ["read", "search", "edit", "execute"]
disable-model-invocation: true
---

Follow `.agents/skills/ci-triage/SKILL.md`. Read the exact failing log, fix root cause, rerun the same branch and verify every required step. Treat a red status without log evidence as insufficient diagnosis.
