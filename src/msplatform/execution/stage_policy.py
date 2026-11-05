"""Read explicit per-action engineering limits using existing process fields."""
from __future__ import annotations

import copy
import json
from typing import Any

from .context import ExecutionContext
from .manifest_records import file_record, verify_record
from .artifact_retention import validate_retention, load_policy


def read_stage_policy(context: ExecutionContext, action: str, *,
                      required_roles: tuple[str, ...] = ()) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return one selected budget and its exact existing file authority.

    This contains engineering/retention settings, never provider, drive, source
    or solver numerics. The existing owner performs capacity admission.
    """
    if context.stage_policy_path is None:
        raise ValueError("This action requires explicit execution policy stage_policy_path")
    record = file_record(context.stage_policy_path, "required_evidence")
    document = json.loads(context.stage_policy_path.read_text(encoding="utf-8-sig"))
    verify_record("execution stage policy", record)
    if (not isinstance(document, dict) or set(document) != {"schema_version", "role", "stages"}
            or type(document["schema_version"]) is not int or document["schema_version"] != 1
            or document["role"] != "execution_stage_policy" or not isinstance(document["stages"], dict)):
        raise ValueError("Unsupported execution stage policy")
    stage = copy.deepcopy(document["stages"].get(action))
    if (not isinstance(stage, dict) or not {"limits", "artifact_retention"} <= set(stage)
            or set(stage) - {"limits", "artifact_retention", "runtime"}
            or ("runtime" in stage and not isinstance(stage["runtime"], dict))):
        raise ValueError("Execution policy omits limits/retention for action: " + action)
    limits = stage["limits"]
    required = {"wall_clock_seconds", "transient_run_directory_bytes", "process_tree_working_set_bytes",
                "minimum_system_available_memory_bytes", "compact_final_retained_bytes"}
    extra = {"reserved_run_payload_bytes"} if action == "solve_fields" else set()
    if (not isinstance(limits, dict) or set(limits) != required | {"automatic_retry_count"} | extra
            or any(type(limits[name]) is not int or limits[name] <= 0 for name in required)
            or type(limits["automatic_retry_count"]) is not int or limits["automatic_retry_count"] != 0):
        raise ValueError("Execution stage requires positive existing process limits and zero automatic retries")
    if extra and (type(limits["reserved_run_payload_bytes"]) is not int
                  or not 0 <= limits["reserved_run_payload_bytes"] <= limits["transient_run_directory_bytes"]):
        raise ValueError("Field stage requires an explicit nonnegative run reserve within its original commitment")
    retention = validate_retention(stage["artifact_retention"])
    allowed = set(load_policy()["classes"][retention.class_id]["allowed_roles"])
    if set(required_roles) - allowed:
        raise ValueError("Execution retention class cannot retain this action's required data roles")
    return stage, record
