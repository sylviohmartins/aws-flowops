"""Read-only Lambda change review; deployment remains a governed runbook Action."""

import base64
import copy
import hashlib
import json
from difflib import unified_diff
from typing import Any

from flowops.core.actions import ActionContext, ActionRegistry
from flowops.core.policies import require
from flowops.core.security import bounded_output
from flowops.domain.errors import WorkflowValidationError
from flowops.domain.models import AWSContext, Identity, new_id

REVIEW_ACTIONS = {
    "lambda.update_function_configuration",
    "lambda.update_function_code",
    "lambda.publish_version",
    "lambda.create_alias",
    "lambda.update_alias",
    "lambda.delete_alias",
}


def _display(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                {name: "[REDACTED]" for name in item}
                if key == "Variables" and isinstance(item, dict)
                else _display(item)
            )
            for key, item in value.items()
            if key not in {"Location", "ResponseMetadata"}
        }
    if isinstance(value, list):
        return [_display(item) for item in value]
    return value


def change_preview(
    current: dict[str, Any], action_id: str, config: dict[str, Any]
) -> dict[str, Any]:
    if action_id not in REVIEW_ACTIONS:
        raise WorkflowValidationError("This operation has no Lambda change review.")
    state = copy.deepcopy(current)
    proposed = copy.deepcopy(current)
    parameters = {
        key: value for key, value in config.items() if key not in {"FunctionName", "_flowops"}
    }
    configuration = state.get("Configuration", {})
    revision = configuration.get("RevisionId")
    if action_id.endswith("update_function_configuration"):
        proposed.setdefault("Configuration", {}).update(parameters)
        if "Environment" in parameters:
            old = configuration.get("Environment", {}).get("Variables", {})
            new = parameters["Environment"].get("Variables", {})
            proposed["EnvironmentVariablesChanged"] = sorted(
                key for key in old.keys() | new.keys() if old.get(key) != new.get(key)
            )
    elif action_id.endswith("update_function_code"):
        image = bool(parameters.get("ImageUri"))
        zipped = "ZipFile" in parameters
        stored = bool(parameters.get("S3Bucket")) and bool(parameters.get("S3Key"))
        if sum((image, zipped, stored)) != 1:
            raise WorkflowValidationError(
                "Choose exactly one Lambda artifact: ZipFile, S3 bucket/key, or ImageUri."
            )
        if (configuration.get("PackageType") == "Image") != image:
            raise WorkflowValidationError(
                "The artifact must match the current Lambda package type."
            )
        if zipped:
            raw = parameters["ZipFile"]
            try:
                content = base64.b64decode(raw["base64"], validate=True)
            except (KeyError, TypeError, ValueError) as exc:
                raise WorkflowValidationError(
                    "ZipFile must use the base64 binary envelope."
                ) from exc
            parameters["ZipFile"] = {
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
            }
        proposed["ProposedArtifact"] = parameters
    elif "alias" in action_id:
        aliases = proposed.setdefault("Aliases", [])
        name = config.get("Name")
        if not isinstance(name, str) or not name:
            raise WorkflowValidationError("Alias review requires Name.")
        existing: dict[str, Any] = next(
            (alias for alias in aliases if alias.get("Name") == name), {}
        )
        revision = existing.get("RevisionId") if action_id.endswith("update_alias") else None
        proposed["Aliases"] = [alias for alias in aliases if alias.get("Name") != name]
        if not action_id.endswith("delete_alias"):
            proposed["Aliases"].append(existing | parameters)
    else:
        proposed["PublishVersion"] = parameters
    safe_current, safe_proposed = (
        bounded_output(_display(state)),
        bounded_output(_display(proposed)),
    )
    diff = "".join(
        unified_diff(
            json.dumps(safe_current, indent=2, sort_keys=True).splitlines(keepends=True),
            json.dumps(safe_proposed, indent=2, sort_keys=True).splitlines(keepends=True),
            fromfile="CURRENT",
            tofile="PROPOSED",
        )
    )
    return {
        "current": safe_current,
        "proposed": safe_proposed,
        "diff": diff,
        "revision_id": revision,
    }


def review_lambda(
    registry: ActionRegistry,
    user: Identity,
    aws: AWSContext,
    action_id: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    require(user, "aws.read")
    if action_id not in REVIEW_ACTIONS:
        raise WorkflowValidationError("This operation has no Lambda change review.")
    name = config.get("FunctionName")
    if not isinstance(name, str) or not name or "{{" in name:
        raise WorkflowValidationError(
            "Set a concrete FunctionName before loading the current state."
        )
    context = ActionContext(new_id(), "lambda_review", aws, True)
    parameters = {"FunctionName": name}
    action = registry.get("lambda.get_function")
    action.validate(parameters)
    try:
        current = action.execute(parameters, context)
        for operation, field in (
            ("list_aliases", "Aliases"),
            ("list_versions_by_function", "Versions"),
        ):
            reader = registry.get(f"lambda.{operation}")
            current[field] = reader.execute(
                parameters | {"_flowops": {"paginate": True, "max_items": 100}}, context
            ).get(field, [])
        return change_preview(current, action_id, config)
    finally:
        release = getattr(getattr(action, "backend", None), "release", None)
        if callable(release):
            release(context.execution_id)
