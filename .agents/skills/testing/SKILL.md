---
name: testing
description: Design deterministic tests for FlowOps core, persistence, AWS provider behavior, governance and Streamlit journeys without depending on production services.
---

# Testing

Follow `.agents/rules/testing.md`. Prioritize behavior and safety invariants over private implementation details. Use fakes/Stubber for AWS, real PostgreSQL only in controlled test infrastructure, and AppTest for relevant Streamlit behavior.

Use stronger techniques only when they express a real invariant. Preserve a regression case for bug fixes when practical. Never add a library merely to satisfy a methodology label.
