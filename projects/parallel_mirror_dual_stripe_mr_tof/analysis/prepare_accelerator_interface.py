"""MR reference identity and scientific execution-contract validation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common.contracts.verify_run_manifest import record_path, verify_record

PROJECT = "parallel_mirror_dual_stripe_mr_tof"
ION_PROCESSOR = "dual_pressure_rectilinear_ion_processor"
REPO = Path(__file__).resolve().parents[3]
CONFIG = REPO / "projects" / PROJECT / "config"


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def verified_reference(run: Path, relative: str, *, required_status: str = "success") -> Path:
    """Verify the exact consumed record, without loading historical field payloads."""
    manifest = _read(run / "run_manifest.json")
    if (required_status not in {"success", "interrupted"}
            or manifest.get("project") != PROJECT or manifest.get("status") != required_status):
        raise ValueError(f"reference must be an MR run with status {required_status}")
    verify_record("reference run config", manifest["run_config"], base_dir=run)
    config = _read(record_path(manifest["run_config"], base_dir=run))
    desired = (run / relative).resolve()
    # Preparation runs freeze file records in their manifest-bound run config.
    # A normalized dependency projection can also have a path; it describes the
    # dependency and is not a second file record with byte/hash authority.
    config_records = [record for record in config.get("inputs", {}).values()
                      if isinstance(record, dict) and {"path", "bytes", "sha256"} <= record.keys()]
    records = [*manifest.get("inputs", {}).values(), *config_records, *manifest["outputs"]]
    matches = [r for r in records if record_path(r, base_dir=run) == desired]
    if not matches:
        raise ValueError(f"reference manifest does not bind {relative}")
    for record in matches:
        verify_record("consumed MR reference", record, base_dir=run)
    return desired










def validate_execution_contract(reference: dict[str, Any], contract: dict[str, Any], *,
                                allow_controller_budget: bool = False) -> dict[str, Any]:
    """Allow observation changes and one selected integration bound, never physics."""
    expected = json.loads(json.dumps(reference))
    scientific = json.loads(json.dumps(contract))
    expected["simion"].pop("trajectory_recording", None)
    scientific["simion"].pop("trajectory_recording", None)
    from msplatform.workflows.prepared_joint.analysis_contract import reference_changes
    changes = reference_changes(expected, scientific, contract_base=Path.cwd())
    budget = None
    if scientific != expected:
        if not allow_controller_budget:
            raise ValueError("Finalization contract changes more than the selected trajectory step")
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration import assert_bounded_controller_resume
        budget = assert_bounded_controller_resume(expected, scientific, None, budget_only=True)
    return dict(reference_profile=changes["reference_profile"], selected_profile=changes["selected_profile"],
                numerical_change=changes["numerical_change"], execution_budget_change=budget,
                analysis_change=changes["analysis_change"], native_refine_change=changes["native_refine_change"])
