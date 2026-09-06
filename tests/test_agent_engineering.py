from __future__ import annotations

from scripts.agents.classify_change import classify
from scripts.agents.completion_gate import evaluate_task_run
from scripts.agents.validate import main as validate_agents


def valid_run() -> dict[str, object]:
    return {
        "id": "agent-contract-test",
        "phase": "VALIDATING",
        "requirements": [
            {"id": "REQ-001", "status": "DONE", "evidence": ["test:agent-contract"]}
        ],
        "tasks": [
            {
                "id": "TASK-001",
                "status": "DONE",
                "requirementIds": ["REQ-001"],
                "wave": 1,
                "files": ["AGENTS.md"],
            }
        ],
        "checks": [{"name": "quality", "required": True, "status": "PASSED"}],
        "failures": [],
        "checkpoint": {"nextAction": "promote validated tree"},
    }


def test_agent_repository_contract_is_self_consistent() -> None:
    assert validate_agents() == 0


def test_completion_gate_accepts_evidenced_terminal_run() -> None:
    status, errors = evaluate_task_run(valid_run(), final=True)
    assert status == "PASS"
    assert errors == []


def test_completion_gate_rejects_done_requirement_without_evidence() -> None:
    run = valid_run()
    requirements = run["requirements"]
    assert isinstance(requirements, list)
    requirements[0].pop("evidence")
    status, errors = evaluate_task_run(run, final=True)
    assert status == "FAIL"
    assert any("needs evidence" in error for error in errors)


def test_change_classifier_elevates_aws_and_policy_surfaces() -> None:
    result = classify(["flowops/providers/aws/actions.py", ".agents/config.json"])
    assert result["riskTier"] == "high"
    assert result["requiresHumanReview"] is True


def test_change_classifier_flags_secret_like_files() -> None:
    result = classify([".env.production"])
    assert result["riskTier"] == "consequential"
    assert result["blockingFactors"]
