# Memory and context

Repository memory preserves durable, reviewable FlowOps knowledge across sessions without turning chat transcripts into source code.

Use `.agents/memory/` only for facts that should remain useful after the current task ends. Use `.agents/runs/` for transactional requirement/task/evidence/checkpoint state.

Good memory candidates: a non-obvious operational invariant, validated compatibility caveat, recurring debugging fact or stable tool limitation not already better represented by code, tests, docs or an ADR.

Every durable memory topic must identify status, last validation date and evidence/source paths. Mark stale/superseded facts explicitly.

Never store secrets, credentials, production identifiers, raw conversations, speculative conclusions, transient CI output or copied third-party prompts without provenance.

After handoff/compaction, reconcile memory/run state with current repository and CI reality before consequential work.
