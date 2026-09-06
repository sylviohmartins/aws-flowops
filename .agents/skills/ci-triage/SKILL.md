---
name: ci-triage
description: Diagnose and recover a failing FlowOps GitHub Actions run using exact job, step and log evidence without weakening quality or security gates.
---

# CI triage

1. Identify workflow, job and exact failing step.
2. Read the relevant log before editing.
3. Separate transient environment failures from deterministic repository failures.
4. Reproduce with the narrowest matching command when useful.
5. Fix root cause; never disable/lower the gate as a shortcut.
6. Rerun the same branch and verify every required step.
7. Record original failure, fix, rerun evidence and residual risk.
