# Change promotion

Development autonomy is separate from promotion authority.

Agents may create a technical branch, edit it, inspect exact CI failures, correct them and repeat until acceptance criteria and required checks are satisfied. Promotion to `main` is a separate decision.

## Risk tiers

- **Low** — documentation/metadata with no runtime, policy or delivery effect.
- **Moderate** — ordinary tests/UI/application behavior outside trust boundaries.
- **High** — `flowops/core`, AWS provider, persistence, production UI controls, dependencies, GitHub Actions, `.agents/` policy or security-sensitive code.
- **Consequential** — real secret changes, production AWS mutation/deployment mechanics, production DB migration or deliberate safety-guard bypass.

Semantic review may raise risk; do not silently lower deterministic classification.

## FlowOps promotion model

For substantive changes:

1. work on a non-`main` branch;
2. validate the exact branch tree with required CI;
3. re-read `main` immediately before promotion;
4. ensure the branch is not behind/conflicted;
5. create a squash stage commit using the exact validated tree and current `main` as parent;
6. update `main` without force;
7. validate the CI run triggered specifically by the new `main` SHA.

A green branch CI is evidence, not permission to use force or bypass a changed `main`.
