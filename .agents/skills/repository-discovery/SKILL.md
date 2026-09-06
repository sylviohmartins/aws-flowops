---
name: repository-discovery
description: Map an unfamiliar FlowOps area before planning or changing code, including execution, AWS, persistence, Streamlit and test boundaries.
---

# Repository discovery

1. Read root and nearest nested `AGENTS.md`.
2. Read only relevant `.agents/rules/`.
3. Trace entry point -> core/engine -> provider/persistence -> Streamlit/API surface -> tests.
4. Identify AWS account/region/resource, authorization, persistence, compatibility and deployment boundaries.
5. Inspect existing tests and Quality workflow before proposing validation.
6. Produce bounded scope and explicit unknowns rather than guessing.
