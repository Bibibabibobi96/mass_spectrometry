"""Validate the paired RF-to-oaTOF axial-energy matching candidate."""

from __future__ import annotations

import json
import math
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = PROJECT_ROOT / "config" / "rf_to_oatof_energy_match_candidate.json"
HYBRID_MESH_ORIGINAL_REPOSITORY_SHA256 = (
    "143917752A0DD2C41BBE1161B272D57AC47FA854521B63CB3A32BEBA1AB3FF40"
)
HYBRID_MESH_ARTIFACT_SHA256 = (
    "9D54CE5AB5456AA487F4F534BBDB372BCB1018339C70F246936122C98D57C6A8"
)
HYBRID_MESH_SOURCE_RUN_ID = (
    "20260722_193000__sim__comsol__rf-input5ev-handoff__n100__r02"
)
HYBRID_MESH_RUNTIME_AUTHORITY_PATH = (
    "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
    "config/legacy_quadrupole_n100_source_contract.json"
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_hybrid_mesh_descriptor(descriptor: dict) -> None:
    """Reject any compatibility record that could authorize current execution."""
    if (
        descriptor.get("schema_version") != 1
        or descriptor.get("role") != "rf_legacy_hybrid_mesh_compatibility_descriptor"
        or descriptor.get("status") != "compatibility_retained_read_only"
    ):
        raise ValueError("RF hybrid-mesh compatibility descriptor identity is invalid")
    for flag in (
        "current_scientific_authority",
        "active_execution_allowed",
        "generation_allowed",
        "promotion_allowed",
    ):
        if descriptor.get(flag) is not False:
            raise ValueError(f"RF hybrid-mesh compatibility descriptor must set {flag}=false")
    identity = descriptor.get("historical_identity", {})
    if (
        identity.get("original_role") != "rf_full_device_hybrid_mesh_candidate"
        or identity.get("original_status") != "approved_for_solver_validation"
        or identity.get("original_repository_path")
        != "projects/rf_quadrupole_ion_optics/config/rf_hybrid_mesh_candidate.json"
        or identity.get("pre_compaction_repository_sha256")
        != HYBRID_MESH_ORIGINAL_REPOSITORY_SHA256
    ):
        raise ValueError("RF hybrid-mesh original contract identity is invalid")
    evidence = descriptor.get("historical_evidence_pointer", {})
    if evidence.get("source_run_id") != HYBRID_MESH_SOURCE_RUN_ID:
        raise ValueError("RF hybrid-mesh source run identity is invalid")
    if evidence.get("contract_basename") != "rf_hybrid_mesh_candidate.json":
        raise ValueError("RF hybrid-mesh artifact contract basename is invalid")
    if evidence.get("artifact_contract_sha256") != HYBRID_MESH_ARTIFACT_SHA256:
        raise ValueError("RF hybrid-mesh artifact contract SHA-256 is invalid")
    runtime_authority = descriptor.get("current_runtime_authority", {})
    if (
        runtime_authority.get("repository_path")
        != HYBRID_MESH_RUNTIME_AUTHORITY_PATH
    ):
        raise ValueError("RF hybrid-mesh current runtime authority path is invalid")


def validate(path: Path = CONTRACT_PATH) -> dict:
    contract = load(path)
    if contract.get("schema_version") != 1 or contract.get("status") != "approved_for_paired_n100_characterization":
        raise ValueError("RF energy-match candidate identity is invalid")
    candidate = contract["input_candidate"]
    source_family = load(PROJECT_ROOT / contract["inputs"]["source_family"])
    distribution = load(PROJECT_ROOT / contract["inputs"]["distribution_shape"])
    transport = load(PROJECT_ROOT / contract["inputs"]["transport_mode"])
    hybrid_mesh = load(PROJECT_ROOT / contract["inputs"]["hybrid_mesh"])
    validate_hybrid_mesh_descriptor(hybrid_mesh)
    oatof = load(PROJECT_ROOT / contract["inputs"]["oatof_science_contract"])
    if oatof.get("role") != "oa_tof_formal_science_contract" or oatof.get("mode") != "formal":
        raise ValueError("OA-TOF energy target must come from its formal science contract")
    source_energy = distribution["kinetic_energy_eV"]
    source_mean = (float(source_energy["min"]) + float(source_energy["max"])) / 2
    target = float(oatof["particle"]["initial_energy_mean_ev"])
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
