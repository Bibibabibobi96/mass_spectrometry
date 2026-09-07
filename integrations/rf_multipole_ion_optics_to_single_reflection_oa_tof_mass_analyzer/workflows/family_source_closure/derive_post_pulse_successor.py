"""Derive an immutable post-pulse campaign from frozen pre-pulse evidence."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_pulse_duration import DURATION_POLICY_ID


INTEGRATION_ID = "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
POST_PULSE_TOPOLOGY_ID = "full_bore_main_with_entrance_local_v1"
COMPACT_RESTART_RECEIPT_ROLES = {
    "rf_oatof_compact_pre_pulse_trace_handoff_receipt",
    "rf_oatof_compact_pre_pulse_subset_receipt",
}


def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} is not readable JSON") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be a JSON object")
    return value


def _full_bore_profile_id(configuration: dict[str, Any]) -> str:
    profiles = configuration.get("frontend_grid_profiles")
    matches = [
        profile for profile in profiles if isinstance(profile, dict)
        and profile.get("post_pulse_topology_id") == POST_PULSE_TOPOLOGY_ID
    ] if isinstance(profiles, list) else []
    if len(matches) != 1 or not isinstance(matches[0].get("profile_id"), str):
        raise ContractError("exactly one registered full-bore post-pulse profile is required")
    return matches[0]["profile_id"]


def _workspace_relative(path: Path, workspace_root: Path) -> str:
    """Store artifact references portably rather than pinning a host path."""

    try:
        return path.resolve().relative_to(workspace_root.resolve()).as_posix()
    except ValueError as exc:
        raise ContractError("compact restart evidence escapes the workspace") from exc


def derive_campaign(*, repo_root: Path, parent_manifest_path: Path,
                    materialization_manifest_path: Path | None, output_path: Path,
                    compact_receipt_path: Path | None = None,
                    frozen_experiment_path: Path | None = None,
                    execution_mode: str = "particle_flight") -> dict[str, Any]:
    """Derive all population and physical identity from immutable evidence."""

    workspace_root = repo_root.parent
    if execution_mode not in {"particle_flight", "program_axis_field_export"}:
        raise ContractError("unsupported post-pulse execution mode")
    parent = _load(parent_manifest_path, "pre-pulse parent manifest")
    if parent.get("project") != INTEGRATION_ID:
        raise ContractError("pre-pulse parent is not successful integration evidence")
    if (materialization_manifest_path is None) == (compact_receipt_path is None):
        raise ContractError("supply exactly one restart evidence path")
    if compact_receipt_path is None and parent.get("status") != "success":
        raise ContractError("archive-backed derivation requires a successful pre-pulse parent")
    frozen_path = frozen_experiment_path or (
        parent_manifest_path.parent / "inputs" / "frozen_campaign_experiment.json"
    )
    frozen = _load(frozen_path, "frozen pre-pulse experiment")
    experiment = frozen.get("experiment")
    if not isinstance(experiment, dict):
        raise ContractError("frozen pre-pulse experiment is missing")
    if compact_receipt_path is not None:
        receipt_path = compact_receipt_path.resolve()
        receipt = _load(receipt_path, "compact restart receipt")
        if (
            receipt.get("role") not in COMPACT_RESTART_RECEIPT_ROLES
            or receipt.get("status") != "success"
        ):
            raise ContractError("compact restart receipt identity differs")
        state_path = Path(str(receipt.get("pulse_target_state", {}).get("path", "")))
    else:
        receipt_path = materialization_manifest_path.parent / "results" / "time_series_restart_materialization_receipt.json"
        receipt = _load(receipt_path, "restart materialization receipt")
        state_path = materialization_manifest_path.parent / "results" / "canonical_pre_pulse_restart_state.csv"
    target = receipt.get("pulse_target_state")
    if not isinstance(target, dict) or not isinstance(target.get("particle_count"), int):
        raise ContractError("restart materialization target is incomplete")
    if target.get("sha256") != file_sha256(state_path):
        raise ContractError("restart state identity differs from its receipt")
    configuration = _load(
        repo_root / "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/config/simion_single_flight.json",
        "single-flight configuration",
    )
    successor = copy.deepcopy(experiment)
    successor["source_release_mode"] = "pre_pulse_restart"
    successor["single_flight_execution_mode"] = execution_mode
    if "single_flight_pulse_schedule_policy" in successor:
        successor["single_flight_pulse_schedule_policy"]["duration_policy_id"] = DURATION_POLICY_ID
    successor["single_flight_frontend_grid_profile_id"] = _full_bore_profile_id(configuration)
    population = successor.get("single_flight_population")
    if not isinstance(population, dict):
        raise ContractError("frozen pre-pulse population is missing")
    count = target["particle_count"]
    population.update({
        "population_mode": "pre_pulse_restart",
        "source_authority": {"input_role": "pre_pulse_source_state", "table_binding": "experiment_pre_pulse_source_state", "ordered_particle_id_encoding": "canonical_compact_json_integer_array_v1"},
        "execution_population": {"particle_count": count, "ordered_particle_id_sha256": target["ordered_particle_id_sha256"], "selection_algorithm": "all_rows_in_frozen_file_order", "selection_seed": 0},
        "denominators": {"population_count": receipt["selection"].get("producer_population_denominator_count", receipt["selection"].get("mother_population_count")), "eligible_population_count": count},
    })
    successor["pre_pulse_source_state"] = {
        "path": _workspace_relative(state_path, workspace_root), "sha256": target["sha256"], "particle_count": count,
        "coordinate_frame": target["coordinate_frame"], "release_event": "pre_pulse_state",
        "materialization_receipt": {"path": _workspace_relative(receipt_path, workspace_root), "sha256": file_sha256(receipt_path)},
        "source_state_epoch": target["source_state_epoch"], "source_state_locus": target.get("source_state_locus", {"kind": "accelerator_stage1_interior_finite_observed_3d_cloud"})["kind"],
        "position_rowwise_abs_tolerance_mm": 1e-9, "velocity_rowwise_abs_tolerance_m_per_s": 1e-6,
        "clock_abs_tolerance_us": 1e-9, "energy_abs_tolerance_eV": 5e-9, "postselection_prohibited": True,
    }
    aperture = successor["accelerator_entrance_local_aperture_mm"]
    experiment_id = f"{experiment['experiment_id']}_post_pulse"
    successor["experiment_id"] = experiment_id
    campaign = {"schema_version": 7, "role": "rf_multipole_oatof_experiment_campaign", "integration_id": INTEGRATION_ID,
        "campaign_id": f"{experiment_id}_derived", "status": "exploration",
        "execution_policy": {"path": "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/config/execution_policy.json", "sha256": file_sha256(repo_root / "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/config/execution_policy.json")},
        "claim_limit": f"DEVELOPMENT_ONLY conditional restart transport; all rates retain frozen {receipt['selection'].get('producer_population_denominator_count', receipt['selection'].get('mother_population_count'))}-ion mother denominator.",
        "experiments": {"shared": {key: value for key, value in successor.items() if key not in {"experiment_id", "single_flight_layout_profile_id", "connection_profile_id", "accelerator_entrance_local_aperture_mm", "sequence", "run_id"}},
         "variation_axes": ["single_flight_layout_profile_id", "connection_profile_id", "accelerator_entrance_local_aperture_mm"],
         "rows": [{"experiment_id": experiment_id, "values": {"single_flight_layout_profile_id": successor["single_flight_layout_profile_id"], "connection_profile_id": successor["connection_profile_id"], "accelerator_entrance_local_aperture_mm": aperture}}]}}
    if execution_mode == "program_axis_field_export":
        campaign["claim_limit"] = "DEVELOPMENT_ONLY frozen post-pulse field diagnostic; no particle transport or resolution claim."
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(campaign, indent=2) + "\n", encoding="utf-8")
    return campaign


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--pre-pulse-parent-manifest", required=True, type=Path)
    parser.add_argument("--materialization-manifest", type=Path)
    parser.add_argument("--compact-receipt", type=Path)
    parser.add_argument(
        "--frozen-experiment", type=Path,
        help=(
            "Explicit immutable frozen experiment when an analysis-recovery "
            "parent does not retain its original campaign-parent input."
        ),
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    campaign = derive_campaign(repo_root=args.repo_root.resolve(), parent_manifest_path=args.pre_pulse_parent_manifest.resolve(), materialization_manifest_path=(args.materialization_manifest.resolve() if args.materialization_manifest else None), compact_receipt_path=(args.compact_receipt.resolve() if args.compact_receipt else None), output_path=args.output.resolve(), frozen_experiment_path=(args.frozen_experiment.resolve() if args.frozen_experiment else None))
    print(f"DERIVED_POST_PULSE_SUCCESSOR=PASS EXPERIMENT={campaign['experiments']['rows'][0]['experiment_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
