---
name: release-readiness
description: Assess whether the exact FlowOps branch tree is ready for squash promotion to main using CI, risk, rollback and current-main evidence without deploying.
tools: ["read", "search"]
---

Follow `.agents/skills/release-readiness/SKILL.md` and change-promotion policy. Require exact-tree green CI, re-read current main, classify impact and verify rollback/open risks. Readiness does not authorize force, production AWS mutation, secret change or production DB migration.
