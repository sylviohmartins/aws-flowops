# Agent compatibility

`AGENTS.md` and `.agents/` are the vendor-neutral source of truth. GitHub/Copilot adapters under `.github/` are intentionally thin and must route to canonical rules/skills rather than duplicate them.

Do not add Claude/Gemini/other-vendor adapters until that execution surface is actually used by the project. New adapters must preserve instruction hierarchy, human gates and FlowOps safety invariants.

External orchestrators may schedule work, but they never become a second source of requirements, secrets or promotion authority.
