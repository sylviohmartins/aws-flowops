from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

FINAL_REQUIREMENT = {"DONE", "REJECTED_WITH_REASON", "BLOCKED", "NOT_APPLICABLE"}
FINAL_TASK = {"DONE", "BLOCKED", "NOT_APPLICABLE"}


def evaluate_task_run(run: dict[str, Any], *, final: bool = False) -> tuple[str, list[str]]:
    errors: list[str] = []
    requirements = run.get("requirements")
    tasks = run.get("tasks")
    checks = run.get("checks")
    failures = run.get("failures")
    checkpoint = run.get("checkpoint")

    if not isinstance(run.get("id"), str) or not run["id"].strip():
        errors.append("run.id must be a non-empty string")
    if not isinstance(run.get("phase"), str) or not run["phase"].strip():
        errors.append("run.phase must be a non-empty string")
    if not isinstance(requirements, list):
        errors.append("requirements must be a list")
        requirements = []
    if not isinstance(tasks, list):
        errors.append("tasks must be a list")
        tasks = []
    if not isinstance(checks, list):
        errors.append("checks must be a list")
        checks = []
    if not isinstance(failures, list):
        errors.append("failures must be a list")
        failures = []
    if not isinstance(checkpoint, dict) or not str(checkpoint.get("nextAction", "")).strip():
        errors.append("checkpoint.nextAction must be present")

    requirement_ids: set[str] = set()
    blocked = False
    for requirement in requirements:
        if not isinstance(requirement, dict):
            errors.append("every requirement must be an object")
            continue
        req_id = str(requirement.get("id", ""))
        status = str(requirement.get("status", ""))
        if not req_id.startswith("REQ-") or req_id in requirement_ids:
            errors.append(f"invalid or duplicate requirement id: {req_id!r}")
        requirement_ids.add(req_id)
        if final and status not in FINAL_REQUIREMENT:
            errors.append(f"requirement {req_id} is not terminal: {status}")
        if status == "DONE" and not requirement.get("evidence"):
            errors.append(f"DONE requirement {req_id} needs evidence")
        if status in {"REJECTED_WITH_REASON", "BLOCKED", "NOT_APPLICABLE"} and not str(
            requirement.get("reason", "")
        ).strip():
            errors.append(f"requirement {req_id} status {status} needs a reason")
        blocked = blocked or status == "BLOCKED"

    task_ids: set[str] = set()
    ownership: dict[tuple[int, str], str] = {}
    for task in tasks:
        if not isinstance(task, dict):
            errors.append("every task must be an object")
            continue
        task_id = str(task.get("id", ""))
        status = str(task.get("status", ""))
        wave = task.get("wave", 0)
        if not task_id or task_id in task_ids:
            errors.append(f"invalid or duplicate task id: {task_id!r}")
        task_ids.add(task_id)
        if final and status not in FINAL_TASK:
            errors.append(f"task {task_id} is not terminal: {status}")
        blocked = blocked or status == "BLOCKED"
        for req_id in task.get("requirementIds", []):
            if req_id not in requirement_ids:
                errors.append(f"task {task_id} references unknown requirement {req_id}")
        for file_path in task.get("files", []):
            key = (int(wave), str(file_path))
            owner = ownership.get(key)
            if owner and owner != task_id:
                errors.append(
                    f"same-wave file ownership conflict for {file_path}: {owner} and {task_id}"
                )
            ownership[key] = task_id

    for check in checks:
        if not isinstance(check, dict):
            errors.append("every check must be an object")
            continue
        required = check.get("required", True) is not False
        status = str(check.get("status", ""))
        if final and required and status != "PASSED":
            errors.append(f"required check {check.get('name', '<unnamed>')} is {status or 'unset'}")

    for failure in failures:
        if isinstance(failure, dict) and failure.get("status", "OPEN") == "OPEN":
            errors.append(f"open failure remains: {failure.get('summary', '<unnamed>')}")

    if errors:
        return "FAIL", errors
    if blocked:
        return "BLOCKED", []
    return ("PASS" if final else "OPEN"), []


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a FlowOps agent task-run checkpoint")
    parser.add_argument("run", type=Path)
    parser.add_argument("--final", action="store_true")
    args = parser.parse_args()
    run = json.loads(args.run.read_text(encoding="utf-8"))
    status, errors = evaluate_task_run(run, final=args.final)
    print(json.dumps({"status": status, "errors": errors}, indent=2))
    return 0 if status in {"PASS", "OPEN", "BLOCKED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
