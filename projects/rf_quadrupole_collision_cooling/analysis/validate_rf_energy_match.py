"""Validate the paired RF-to-oaTOF axial-energy matching candidate."""

from __future__ import annotations

import json
import math
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = PROJECT_ROOT / "config" / "rf_to_oatof_energy_match_candidate.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(path: Path = CONTRACT_PATH) -> dict:
    contract = load(path)
    if contract.get("schema_version") != 1 or contract.get("status") != "approved_for_paired_n100_characterization":
        raise ValueError("RF energy-match candidate identity is invalid")
    candidate = contract["input_candidate"]
    source_family = load(PROJECT_ROOT / contract["inputs"]["source_family"])
    distribution = load(PROJECT_ROOT / contract["inputs"]["distribution_shape"])
    transport = load(PROJECT_ROOT / contract["inputs"]["transport_mode"])
    oatof = load(PROJECT_ROOT / contract["inputs"]["oatof_formal_validation"])
    source_energy = distribution["kinetic_energy_eV"]
    source_mean = (float(source_energy["min"]) + float(source_energy["max"])) / 2
    target = float(oatof["shared_particles"]["initial_energy_mean_eV"])
    point = source_family["operating_points"].get(candidate.get("operating_point"), {})
    if candidate.get("particles") != 100 or candidate.get("mass_amu") != 100.0 or candidate.get("charge_state") != 1:
        raise ValueError("RF energy-match input identity changed")
    if point.get("kinetic_energy_eV") != {"distribution": "fixed", "value": 5.0}:
        raise ValueError("RF energy-match named operating point changed")
    if not math.isclose(float(candidate.get("kinetic_energy_eV", -1)), target, abs_tol=1e-12):
        raise ValueError("RF energy-match input no longer matches the oaTOF mean reference")
    if math.isclose(source_mean, target, abs_tol=1e-12):
        raise ValueError("RF energy-match candidate must remain separate from the official 2 eV regression")
    changes = contract["model_changes"]
    if any(changes.get(key) is not False for key in (
        "geometry_changed", "electrode_potentials_changed", "differential_rf_amplitude_changed", "collisions_enabled"
    )):
        raise ValueError("RF input-energy test must not change the RF model")
    if changes.get("velocity_rewrite_at_handoff_allowed") is not False:
        raise ValueError("RF energy matching cannot rewrite handoff velocity")
    if any(float(transport["static_electrodes_V"][key]) != 0 for key in ("entrance_plate", "exit_enclosure")):
        raise ValueError("Paired control must start from the existing zero-offset transport mode")
    paired = contract["paired_test"]
    if paired.get("particles") != 100 or paired.get("only_variable_from_the_previous_rf_input_distribution") != "named input kinetic-energy operating point":
        raise ValueError("RF energy-match paired test is incomplete")
    evidence = contract.get("n100_evidence", {})
    if evidence.get("source_phase_space_particle_wise_paired_except_energy") is not True or evidence.get("transmitted") != 100:
        raise ValueError("RF energy-match N=100 evidence is incomplete")
    if abs(float(evidence.get("mean_handoff_energy_eV", -1)) - target) > float(paired["target_mean_energy_tolerance_eV"]):
        raise ValueError("RF energy-match evidence no longer meets the target")
    downstream = contract.get("physical_port_pulse_evidence", {})
    derived_pulse = (
        1000.0 * (
            float(downstream.get("target_centroid_x_mm", math.nan))
            - float(downstream.get("release_x_mm", math.nan))
        )
        + float(downstream.get("mean_velocity_x_times_entry_time_m_s_us", math.nan))
    ) / float(downstream.get("mean_selected_velocity_x_m_s", math.nan))
    if not math.isclose(derived_pulse, float(downstream.get("derived_pulse_time_us", math.nan)), abs_tol=1e-12):
        raise ValueError("RF energy-match pulse time is not derived from the frozen timing rule")
    port = int(downstream.get("geometric_port_accepted", -1))
    predicted = int(downstream.get("predicted_finite_wall_survivors", -1))
    active = int(downstream.get("active_at_pulse", -1))
    port_loss = int(downstream.get("pre_pulse_port_losses", -1))
    accelerator_loss = int(downstream.get("pre_pulse_accelerator_losses", -1))
    local_exit = int(downstream.get("local_joint_exit", -1))
    if not (100 >= port >= active >= local_exit >= 0):
        raise ValueError("RF energy-match downstream particle funnel is inconsistent")
    if predicted != active + accelerator_loss or port_loss != port - predicted:
        raise ValueError("RF energy-match finite-wall and downstream-loss census is inconsistent")
    centroid_error = float(downstream.get("actual_centroid_error_x_mm", math.nan))
    if abs(centroid_error) > 0.1:
        raise ValueError("RF energy-match pulse does not center the active cohort")
    if downstream.get("hit_rate_gate_applied") is not False or downstream.get("compact_storage_claimed") is not False:
        raise ValueError("RF pulse timing evidence exceeds the continuous-beam slice scope")
    return contract


if __name__ == "__main__":
    validated = validate()
    print("RF_ENERGY_MATCH=PASS INPUT_ENERGY_EV=5 GEOMETRY_CHANGED=false VELOCITY_REWRITE=false")
