"""Derive a shared pulse time from selected-species handoff phase space."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from plot_s1_pulse_geometry_snapshot import accelerator_geometry
except ModuleNotFoundError:
    from projects.rf_quadrupole_collision_cooling.analysis.plot_s1_pulse_geometry_snapshot import accelerator_geometry


PROJECT_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = PROJECT_ROOT / "config" / "rf_to_oatof_pulse_timing.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_policy(policy_path: Path = POLICY_PATH) -> dict:
    policy = load_json(policy_path)
    if policy.get("schema_version") != 1:
        raise ValueError("pulse timing policy schema is invalid")
    if policy.get("method") != "selected_species_ballistic_port_survivor_x_centroid":
        raise ValueError("pulse timing method is not the supported centroid scheduler")
    population = policy["population"]
    if population.get("species_key") != ["mass_amu", "charge_state"]:
        raise ValueError("pulse timing species key changed")
    if int(population.get("minimum_particles_after_port_prediction", 0)) < 1:
        raise ValueError("pulse timing must require at least one predicted port survivor")
    claims = policy["claims"]
    if claims.get("continuous_beam_time_slice_extraction") is not True:
        raise ValueError("pulse timing policy lost its continuous-beam scope")
    if claims.get("compact_storage_required") is not False:
        raise ValueError("centroid scheduling must not claim compact storage")
    if claims.get("hit_rate_gate_required_for_timing_validation") is not False:
        raise ValueError("timing validation must remain independent of hit rate")
    return policy


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def derive_schedule(particle_path: Path, baseline_path: Path, joint_path: Path,
                    policy_path: Path = POLICY_PATH, target_mass_amu: float | None = None,
                    target_charge_state: int | None = None,
                    s2_contract_path: Path | None = None) -> dict[str, object]:
    policy = validate_policy(policy_path)
    particles = pd.read_csv(particle_path)
    required = {
        "particle_id", "instrument_time_us", "mass_amu", "charge_state",
        "position_x_mm", "position_y_mm", "position_z_mm", "velocity_x_m_s", "velocity_y_m_s",
        "velocity_z_m_s",
    }
    if not required.issubset(particles.columns):
        raise ValueError("canonical handoff table is missing pulse-scheduler columns")
    if (target_mass_amu is None) != (target_charge_state is None):
        raise ValueError("target mass and charge state must be specified together")

    species = particles[["mass_amu", "charge_state"]].drop_duplicates()
    if target_mass_amu is None:
        if len(species) != 1:
            raise ValueError("mixed-species input requires an explicit target mass and charge state")
        target_mass_amu = float(species.iloc[0]["mass_amu"])
        target_charge_state = int(species.iloc[0]["charge_state"])
    selected = particles[
        np.isclose(particles["mass_amu"], float(target_mass_amu), rtol=0, atol=1e-12)
        & particles["charge_state"].eq(int(target_charge_state))
    ].copy()
    if selected.empty:
        raise ValueError("selected target species is absent from the handoff table")
    if (selected["velocity_x_m_s"] <= 0).any():
        raise ValueError("selected pulse population must move in the positive injection direction")

    baseline = load_json(baseline_path)
    joint = load_json(joint_path)
    geometry = accelerator_geometry(baseline, joint)
    schedule_stage = "S1"
    if s2_contract_path is None:
        offset = float(joint["port_sweep"]["particle_release_offset_inside_outer_face_mm"])
        entry_center = joint["nominal_registration"]["target_entry_center_instrument_mm"]
        port_width = float(geometry["port_width_y"])
        port_height = float(geometry["port_height_z"])
    else:
        s2 = load_json(s2_contract_path)
        if s2.get("stage") != "S2":
            raise ValueError("S3 timing requires an S2 connector contract")
        if not {"event", "status"}.issubset(selected.columns):
            raise ValueError("S3 timing states must identify real S2 oa-entry events")
        selected = selected[
            selected["event"].eq("oatof_entry") & selected["status"].eq("transmitted")
        ].copy()
        if selected.empty:
            raise ValueError("S3 timing states contain no transmitted oa-entry event")
        offset = float(s2["no_pulse_field_candidate"]["boundary_probe_inset_mm"])
        entry_center = s2["nominal_registration"]["target_entry_center_instrument_mm"]
        port = s2["passive_connector_geometry"]["downstream_entry_aperture"]
        port_width = float(port["full_width_y_mm"])
        port_height = float(port["full_height_z_mm"])
        schedule_stage = "S3"
    entry_surface_x = float(entry_center[0])
    if not np.allclose(selected["position_x_mm"], entry_surface_x, rtol=0, atol=1e-12):
        raise ValueError(
            "canonical handoff position_x_mm must equal the physical oa-TOF entry surface; "
            "projection or silent coordinate replacement is forbidden"
        )
    release_x = entry_surface_x + offset
    target_x = float(geometry["source_center"]["x"])
    port_center_z = float(entry_center[2])
    half_y = port_width / 2
    half_z = port_height / 2
    wall = float(geometry["shield_wall"])

    at_outer = (
        selected["position_y_mm"].abs().le(half_y + 1e-12)
        & (selected["position_z_mm"] - port_center_z).abs().le(half_z + 1e-12)
    )
    outer = selected[at_outer].copy()
    outer["predicted_inner_y_mm"] = (
        outer["position_y_mm"] + outer["velocity_y_m_s"] / outer["velocity_x_m_s"] * wall)
    outer["predicted_inner_z_mm"] = (
        outer["position_z_mm"] + outer["velocity_z_m_s"] / outer["velocity_x_m_s"] * wall)
    at_inner = (
        outer["predicted_inner_y_mm"].abs().le(half_y + 1e-12)
        & (outer["predicted_inner_z_mm"] - port_center_z).abs().le(half_z + 1e-12)
    )
    cohort = outer[at_inner].copy()
    minimum = int(policy["population"]["minimum_particles_after_port_prediction"])
    if len(cohort) < minimum:
        raise ValueError("finite-wall prediction leaves too few particles for pulse scheduling")

    mean_vx = float(cohort["velocity_x_m_s"].mean())
    mean_vx_t = float((cohort["velocity_x_m_s"] * cohort["instrument_time_us"]).mean())
    pulse_time = (1000.0 * (target_x - release_x) + mean_vx_t) / mean_vx
    predicted_x = release_x + cohort["velocity_x_m_s"] * (
        pulse_time - cohort["instrument_time_us"]) / 1000.0
    centroid_error = float(predicted_x.mean() - target_x)
    if not math.isclose(centroid_error, 0.0, abs_tol=1e-9):
        raise ValueError("derived pulse time does not center the selected cohort")

    energy = cohort["kinetic_energy_eV"] if "kinetic_energy_eV" in cohort else None
    return {
        "schema_version": 1,
        "role": f"rf_to_oatof_{schedule_stage.lower()}_centroid_pulse_schedule",
        "stage": schedule_stage,
        "status": "PASS",
        "method": policy["method"],
        "source_particle_table": str(particle_path.resolve()),
        "source_particle_table_sha256": _sha256(particle_path),
        "target_species": {
            "mass_amu": float(target_mass_amu),
            "charge_state": int(target_charge_state),
        },
        "population_counts": {
            "input_all_species": int(len(particles)),
            "selected_species": int(len(selected)),
            "outer_face_geometric_acceptance": int(len(outer)),
            "predicted_finite_wall_survivors": int(len(cohort)),
        },
        "geometry_mm": {
            "canonical_entry_surface_x": entry_surface_x,
            "numerical_release_offset_inside_surface": offset,
            "release_x": release_x,
            "target_centroid_x": target_x,
            "shield_wall_thickness": wall,
            "port_full_width_y": 2 * half_y,
            "port_full_height_z": 2 * half_z,
        },
        "selected_cohort": {
            "particle_ids": [int(value) for value in cohort["particle_id"]],
            "mean_entry_instrument_time_us": float(cohort["instrument_time_us"].mean()),
            "mean_velocity_x_m_s": mean_vx,
            "mean_velocity_x_times_entry_time_m_s_us": mean_vx_t,
            "mean_kinetic_energy_eV": float(energy.mean()) if energy is not None else None,
        },
        "derived_pulse_time_us": pulse_time,
        "pulse_width_us": float(policy["waveform"]["pulse_width_us"]),
        "predicted_centroid_x_at_pulse_mm": float(predicted_x.mean()),
        "predicted_centroid_error_x_mm": centroid_error,
        "hit_rate_gate_applied": False,
        "compact_storage_claimed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--particle-state", type=Path)
    parser.add_argument("--oatof-baseline", type=Path)
    parser.add_argument("--joint-contract", type=Path)
    parser.add_argument("--s2-contract", type=Path)
    parser.add_argument("--policy", type=Path, default=POLICY_PATH)
    parser.add_argument("--target-mass-amu", type=float)
    parser.add_argument("--target-charge-state", type=int)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check-contract", action="store_true")
    args = parser.parse_args()
    if args.check_contract:
        validate_policy(args.policy)
        print("S1_PULSE_TIMING_POLICY=PASS")
        return
    required = (args.particle_state, args.oatof_baseline, args.joint_contract, args.output)
    if any(value is None for value in required):
        parser.error("derivation requires particle state, oaTOF baseline, joint contract and output")
    result = derive_schedule(args.particle_state, args.oatof_baseline, args.joint_contract,
                             args.policy, args.target_mass_amu, args.target_charge_state,
                             args.s2_contract)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{result['stage']}_CENTROID_PULSE_TIME=PASS TIME_US={result['derived_pulse_time_us']:.12f} "
          f"COHORT={result['population_counts']['predicted_finite_wall_survivors']}")


if __name__ == "__main__":
    main()
