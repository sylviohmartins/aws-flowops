# Engineering conventions

Use existing FlowOps patterns before introducing new abstractions.

- Keep `flowops/core` independent of Streamlit and boto3 transport details.
- Keep AWS SDK behavior behind `flowops/providers/aws`.
- Keep presentation-specific state and widgets under `flowops/streamlit`.
- Prefer small modules, explicit boundaries and typed contracts.
- Preserve published definition/snapshot compatibility; migrate explicitly instead of reinterpreting history.
- Keep side effects explicit; never rely on Streamlit reruns or accidental background behavior for correctness.
- Keep retries bounded and tied to idempotency/safety semantics.
- Centralize redaction/bounded-output handling for persisted/logged external data.
- Comments explain rationale, safety constraints and non-obvious invariants rather than narrating syntax.
- Make the smallest complete change and avoid unrelated refactors.
- New dependencies require concrete value plus maintenance/security review.
