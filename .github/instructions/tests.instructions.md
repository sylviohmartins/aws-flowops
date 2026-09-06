---
applyTo: "tests/**/*.py"
---

Follow `.agents/rules/testing.md`. Prefer observable FlowOps behavior and safety invariants over private implementation details. Keep automated tests deterministic and isolated from production AWS. Never weaken an assertion or lower the coverage gate solely to recover CI.
