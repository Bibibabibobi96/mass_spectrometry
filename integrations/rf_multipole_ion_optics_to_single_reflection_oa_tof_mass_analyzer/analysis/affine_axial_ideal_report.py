"""Build a PROVISIONAL affine-axial all-ideal diagnostic report."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import load_json
from common.contracts.particle_physics import kinetic_energy_ev, mass_to_charge_th
from common.multipole.compile_design_request import canonical_sha256
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source import (
    resolve_source_materialization_profile,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.accelerator_time_focus import (
    PhysicsContractError,
    accelerator_state,
    time_to_fixed_plane_s,
)
from common.analysis.peak_metrics import (
    compute_peak_metrics,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.reflectron_dual_stage_solver import (
    flight_time_s,
)


WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
ENERGY_ENVELOPE_ABS_TOL_V = 1.0e-9


def resolve_bound_input_path(root: Path, record: Mapping[str, Any], label: str) -> Path:
    """Resolve one SHA-bound workspace input or fail closed."""

    path = (root / str(record["path"])).resolve()
    if not path.is_file() or file_sha256(path) != record.get("sha256"):
        raise PhysicsContractError(f"{label} is missing or SHA-256 differs")
    return path


def select_bound_source_profile(
    registry: Mapping[str, Any], case: Mapping[str, Any]
) -> Mapping[str, Any]:
    """Select the uniquely identified source-profile definition for an analytic case."""

    matches = [
        value
        for value in registry.get("source_materialization_profiles", [])
        if value.get("profile_id") == case["source_profile_id"]
    ]
    if len(matches) != 1 or canonical_sha256(matches[0]) != case["source_profile_definition_sha256"]:
        raise PhysicsContractError("source materialization profile identity differs")
    return matches[0]


def _validate_release(path: Path, expected_count: int) -> None:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    try:
        ids = [int(row["particle_id"]) for row in rows]
    except (KeyError, TypeError, ValueError) as error:
        raise PhysicsContractError("source release CSV particle_id is invalid") from error
    if len(rows) != expected_count or ids != list(range(1, expected_count + 1)):
        raise PhysicsContractError("source release CSV count or ordered particle IDs differ")


def compute_analytic_report(
    campaign_path: Path,
    case_id: str,
    *,
    workspace_root: Path = WORKSPACE_ROOT,
) -> dict[str, Any]:
    """Return one JSON-ready PROVISIONAL diagnostic report."""

    campaign_path = campaign_path.resolve()
    campaign = load_json(campaign_path)
    if not isinstance(campaign, dict) or (
        campaign.get("role") != "rf_oatof_affine_axial_all_ideal_report_campaign"
        or campaign.get("evidence_level") != "PROVISIONAL"
    ):
        raise PhysicsContractError("analytic campaign identity is invalid")
    cases = [case for case in campaign.get("cases", []) if case.get("case_id") == case_id]
    if len(cases) != 1:
        raise PhysicsContractError("case_id must select exactly one analytic case")
    case = cases[0]
    geometry_path = resolve_bound_input_path(
        workspace_root, case["resolved_geometry"], "geometry"
    )
    receipt_path = resolve_bound_input_path(
        workspace_root, case["source_materialization_receipt"], "source receipt"
    )
    release_path = resolve_bound_input_path(
        workspace_root, case["source_release_csv"], "source release CSV"
    )
    registry_path = (workspace_root / campaign["source_profile_registry_path"]).resolve()
    geometry = load_json(geometry_path)
    receipt = load_json(receipt_path)
    profile = resolve_source_materialization_profile(
        dict(select_bound_source_profile(load_json(registry_path), case)), INTEGRATION_ROOT,
    )
    expected = case["source_contract"]
    count = int(expected["particle_count"])
    if count < 2 or expected["full_width_mm"] <= 0 or expected["charge_state"] <= 0:
        raise PhysicsContractError("analytic source requires N >= 2, positive width and ions")
    release = receipt.get("particle_source", {})
    receipt_physics = receipt.get("physics", {})
    _validate_release(release_path, count)
    if (
        receipt.get("role") != "rf_oatof_single_flight_source_materialization_receipt"
        or receipt.get("method") != "resolved_layout_pulse_contract_ideal_linear_z_vz_v1"
        or receipt.get("profile_id")
        != case.get("target_materialization_profile_id", case["source_profile_id"])
        or release.get("sha256") != case["source_release_csv"]["sha256"]
        or release.get("particle_count") != count
        or release.get("sampling_mode") != "continuous_injection_full_population"
        or receipt.get("particle_count") != count
        or receipt.get("source_full_width_mm") != expected["full_width_mm"]
        or receipt_physics.get("mass_amu") != expected["mass_amu"]
        or receipt_physics.get("charge_state") != expected["charge_state"]
        or profile.get("particle_count") != count
        or profile.get("source_full_width_mm") != expected["full_width_mm"]
        or profile.get("mass_amu") != expected["mass_amu"]
        or profile.get("charge_state") != expected["charge_state"]
    ):
        raise PhysicsContractError("source profile, receipt, release CSV, or contract differs")
    if (
        geometry.get("role") != "oa_tof_resolved_contract_do_not_edit"
        or geometry.get("single_flight_layout_derivation", {}).get(
            "architecture_generation_id"
        )
        != case["architecture_generation_id"]
    ):
        raise PhysicsContractError("resolved geometry architecture identity differs")

    accelerator = geometry["geometry_derivation"]["accelerator"]
    theory = accelerator["finite_interval_theory"]
    reflectron = theory["coupled_reflectron"]
    electrodes = geometry["electrodes_V"]
    mass_amu = float(expected["mass_amu"])
    charge = int(expected["charge_state"])
    mz = mass_to_charge_th(mass_amu, charge)
    if mz != float(expected["mass_to_charge_Th"]):
        raise PhysicsContractError("mass-to-charge differs from mass and charge state")
    width = float(expected["full_width_mm"])
    center_z = float(receipt["resolved_target_center_mm"][2])
    repeller_z = float(accelerator["canonical_repeller_z_mm"])
    mean_vz = float(profile["mean_velocity_z_m_per_s"])
    slope_vz = float(profile["velocity_z_slope_m_per_s_per_mm"])
    particles = []
    for index in range(count):
        z = center_z - width / 2.0 + width * index / (count - 1)
        vz = mean_vz + slope_vz * (z - center_z)
        release_z = z - repeller_z
        state = accelerator_state(
            float(electrodes["repeller"]),
            float(electrodes["grid1"]),
            float(accelerator["d1_mm"]),
            float(accelerator["d2_mm"]),
            exit_v=float(electrodes["grid2"]),
            release_position_mm=release_z,
            require_downstream_focus=False,
        )
        energy = state.nominal_energy_per_charge_v + kinetic_energy_ev(
            mass_amu, 0.0, 0.0, vz
        ) / charge
        accelerator_tof = time_to_fixed_plane_s(
            float(electrodes["repeller"]),
            float(electrodes["grid1"]),
            float(accelerator["d1_mm"]),
            float(accelerator["d2_mm"]),
            release_z,
            vz,
            float(theory["focus_drift_mm"]),
            mz,
            exit_v=float(electrodes["grid2"]),
        )
        total_tof = accelerator_tof + flight_time_s(
            energy,
            mz,
            float(reflectron["total_field_free_length_mm"]),
            float(reflectron["stage1_voltage_drop_v"]),
            float(reflectron["stage1_field_v_per_mm"]),
            float(reflectron["stage2_field_v_per_mm"]),
        )
        particles.append(
            {
                "particle_id": index + 1,
                "axial_energy_per_charge_V": energy,
                "pulse_effective_detector_tof_us": total_tof * 1.0e6,
            }
        )

    times = np.asarray([row["pulse_effective_detector_tof_us"] for row in particles])
    energies = np.asarray([row["axial_energy_per_charge_V"] for row in particles])
    peak, _ = compute_peak_metrics(times, mass_amu)
    energy_min = float(reflectron["energy_min_v"])
    energy_max = float(reflectron["energy_max_v"])
    outside = (energies < energy_min - ENERGY_ENVELOPE_ABS_TOL_V) | (
        energies > energy_max + ENERGY_ENVELOPE_ABS_TOL_V
    )
    outside_count = int(np.count_nonzero(outside))
    lower_exceedance = max(0.0, energy_min - float(np.min(energies)))
    upper_exceedance = max(0.0, float(np.max(energies)) - energy_max)
    if outside_count and not case.get("allow_diagnostic_extrapolation", False):
        raise PhysicsContractError("axial energy exceeds resolved reflectron envelope")
    return {
        "schema_version": 1,
        "report_role": "rf_oatof_affine_axial_all_ideal_analytic_report",
        "status": "diagnostic_extrapolation" if outside_count else "diagnostic",
        "evidence_level": "PROVISIONAL",
        "claim_scope": "analytic_diagnostic_not_solver_candidate_or_formal",
        "case_id": case_id,
        "architecture_id": case["architecture_id"],
        "field_profile_id": case["field_profile_id"],
        "clock": {"time_zero": "pulse_effective_time"},
        "inputs": {
            "campaign": {"path": campaign_path.as_posix(), "sha256": file_sha256(campaign_path)},
            "resolved_geometry": dict(case["resolved_geometry"]),
            "source_materialization_receipt": dict(case["source_materialization_receipt"]),
            "source_release_csv": dict(case["source_release_csv"]),
            "source_profile_id": case["source_profile_id"],
            "pulse_state_derivation": "profile_velocity_on_materializer_target_contract",
        },
        "energy_envelope": {
            "authority": "resolved_geometry.geometry_derivation.accelerator.finite_interval_theory.coupled_reflectron",
            "resolved_min_V": energy_min,
            "resolved_max_V": energy_max,
            "observed_min_V": float(np.min(energies)),
            "observed_max_V": float(np.max(energies)),
            "inside_count": count - outside_count,
            "outside_count": outside_count,
            "comparison_abs_tolerance_V": ENERGY_ENVELOPE_ABS_TOL_V,
            "lower_exceedance_V": 0.0 if lower_exceedance <= ENERGY_ENVELOPE_ABS_TOL_V else lower_exceedance,
            "upper_exceedance_V": 0.0 if upper_exceedance <= ENERGY_ENVELOPE_ABS_TOL_V else upper_exceedance,
        },
        "summary": {
            "particle_count": count,
            "mean_tof_us": peak["mean_tof_us"],
            "population_sigma_tof_ns": float(np.std(times, ddof=0) * 1.0e3),
            "sample_sigma_tof_ns": peak["std_tof_ns"],
            "direct_fwhm_tof_ns": peak["direct_fwhm_tof_ns"],
            "mass_resolution": peak["mass_resolution"],
            "significant_kde_modes": peak["significant_kde_modes"],
        },
        "particle_tof_records_sha256": canonical_sha256(particles),
        "particle_tof_records": particles,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = compute_analytic_report(args.campaign, args.case_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"PROVISIONAL_ANALYTIC_REPORT={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
