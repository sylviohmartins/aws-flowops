---
name: debugging
description: Diagnose FlowOps runtime, execution, persistence, AWS-provider or Streamlit failures from evidence before changing behavior.
---

# Debugging

Reproduce or obtain exact evidence first. Trace the narrow path from symptom through caller, engine/policy, provider/persistence boundary and relevant checkpoint/audit state. Form explicit hypotheses and falsify them with logs/tests/code before editing.

For AWS issues, distinguish SDK/model errors, account/region/resource mismatch, permissions, transient service errors and FlowOps policy rejection. For persistence issues, distinguish SQLite/PostgreSQL differences and migration state. Preserve a regression test for confirmed defects when practical.
