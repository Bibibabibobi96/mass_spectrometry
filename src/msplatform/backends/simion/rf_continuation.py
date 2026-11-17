"""Read RF continuation lineage from terminal owner records."""
from __future__ import annotations

from pathlib import Path

from msplatform.io.manifest_records import record_path, require_completed_terminal_publication
from msplatform.execution.retention import verify_record
from msplatform.io.strict_json import load_json_object


def ancestry(predecessor: Path, project: str, mode: str = "resolved_design_transport") -> list[Path]:
    """Follow only manifest-bound direct predecessors; reject cycles and drift."""
    current, chain = predecessor.resolve(strict=True), []
    while True:
        if current in chain:
            raise ValueError("RF continuation ancestry contains a cycle")
        chain.append(current)
        manifest_path = current / "run_manifest.json"
        require_completed_terminal_publication(manifest_path)
        manifest = load_json_object(manifest_path)
        if (manifest.get("project") != project or manifest.get("mode") != mode
                or manifest.get("run_id") != current.name or manifest.get("status") not in {"success", "failed", "interrupted"}):
            raise ValueError("RF continuation ancestor is not a terminal owner run")
        inputs = manifest.get("inputs", {})
        plan_record = inputs.get("continuation_plan")
        parent_record = inputs.get("continuation_predecessor_manifest")
        if not plan_record and not parent_record:
            return chain
        if not plan_record or not parent_record:
            raise ValueError("RF continuation provenance is incomplete")
        verify_record("RF continuation plan", plan_record, base_dir=current)
        verify_record("RF continuation parent", parent_record, base_dir=current)
        plan = load_json_object(record_path(plan_record, base_dir=current))
        parent = record_path(parent_record, base_dir=current)
        if (parent.name != "run_manifest.json" or plan.get("role") != "simion_whole_unit_replay_plan"
                or plan.get("status") != "ready" or str(parent.parent) != plan["predecessor"]["run_dir"]
                or str(parent_record["sha256"]).upper() != str(plan["predecessor"]["manifest_sha256"]).upper()):
            raise ValueError("RF continuation parent binding differs")
        current = parent.parent.resolve(strict=True)
