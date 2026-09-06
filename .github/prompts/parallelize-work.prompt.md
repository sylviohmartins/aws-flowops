# Parallelize FlowOps work safely

Read `../../AGENTS.md` and `.agents/skills/parallel-work/SKILL.md`. Build a task dependency graph and write-file ownership map. Create parallel waves only for dependency-independent, file-disjoint work and only claim actual parallelism when isolated workers/worktrees exist. Revalidate the integrated tree.
