# Context efficiency

Optimize context only after preserving correctness and evidence.

- Prefer progressive disclosure: indexes, diffs, focused files and exact failing logs before broad raw trees/logs.
- Persist long-task state in `.agents/runs/` rather than repeatedly reconstructing it from conversation.
- Keep exact error text, failing assertions, security findings, FlowOps invariants and evidence references lossless.
- Summarize repetitive successful output; never hide a failure to save context.
- Use repository-native search and focused diffs before adding a persistent external knowledge system.
- Version-sensitive library/AWS SDK claims should use installed-version-aware evidence or authoritative documentation.
