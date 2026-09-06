# Core agent instructions

Applies under `flowops/core/`.

- Keep this layer independent of Streamlit and boto3 transport details.
- Preserve deterministic DAG validation, safe expression/mapping semantics and explicit version compatibility.
- Never introduce arbitrary Python/shell evaluation for Runbook data.
- Engine-side authorization/policy/approval/simulation controls are authoritative; presentation code cannot replace them.
- Retry behavior must remain bounded and safe for the Action's idempotency semantics.
- Execution checkpoints and immutable snapshots are recovery/audit contracts; migrations need explicit compatibility handling.
- Changes to engine, graph, security or policy are high-risk and need focused negative-path tests.
