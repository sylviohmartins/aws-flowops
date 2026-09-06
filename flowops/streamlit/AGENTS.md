# Streamlit agent instructions

Applies under `flowops/streamlit/` and standalone presentation work.

- Streamlit is presentation; durable actions must route through Repository/Engine/provider contracts.
- A render/rerun must never perform an unintended mutation.
- Preserve explicit submit semantics and production typed confirmation.
- Do not weaken engine-side RBAC, policy, destructive grants or approvals because the UI already checks something.
- Keep session-state identifiers free of secrets/DSNs/raw credentials.
- Preserve distinction between FlowOps simulation and AWS-native DryRun.
- Update AppTest journeys when observable UI behavior or operational controls change.
