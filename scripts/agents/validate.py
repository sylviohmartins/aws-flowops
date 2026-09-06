from __future__ import annotations

import json
import re
from pathlib import Path

from scripts.agents.completion_gate import evaluate_task_run

ROOT = Path(__file__).resolve().parents[2]

REQUIRED = [
    "AGENTS.md",
    ".agents/README.md",
    ".agents/config.json",
    ".agents/memory/README.md",
    ".agents/memory/INDEX.md",
    ".agents/runs/README.md",
    ".agents/specs/execution-model.md",
    ".agents/specs/completion-contract.md",
    ".agents/specs/compatibility.md",
    ".agents/rules/engineering-conventions.md",
    ".agents/rules/testing.md",
    ".agents/rules/security.md",
    ".agents/rules/aws-safety.md",
    ".agents/rules/persistence-and-migrations.md",
    ".agents/rules/change-promotion.md",
    ".agents/rules/context-efficiency.md",
    ".agents/rules/memory-and-context.md",
    ".agents/rules/completion-and-evidence.md",
    ".agents/rules/agent-asset-supply-chain.md",
    ".agents/schemas/agent-config.schema.json",
    ".agents/schemas/task-run.schema.json",
    ".agents/schemas/change-report.schema.json",
    ".agents/schemas/promotion-decision.schema.json",
    ".github/copilot-instructions.md",
    "flowops/core/AGENTS.md",
    "flowops/providers/aws/AGENTS.md",
    "flowops/persistence/AGENTS.md",
    "flowops/streamlit/AGENTS.md",
    "scripts/agents/completion_gate.py",
    "scripts/agents/classify_change.py",
]


def fail(message: str) -> None:
    raise RuntimeError(message)


def validate_frontmatter(text: str, *, name: str | None = None, apply_to: bool = False) -> None:
    match = re.match(r"^---\n(?P<body>[\s\S]*?)\n---\n", text)
    if not match:
        fail("missing YAML frontmatter")
    body = match.group("body")
    if name is not None:
        found = re.search(r"^name:\s*(.+)$", body, re.MULTILINE)
        if not found or found.group(1).strip() != name:
            fail(f"frontmatter name must be {name}")
        description = re.search(r"^description:\s*(.+)$", body, re.MULTILINE)
        if not description or len(description.group(1).strip()) < 30:
            fail(f"weak skill/agent description for {name}")
    if apply_to and not re.search(r"^applyTo:\s*.+$", body, re.MULTILINE):
        fail("path-specific instruction missing applyTo")


def main() -> int:
    for relative in REQUIRED:
        if not (ROOT / relative).exists():
            fail(f"missing required agent-engineering file: {relative}")

    config = json.loads((ROOT / ".agents/config.json").read_text(encoding="utf-8"))
    if config.get("version") != 1:
        fail("agent config version must be 1")
    if config.get("canonicalInstructions") != "../AGENTS.md":
        fail("agent config must route to root AGENTS.md")
    execution = config.get("execution", {})
    if execution.get("strategy") != "github-mediated-development":
        fail("execution strategy must be github-mediated-development")
    if execution.get("workingBranchRequired") is not True:
        fail("substantive work must require a working branch")
    if execution.get("pullRequestRequired") is not False:
        fail("FlowOps intentionally supports branch+CI+squash without mandatory PR")
    promotion = config.get("promotion", {})
    if promotion.get("requireExactValidatedTree") is not True:
        fail("promotion must require the exact validated tree")
    if promotion.get("allowForceUpdateMain") is not False:
        fail("normal main promotion must forbid force updates")
    safety = config.get("safety", {})
    for key in (
        "allowProductionAwsMutationForValidation",
        "allowSecretMutation",
        "allowDirectMainWritesForSubstantiveChanges",
        "allowForceUpdateMain",
    ):
        if safety.get(key) is not False:
            fail(f"safety default must remain false: {key}")

    for schema in (ROOT / ".agents/schemas").glob("*.json"):
        json.loads(schema.read_text(encoding="utf-8"))

    skills = sorted((ROOT / ".agents/skills").glob("*/SKILL.md"))
    if len(skills) < 12:
        fail("expected a curated FlowOps skill catalog")
    for skill in skills:
        text = skill.read_text(encoding="utf-8")
        try:
            validate_frontmatter(text, name=skill.parent.name)
        except RuntimeError as exc:
            fail(f"{skill.relative_to(ROOT)}: {exc}")
        if len(text) > 8000:
            fail(f"skill is too large for progressive disclosure: {skill.parent.name}")

    for instruction in sorted((ROOT / ".github/instructions").glob("*.instructions.md")):
        try:
            validate_frontmatter(instruction.read_text(encoding="utf-8"), apply_to=True)
        except RuntimeError as exc:
            fail(f"{instruction.relative_to(ROOT)}: {exc}")

    for agent in sorted((ROOT / ".github/agents").glob("*.agent.md")):
        text = agent.read_text(encoding="utf-8")
        try:
            validate_frontmatter(text, name=agent.name.removesuffix(".agent.md"))
        except RuntimeError as exc:
            fail(f"{agent.relative_to(ROOT)}: {exc}")
        frontmatter = text.split("---", 2)[1]
        if "tools:" not in frontmatter:
            fail(f"custom agent must declare least-privilege tools: {agent.name}")

    for prompt in sorted((ROOT / ".github/prompts").glob("*.prompt.md")):
        text = prompt.read_text(encoding="utf-8")
        if "AGENTS.md" not in text:
            fail(f"prompt must route to canonical AGENTS.md: {prompt.name}")

    copilot = (ROOT / ".github/copilot-instructions.md").read_text(encoding="utf-8")
    if "AGENTS.md" not in copilot:
        fail("Copilot adapter must route to AGENTS.md")

    for run_file in sorted((ROOT / ".agents/runs").glob("*.json")):
        run = json.loads(run_file.read_text(encoding="utf-8"))
        final = run.get("completionGate", {}).get("status") not in {None, "OPEN"}
        status, errors = evaluate_task_run(run, final=final)
        if errors or status == "FAIL":
            fail(f"invalid task run {run_file.name}: {' | '.join(errors)}")

    quality = (ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    if "python scripts/agents/validate.py" not in quality:
        fail("Quality workflow must execute agent-engineering validation")
    if "--cov-fail-under=96" not in quality:
        fail("Quality workflow coverage floor must remain 96")

    forbidden_config_terms = ("cloudflare", "d1", "wrangler", "npm run", "nexo")
    config_text = json.dumps(config).lower()
    for term in forbidden_config_terms:
        if term in config_text:
            fail(f"source-project-specific term leaked into FlowOps agent config: {term}")

    print(f"agent engineering validation: ok ({len(skills)} canonical skills)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
