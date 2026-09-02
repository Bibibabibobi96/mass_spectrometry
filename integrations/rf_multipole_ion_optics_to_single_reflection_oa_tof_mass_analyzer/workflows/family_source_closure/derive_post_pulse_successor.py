"""Derive an immutable post-pulse campaign from frozen pre-pulse evidence."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError


INTEGRATION_ID = "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
POST_PULSE_TOPOLOGY_ID = "full_bore_main_with_entrance_local_v1"


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


def derive_campaign(*, repo_root: Path, parent_manifest_path: Path,
                    materialization_manifest_path: Path, output_path: Path) -> dict[str, Any]:
    """Derive all population and physical identity from immutable evidence."""

    parent = _load(parent_manifest_path, "pre-pulse parent manifest")
    if parent.get("status") != "success" or parent.get("project") != INTEGRATION_ID:
        raise ContractError("pre-pulse parent is not successful integration evidence")
    frozen_path = parent_manifest_path.parent / "inputs" / "frozen_campaign_experiment.json"
    frozen = _load(frozen_path, "frozen pre-pulse experiment")
    experiment = frozen.get("experiment")
    if not isinstance(experiment, dict):
        raise ContractError("frozen pre-pulse experiment is missing")
    receipt_path = materialization_manifest_path.parent / "results" / "time_series_restart_materialization_receipt.json"
    receipt = _load(receipt_path, "restart materialization receipt")
    target = receipt.get("pulse_target_state")
    if not isinstance(target, dict) or not isinstance(target.get("particle_count"), int):
        raise ContractError("restart materialization target is incomplete")
    state_path = materialization_manifest_path.parent / "results" / "canonical_pre_pulse_restart_state.csv"
    if target.get("sha256") != file_sha256(state_path):
        raise ContractError("restart state identity differs from its receipt")
    configuration = _load(
        repo_root / "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/config/simion_single_flight.json",
        "single-flight configuration",
    )
    policy = _load(
        repo_root / "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/config/execution_policy.json",
        "execution policy",
    )
    successor = copy.deepcopy(experiment)
    successor["source_release_mode"] = "pre_pulse_restart"
    successor["single_flight_frontend_grid_profile_id"] = _full_bore_profile_id(configuration)
    population = successor.get("single_flight_population")
    if not isinstance(population, dict):
        raise ContractError("frozen pre-pulse population is missing")
    count = target["particle_count"]
    population.update({
        "population_mode": "pre_pulse_restart",
        "source_authority": {"input_role": "pre_pulse_source_state", "table_binding": "experiment_pre_pulse_source_state", "ordered_particle_id_encoding": "canonical_compact_json_integer_array_v1"},
        "execution_population": {"particle_count": count, "ordered_particle_id_sha256": target["ordered_particle_id_sha256"], "selection_algorithm": "all_rows_in_frozen_file_order", "selection_seed": 0},
        "denominators": {"population_count": receipt["selection"]["producer_population_denominator_count"], "eligible_population_count": count},
    })
    successor["pre_pulse_source_state"] = {
        "path": str(state_path), "sha256": target["sha256"], "particle_count": count,
        "coordinate_frame": target["coordinate_frame"], "release_event": "pre_pulse_state",
        "materialization_receipt": {"path": str(receipt_path), "sha256": file_sha256(receipt_path)},
        "source_state_epoch": target["source_state_epoch"], "source_state_locus": target["source_state_locus"]["kind"],
        "position_rowwise_abs_tolerance_mm": 1e-9, "velocity_rowwise_abs_tolerance_m_per_s": 1e-6,
        "clock_abs_tolerance_us": 1e-9, "energy_abs_tolerance_eV": 5e-9, "postselection_prohibited": True,
    }
    aperture = successor["accelerator_entrance_local_aperture_mm"]
    experiment_id = f"{experiment['experiment_id']}_post_pulse"
    successor["experiment_id"] = experiment_id
    campaign = {"schema_version": 7, "role": "rf_multipole_oatof_experiment_campaign", "integration_id": INTEGRATION_ID,
        "campaign_id": f"{experiment_id}_derived", "status": "exploration",
        "execution_policy": {"path": "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/config/execution_policy.json", "sha256": file_sha256(repo_root / "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/config/execution_policy.json")},
        "claim_limit": f"DEVELOPMENT_ONLY conditional restart transport; all rates retain frozen {receipt['selection']['producer_population_denominator_count']}-ion mother denominator.",
        "experiments": {"shared": {key: value for key, value in successor.items() if key not in {"experiment_id", "single_flight_layout_profile_id", "connection_profile_id", "accelerator_entrance_local_aperture_mm", "sequence", "run_id"}},
         "variation_axes": ["single_flight_layout_profile_id", "connection_profile_id", "accelerator_entrance_local_aperture_mm"],
         "rows": [{"experiment_id": experiment_id, "values": {"single_flight_layout_profile_id": successor["single_flight_layout_profile_id"], "connection_profile_id": successor["connection_profile_id"], "accelerator_entrance_local_aperture_mm": aperture}}]}}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(campaign, indent=2) + "\n", encoding="utf-8")
    return campaign


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--pre-pulse-parent-manifest", required=True, type=Path)
    parser.add_argument("--materialization-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    campaign = derive_campaign(repo_root=args.repo_root.resolve(), parent_manifest_path=args.pre_pulse_parent_manifest.resolve(), materialization_manifest_path=args.materialization_manifest.resolve(), output_path=args.output.resolve())
    print(f"DERIVED_POST_PULSE_SUCCESSOR=PASS EXPERIMENT={campaign['experiments']['rows'][0]['experiment_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
