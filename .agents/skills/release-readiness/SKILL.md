---
name: release-readiness
description: Assess whether a FlowOps branch/tree is ready for promotion using exact CI, security, packaging, migration, AWS-impact and rollback evidence without deploying.
---

# Release readiness

Require the exact candidate tree to have green required CI, documented AWS/persistence/security/deployment impact, rollback path and no blocking findings. Re-read current `main`, verify ancestry/tree assumptions and follow `.agents/rules/change-promotion.md`.

Readiness does not authorize real AWS mutations, secret changes, production DB migrations or force-updating `main`.
