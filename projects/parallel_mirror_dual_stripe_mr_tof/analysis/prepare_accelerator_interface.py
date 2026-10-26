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


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


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








def _native_refine_change(reference: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any] | None:
    """Validate both native identities and isolate only the declared Boolean strategy."""
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding import resolve_native_refine_numerics

    profiles = [value["simion"].get("numerical_profiles", {}) for value in (reference, contract)]
    if not any("native_static_field" in profile for profile in profiles):
        return None
    previous, current = [resolve_native_refine_numerics(value) for value in (reference, contract)]
    for value in (reference, contract):
        value["simion"]["numerical_profiles"]["native_static_field"]["refine"].pop("skipped_point", None)
    if previous == current:
        return None
    # Other numerical changes remain in the full contract comparison below.
    return dict(change_kind="native_refine_skipped_point_policy_only", previous=previous, current=current)


def validate_execution_contract(reference: dict[str, Any], contract: dict[str, Any], *,
                                allow_controller_budget: bool = False) -> dict[str, Any]:
    """Allow observation changes and one selected integration bound, never physics."""
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import resolve_trajectory_profile

    expected = json.loads(json.dumps(reference))
    scientific = json.loads(json.dumps(contract))
    expected["simion"].pop("trajectory_recording", None)
    scientific["simion"].pop("trajectory_recording", None)
    native_refine_change = _native_refine_change(expected, scientific)
    analysis_change = None
    peak = scientific.get("peak_analysis")
    previous_peak = expected.get("peak_analysis")
    if peak and peak.get("time_basis") == "instrument_arrival_minus_common_extraction_pulse_us":
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.measured_component_analysis import validate_measured_peak_analysis_contract
        validate_measured_peak_analysis_contract(peak, Path.cwd())
        if peak != previous_peak:
            names = ("method_id", "resolution_definition", "settings")
            if previous_peak is None or any(peak[name] != previous_peak.get(name) for name in names):
                raise ValueError("Measured peak reference change must retain the declared method and settings")
            analysis_change = dict(change_kind="measured_detector_common_pulse_reference",
                                   previous=previous_peak, current=peak)
            scientific["peak_analysis"] = expected["peak_analysis"]
    previous = resolve_trajectory_profile(expected)
    current = resolve_trajectory_profile(scientific)
    profile_id = previous["profile_id"]
    if current["profile_id"] != profile_id:
        raise ValueError("Prepared joint trial must retain its selected trajectory profile")
    if current["trajectory_quality"] != previous["trajectory_quality"]:
        raise ValueError("Prepared joint timestep comparison must retain trajectory quality")
    selected = scientific["simion"]["trajectory_profiles"][profile_id]["maximum_step_us"]
    if isinstance(selected, bool) or not isinstance(selected, (int, float)):
        raise ValueError("Selected maximum_step_us must be a numeric integration bound")
    change = None
    if current["maximum_step_us"] != previous["maximum_step_us"]:
        change = dict(change_kind="selected_trajectory_maximum_step_only", profile_id=profile_id,
                      maximum_step_us=dict(previous=previous["maximum_step_us"], current=current["maximum_step_us"]))
    scientific["simion"]["trajectory_profiles"][profile_id]["maximum_step_us"] = (
        expected["simion"]["trajectory_profiles"][profile_id]["maximum_step_us"])
    budget = None
    if scientific != expected:
        if not allow_controller_budget:
            raise ValueError("Finalization contract changes more than the selected trajectory step")
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration import assert_bounded_controller_resume
        budget = assert_bounded_controller_resume(expected, scientific, None, budget_only=True)
    return dict(reference_profile=previous, selected_profile=current, numerical_change=change,
                execution_budget_change=budget, analysis_change=analysis_change,
                native_refine_change=native_refine_change)
