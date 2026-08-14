"""Prepare one campaign-declared multipole-to-oaTOF execution."""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

from common.contracts.file_identity import file_sha256, repository_text_sha256
from common.contracts.machine_contracts import ContractError, validate_schema
from common.contracts.particle_count_policy import validate_standard_particle_count
from common.contracts.particle_physics import kinetic_energy_ev
from common.integration.adapter_contract import (
    load_execution_adapter_registry,
    resolve_execution_mapping,
)
from common.integration.resolve_connection import (
    derive_direct_mating_translation,
    load_connection_profile_registry,
    verify_composition_plan,
    write_resolved_and_plan,
)
from common.multipole.component_port import build_exit_component_port
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.resolved_region_field import (
    FULL_ID,
    build_resolved_region_field_contract,
    canonical_profile_id,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.resolved_population import (
    compile_resolved_population_contract,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_layout import (
    compile_geometry_and_port,
    derive_pulse_schedule,
    select_profile,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source import (
    materialize_ideal_linear_source,
    materialize_pre_pulse_restart,
    resolve_source_materialization_profile,
)


INTEGRATION_ID = (
    "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
)
UPSTREAM_PROJECTS = {
    "rf_quadrupole_ion_optics",
    "rf_hexapole_ion_optics",
    "rf_octupole_ion_optics",
}

def validate_full_domain_affine_width_numerics_campaign(
    campaign: dict[str, Any], single_flight: dict[str, Any], policy: dict[str, Any],
    root: Path,
) -> None:
    """Fail closed on the pending Stage-B five-cell matrix."""

    rows = [
        row for row in campaign["experiments"]
        if canonical_profile_id(
            row.get("single_flight_accelerator_field_profile_id", "accelerator_real_pa")
        ) == FULL_ID
    ]
    if not rows:
        return
    if len(rows) != len(campaign["experiments"]):
        raise ContractError("full-domain ideal rows cannot be mixed with another campaign")
    observed = {
        (
            row.get("single_flight_source_materialization_profile_id"),
            row.get("single_flight_trajectory_quality_profile_id"),
            row.get("single_flight_time_integration_profile_id"),
        )
        for row in rows
    }
    expected = {
        ("canonical_ideal_linear_z_vz_1mm_n1000", "tqual_8", "dt160"),
        ("canonical_ideal_linear_z_vz_1p5mm_n1000", "tqual_8", "dt160"),
        ("canonical_ideal_linear_z_vz_2p2mm_n1000", "tqual_8", "dt160"),
        ("canonical_ideal_linear_z_vz_2p2mm_n1000", "tqual_8", "dt320"),
        ("canonical_ideal_linear_z_vz_2p2mm_n1000", "tqual_108", "dt160"),
    }
    if len(rows) != 5 or observed != expected:
        raise ContractError("full-domain affine width/numerics matrix differs")
    registration = campaign.get("preregistration")
    release_modes = {row.get("source_release_mode") for row in rows}
    if release_modes != {"pre_pulse_restart"}:
        if campaign.get("status") != "archived_invalid":
            raise ContractError("non-restart full-domain width campaign must remain archived")
    elif campaign.get("status") == "authorized":
        if registration is None:
            raise ContractError("authorized full-domain matrix requires preregistration")
        document = registration["document"]
        document_path = (root / document["path"]).resolve()
        if (
            not document_path.is_relative_to(root)
            or not document_path.is_file()
            or document_path.stat().st_size != int(document["bytes"])
            or file_sha256(document_path) != document["sha256"]
        ):
            raise ContractError("full-domain matrix preregistration document differs")
        row_hashes = {
            row["experiment_id"]: _canonical_sha256(row) for row in rows
        }
        if registration["frozen_experiment_row_sha256"] != row_hashes:
            raise ContractError("full-domain matrix preregistered row identities differ")
    elif campaign.get("status") != "PENDING_PREREGISTRATION":
        raise ContractError("full-domain matrix registration status differs")
    source_profiles = {
        item["profile_id"]: item
        for item in single_flight["source_materialization_profiles"]
    }
    expected_widths = {
        "canonical_ideal_linear_z_vz_1mm_n1000": 1.0,
        "canonical_ideal_linear_z_vz_1p5mm_n1000": 1.5,
        "canonical_ideal_linear_z_vz_2p2mm_n1000": 2.2,
    }
    for profile_id, width in expected_widths.items():
        profile = source_profiles.get(profile_id, {})
        if (
            int(profile.get("particle_count", 0)) != 1000
            or float(profile.get("source_full_width_mm", float("nan"))) != width
            or profile.get("phase_space_authority")
            != "config/accelerator_phase_space_match.json"
            or (profile.get("mass_amu"), profile.get("charge_state"),
                profile.get("kinetic_energy_eV")) != (100.0, 1, 10.0)
        ):
            raise ContractError("full-domain affine source authority differs")
    fixed = {
        "execution_strategy": "simion_single_flight",
        "single_flight_layout_profile_id": "symmetric_10ev_source_z22_finite_interval_theory",
        "single_flight_frontend_grid_profile_id": "frontend_isotropic_020_accelerator_overlay_z005",
        "single_flight_oatof_numerical_profile_id": "oatof_formal_mesh",
        "single_flight_accelerator_field_profile_id": FULL_ID,
        "architecture_generation_id": "finite_interval_2p2mm_matched_voltage_v1",
        "field_overlay_id": "accelerator_overlay_z005",
    }
    for row in rows:
        if any(row.get(key) != value for key, value in fixed.items()):
            raise ContractError("full-domain width/numerics fixed control differs")
        if campaign["schema_version"] == 3:
            if row.get("single_flight_pulse_schedule_policy") != {
                "policy_id": "multipole_handoff_ballistic_centroid_v1",
                "offset_rf_periods": 0,
                "pulse_width_us": 1.0,
            }:
                raise ContractError("full-domain width/numerics pulse policy differs")
        elif row.get("single_flight_pulse_offset_rf_periods") != 0:
            raise ContractError("historical full-domain pulse offset differs")
        if row.get("source_profile_id") != row.get(
            "single_flight_source_materialization_profile_id"
        ):
            raise ContractError("full-domain width/numerics source identity differs")
    release_modes = {row.get("source_release_mode") for row in rows}
    if release_modes == {"continuous_frontend"}:
        if release_modes != {"continuous_frontend"} or any(
            row.get("pre_pulse_source_state") is not None for row in rows
        ):
            raise ContractError("archived continuous source path differs")
    else:
        if release_modes != {"pre_pulse_restart"}:
            raise ContractError("official full-domain source path must be pre-pulse restart")
        expected_restart_sources = {
            "canonical_ideal_linear_z_vz_1mm_n1000": (
                "22ADAC66F610064AD73E78FC9B17AB850A8FA59B3D6175EE0B5F10357FBC0539",
                "A59E16B3783DCDE7930070286C58D5BA6BA8DC0B9756DE61B410A07975672B5B",
            ),
            "canonical_ideal_linear_z_vz_1p5mm_n1000": (
                "2411F2BB62939E1CA74F627ABD567937C698848AB0E332A67784B0F2F8405624",
                "7A8FFC4D6E2A4D9B67560592B7401A72984137ACC8AE6F79388275DA494927C2",
            ),
            "canonical_ideal_linear_z_vz_2p2mm_n1000": (
                "75DF5222C32846CA16F7594404067020AEFD1CFCB2577FC8E86BF18A08493D4E",
                "7B1D722A9E73635938847EC31DEF0B45824098E1F44D4A7A1B036F6CF02392E6",
            ),
        }
        for row in rows:
            restart = row.get("pre_pulse_source_state", {})
            expected_source, expected_receipt = expected_restart_sources[
                row["single_flight_source_materialization_profile_id"]
            ]
            receipt = restart.get("materialization_receipt", {})
            if (
                restart.get("sha256") != expected_source
                or receipt.get("sha256") != expected_receipt
                or restart.get("particle_count") != 1000
                or restart.get("source_state_epoch") != "pulse_effective_time"
                or restart.get("postselection_prohibited") is not True
            ):
                raise ContractError("official full-domain restart source identity differs")
    grids = {
        item["profile_id"]: item for item in single_flight["frontend_grid_profiles"]
    }
    if int(grids[fixed["single_flight_frontend_grid_profile_id"]]["max_parallel_batches"]) != 3:
        raise ContractError(
            "full-domain width/numerics requires five batches dispatched as 3+2 waves"
        )
    if int(policy["stage_limits"]["single_flight_transport"][
        "minimum_system_available_memory_bytes"
    ]) != 4 * 1024**3:
        raise ContractError("full-domain width/numerics memory gate must be 4 GiB")


def validate_pulse_resolution_optimization_campaign(
    campaign: dict[str, Any], *, execution_requested: bool,
    experiment: dict[str, Any] | None = None,
) -> None:
    """Validate cross-field optimization semantics before any solver input is read."""
    contract = campaign.get("pulse_resolution_optimization")
    if contract is None:
        return
    arms = contract["attribution_arms"]
    if [arm["sequence"] for arm in arms] != list(range(1, 9)):
        raise ContractError("pulse-resolution attribution arms must be ordered 1 through 8")
    expected_matrix = [
        ("real_beam_all_real", "real_beam", "all_real", "real"),
        ("real_beam_ideal_stage1", "real_beam", "ideal_stage1", "real"),
        ("real_beam_ideal_stage1_stage2", "real_beam", "ideal_stage1_stage2", "real"),
        ("real_beam_all_ideal", "real_beam", "ideal_accelerator", "ideal"),
        ("finite_source_all_real", "finite_interval_2p2mm_theory_source", "all_real", "real"),
        ("finite_source_ideal_accelerator", "finite_interval_2p2mm_theory_source", "ideal_accelerator", "real"),
        ("finite_source_all_ideal", "finite_interval_2p2mm_theory_source", "ideal_accelerator", "ideal"),
        ("axial_source_all_ideal", "on_axis_longitudinal_ideal_source", "ideal_accelerator", "ideal"),
    ]
    observed_matrix = [
        (arm["arm_id"], arm["source_model"], arm["accelerator_field"], arm["reflectron_field"])
        for arm in arms
    ]
    if observed_matrix != expected_matrix:
        raise ContractError("pulse-resolution attribution matrix differs")
    if [arm["implementation_status"] for arm in arms] != (
        ["executable_registration"] + ["executable_paired_screening"] * 2
        + ["executable_paired_screening_with_full_domain_contract"]
        + ["planning_only_until_adapter_support"] * 4
    ):
        raise ContractError("pulse-resolution executable-arm status matrix differs")
    screening = contract["screening_promotion"]
    if screening["axial_ideal_closure_arm_id"] != arms[-1]["arm_id"]:
        raise ContractError("axial ideal closure stop rule must bind attribution arm 8")
    gates = contract["acceptance_gates"]
    expected_gates = {
        "full_beam": ("all_pulse_eligible_particles", 20000, 0.806),
        "theoretical_window": (
            "detector_blind_theoretical_acceptance_window", 30000, 0.537
        ),
    }
    for gate_id, expected in expected_gates.items():
        gate = gates[gate_id]
        observed = (
            gate["population_basis"], gate["mass_resolution_minimum"],
            gate["direct_fwhm_maximum_ns"],
        )
        if observed != expected:
            raise ContractError(f"pulse-resolution {gate_id} gate differs")
    prohibited = set(contract["optimization_constraints"]["derived_variables_prohibited"])
    expected_prohibited = {
        "absolute_electrode_voltages", "focus_plane", "source_center",
        "reflectron_endpoints", "ring_baseline_voltages", "shield_position",
    }
    if prohibited != expected_prohibited:
        raise ContractError("pulse-resolution derived-variable prohibition differs")
    if execution_requested:
        if experiment is None:
            raise ContractError("pulse-resolution execution requires a selected row")
        baseline_row = (
            experiment.get("pulse_resolution_attribution_arm_id")
            == "real_beam_all_real"
            and experiment.get("pulse_resolution_execution_mode")
            == "screening_prefix_n100_baseline_registration"
            and experiment.get("single_flight_accelerator_field_profile_id")
            == "accelerator_real_pa"
        )
        paired_row = (
            experiment.get("pulse_resolution_attribution_arm_id")
            == "real_beam_ideal_stage1"
            and experiment.get("pulse_resolution_execution_mode")
            == "screening_prefix_n100_paired_candidate"
            and experiment.get("single_flight_accelerator_field_profile_id")
            == "accelerator_ideal_stage1_real_stage2"
            and experiment.get("pulse_resolution_baseline_result") is not None
        )
        paired_stage12_row = (
            experiment.get("pulse_resolution_attribution_arm_id")
            == "real_beam_ideal_stage1_stage2"
            and experiment.get("pulse_resolution_execution_mode")
            == "screening_prefix_n100_paired_candidate"
            and experiment.get("single_flight_accelerator_field_profile_id")
            == "accelerator_ideal_stage1_stage2_real_reflectron"
            and experiment.get("pulse_resolution_baseline_result") is not None
        )
        paired_all_ideal_row = (
            experiment.get("pulse_resolution_attribution_arm_id") == "real_beam_all_ideal"
            and experiment.get("pulse_resolution_execution_mode")
            == "screening_prefix_n100_paired_candidate"
            and experiment.get("single_flight_accelerator_field_profile_id")
            == FULL_ID
            and experiment.get("pulse_resolution_baseline_result") is not None
        )
        if experiment.get("execution_strategy") != "simion_single_flight" or not (
            baseline_row or paired_row or paired_stage12_row or paired_all_ideal_row
        ):
            raise ContractError("pulse-resolution N=100 experiment is not executable")


SCREENING_SOURCE_COLUMNS = [
    "particle_id", "birth_time_s", "x_mm", "y_mm", "z_mm",
    "vx_m_s", "vy_m_s", "vz_m_s", "mass_amu", "charge_state",
]


def write_pulse_resolution_screening_prefix(
    source_path: Path, output_path: Path, *, mother_count: int, prefix_count: int,
) -> str:
    """Write the deterministic governed mother-sample prefix with no sampling."""
    if not 0 < prefix_count <= mother_count:
        raise ContractError("pulse-resolution prefix count is invalid")
    with source_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows, columns = list(reader), reader.fieldnames
    if columns != SCREENING_SOURCE_COLUMNS or len(rows) != mother_count:
        raise ContractError("pulse-resolution mother source is not canonical N=1000")
    if [int(row["particle_id"]) for row in rows] != list(range(1, mother_count + 1)):
        raise ContractError("pulse-resolution mother-source IDs must be contiguous")
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SCREENING_SOURCE_COLUMNS,
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows[:prefix_count])
    return file_sha256(output_path)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ContractError(f"JSON object required: {path}")
    return value


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def _repo_record(root: Path, record: dict[str, str], label: str) -> Path:
    path = (root / record["path"]).resolve()
    if (
        not path.is_relative_to(root)
        or not path.is_file()
        or repository_text_sha256(path) != record["sha256"]
    ):
        raise ContractError(f"{label} is missing, stale or escapes the repository")
    return path


def _workspace_path(workspace: Path, raw: str, label: str) -> Path:
    value = Path(raw)
    path = value.resolve() if value.is_absolute() else (workspace / value).resolve()
    artifacts = (workspace / "artifacts").resolve()
    if not path.is_relative_to(artifacts) or not path.is_file():
        raise ContractError(f"{label} is missing or escapes workspace artifacts")
    return path


def _workspace_record(
    workspace: Path, record: dict[str, str], label: str
) -> Path:
    path = _workspace_path(workspace, record["path"], label)
    if file_sha256(path) != record["sha256"]:
        raise ContractError(f"{label} SHA-256 is stale")
    return path


def _workspace_relative(path: Path, workspace: Path) -> str:
    try:
        return path.resolve().relative_to(workspace.resolve()).as_posix()
    except ValueError as exc:
        raise ContractError(f"path escapes the workspace: {path}") from exc


def _population_source_table(
    path: Path,
    *,
    workspace: Path,
    input_role: str,
    table_binding: str,
) -> dict[str, Any]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or "particle_id" not in rows[0]:
        raise ContractError("population source table lacks particle identities")
    try:
        particle_ids = [int(row["particle_id"]) for row in rows]
    except (TypeError, ValueError) as exc:
        raise ContractError("population source particle identities are invalid") from exc
    if len(particle_ids) != len(set(particle_ids)):
        raise ContractError("population source particle identities are not unique")
    return {
        "input_role": input_role,
        "table_binding": table_binding,
        "table": {
            "path": _workspace_relative(path, workspace),
            "sha256": file_sha256(path),
        },
        "particle_count": len(particle_ids),
        "ordered_particle_ids": {
            "encoding": "canonical_compact_json_integer_array_v1",
            "sha256": _canonical_sha256(particle_ids),
        },
    }


def _validate_canonical_pulse_restart_state(
    source_path: Path,
    receipt_path: Path,
    source_record: dict[str, Any],
    profile: dict[str, Any],
    geometry: dict[str, Any],
    schedule: dict[str, Any],
) -> dict[str, Any]:
    receipt = _load(receipt_path)
    target = receipt.get("pulse_target_state", {})
    expected_locus = "accelerator_stage1_interior_fixed_transverse_finite_local_z_interval"
    if (
        receipt.get("profile_id") != profile["profile_id"]
        or target.get("sha256") != source_record["sha256"]
        or target.get("particle_count") != source_record["particle_count"]
        or target.get("source_state_epoch") != "pulse_effective_time"
        or target.get("source_state_locus", {}).get("kind") != expected_locus
        or target.get("coordinate_frame") != "oatof_global_cartesian"
        or target.get("clock_basis") != "canonical_instrument_time_us"
        or target.get("clock_authority") != "resolved_single_flight_pulse_schedule"
    ):
        raise ContractError("canonical pulse restart receipt identity differs")
    pulse_time_us = float(schedule["pulse_effective_time_us"])
    _, normalized_rows = materialize_pre_pulse_restart(source_path, pulse_time_us)
    count = int(profile["particle_count"])
    if len(normalized_rows) != count:
        raise ContractError("canonical pulse restart population differs")
    ordered_ids = [int(row["particle_id"]) for row in normalized_rows]
    ordered_id_sha256 = _canonical_sha256(ordered_ids)
    if target.get("ordered_particle_id_sha256") != ordered_id_sha256:
        raise ContractError("canonical pulse restart ordered particle identity differs")
    particle_source = geometry["particle_source"]
    center_x = float(particle_source["center_x_mm"])
    center_y = float(particle_source["center_y_mm"])
    center_z = float(particle_source["center_z_mm"])
    width = float(profile["source_full_width_mm"])
    mean_vz = float(profile["mean_velocity_z_m_per_s"])
    slope = float(profile["velocity_z_slope_m_per_s_per_mm"])
    position_tolerance = float(source_record["position_rowwise_abs_tolerance_mm"])
    velocity_tolerance = float(source_record["velocity_rowwise_abs_tolerance_m_per_s"])
    maximum_position_error = 0.0
    maximum_velocity_error = 0.0
    maximum_clock_error = 0.0
    maximum_energy_error = 0.0
    for index, row in enumerate(normalized_rows):
        expected_z = (
            center_z
            if count == 1
            else center_z - width / 2.0 + width * index / (count - 1)
        )
        expected_vz = mean_vz + slope * (expected_z - center_z)
        maximum_position_error = max(
            maximum_position_error,
            abs(float(row["position_x_mm"]) - center_x),
            abs(float(row["position_y_mm"]) - center_y),
            abs(float(row["position_z_mm"]) - expected_z),
        )
        maximum_velocity_error = max(
            maximum_velocity_error,
            abs(float(row["velocity_z_m_s"]) - expected_vz),
        )
        maximum_clock_error = max(
            maximum_clock_error,
            abs(float(row["instrument_time_us"]) - pulse_time_us),
        )
        maximum_energy_error = max(
            maximum_energy_error,
            abs(
                kinetic_energy_ev(
                    float(row["mass_amu"]),
                    *(float(row[f"velocity_{axis}_m_s"]) for axis in "xyz"),
                ) - float(row["kinetic_energy_eV"])
            ),
        )
    if (
        maximum_position_error > position_tolerance
        or maximum_velocity_error > velocity_tolerance
        or maximum_clock_error > float(source_record["clock_abs_tolerance_us"])
        or maximum_energy_error > float(source_record["energy_abs_tolerance_eV"])
    ):
        raise ContractError("canonical pulse restart target-state validation failed")
    return {
        "schema_version": 1,
        "role": "canonical_pulse_restart_target_state_validation",
        "status": "PASS",
        "target_pulse_state_sha256": source_record["sha256"],
        "materialization_receipt_sha256": source_record["materialization_receipt"]["sha256"],
        "source_state_epoch": "pulse_effective_time",
        "source_state_locus": expected_locus,
        "coordinate_frame": "oatof_global_cartesian",
        "clock_basis": "canonical_instrument_time_us",
        "clock_authority": "resolved_single_flight_pulse_schedule",
        "ordered_particle_id_sha256": ordered_id_sha256,
        "particle_count": count,
        "tolerances": {
            "position_rowwise_abs_tolerance_mm": position_tolerance,
            "velocity_rowwise_abs_tolerance_m_per_s": velocity_tolerance,
            "clock_abs_tolerance_us": float(source_record["clock_abs_tolerance_us"]),
            "energy_abs_tolerance_eV": float(source_record["energy_abs_tolerance_eV"]),
        },
        "maximum_errors": {
            "position_rowwise_abs_mm": maximum_position_error,
            "velocity_rowwise_abs_m_per_s": maximum_velocity_error,
            "clock_abs_us": maximum_clock_error,
            "energy_abs_eV": maximum_energy_error,
        },
    }


def _unique_profile(document: dict[str, Any], profile_id: str) -> dict[str, Any]:
    matches = [
        item
        for item in document["profiles"]
        if item["connection_profile_id"] == profile_id
    ]
    if len(matches) != 1:
        raise ContractError(f"connection profile is not unique: {profile_id}")
    return matches[0]


def _source_solver(manifest: dict[str, Any]) -> str:
    software = " ".join(str(item).lower() for item in manifest.get("software", []))
    matches = [name for name in ("comsol", "simion") if name in software]
    if len(matches) != 1:
        raise ContractError("source manifest solver identity is not unique")
    return matches[0]


def _verify_manifest_record(
    workspace: Path,
    record: dict[str, Any],
    expected_path: Path,
    expected_sha256: str,
    label: str,
) -> None:
    if not record.get("exists"):
        raise ContractError(f"source manifest {label} record is absent")
    path = _workspace_path(workspace, str(record["path"]), label)
    if path != expected_path.resolve() or record["sha256"] != expected_sha256:
        raise ContractError(f"source manifest {label} identity differs")


def _load_source_evidence(
    *,
    workspace: Path,
    experiment: dict[str, Any],
    expected_project_id: str,
) -> dict[str, Any]:
    source = experiment["source"]
    launched_count = validate_standard_particle_count(
        int(source["launched_particle_count"])
    )
    selected_count = int(source["particle_count"])
    if selected_count > launched_count:
        raise ContractError("selected source particle count exceeds launched count")
    manifest_path = _workspace_record(workspace, source["manifest"], "source manifest")
    state_path = _workspace_record(workspace, source["state"], "source state")
    particle_source_path = _workspace_record(
        workspace, source["particle_source"], "source particle table"
    )
    metadata_path = _workspace_record(workspace, source["metadata"], "source metadata")
    manifest = _load(manifest_path)
    if (
        manifest.get("role") != "simulation_run_manifest"
        or manifest.get("status") != "success"
        or manifest.get("run_id") != source["run_id"]
        or manifest.get("project") != expected_project_id
        or expected_project_id not in UPSTREAM_PROJECTS
    ):
        raise ContractError("source manifest run/project/status identity differs")
    source_role = source["particle_source_manifest_input_role"]
    _verify_manifest_record(
        workspace,
        manifest.get("inputs", {}).get(source_role, {}),
        particle_source_path,
        source["particle_source"]["sha256"],
        "particle source",
    )
    _verify_manifest_record(
        workspace,
        manifest.get("inputs", {}).get("particle_source_metadata", {}),
        metadata_path,
        source["metadata"]["sha256"],
        "particle source metadata",
    )
    matching_states = [
        record
        for record in manifest.get("outputs", [])
        if record.get("sha256") == source["state"]["sha256"]
    ]
    if len(matching_states) != 1:
        raise ContractError("source state is not uniquely frozen by its manifest")
    _verify_manifest_record(
        workspace,
        matching_states[0],
        state_path,
        source["state"]["sha256"],
        "source state",
    )
    design_record = manifest.get("inputs", {}).get("multipole_resolved_design", {})
    design_path = _workspace_path(
        workspace, str(design_record.get("path", "")), "source resolved design"
    )
    if (
        not design_record.get("exists")
        or file_sha256(design_path) != design_record.get("sha256")
    ):
        raise ContractError("source resolved design is absent or stale")
    resolved_design = _load(design_path)
    validate_schema(resolved_design, "multipole_resolved_design.schema.json")
    run_config_record = manifest.get("run_config", {})
    run_config_path = _workspace_path(
        workspace, str(run_config_record.get("path", "")), "source run config"
    )
    if (
        not run_config_record.get("exists")
        or file_sha256(run_config_path) != run_config_record.get("sha256")
    ):
        raise ContractError("source run config is absent or stale")
    run_config = _load(run_config_path)
    design_profile_id = run_config.get("parameters", {}).get("design_profile_id")
    if (
        not isinstance(design_profile_id, str)
        or not design_profile_id
        or resolved_design["identity"]["project_id"] != expected_project_id
    ):
        raise ContractError("source design profile/project identity differs")
    terminal = resolved_design.get("downstream_terminal")
    if (
        not isinstance(terminal, dict)
        or terminal.get("terminal_profile_id") != "oatof_shield_terminal"
        or terminal.get("surface_role") != "aperture_outer_tangent_plane"
        or float(terminal.get("rod_end_clearance_mm", -1.0)) != 1.0
        or terminal.get("upstream_terminal_electrode_present") is not False
    ):
        raise ContractError("source design does not freeze the governed oaTOF terminal")
    return {
        "source": source,
        "manifest": manifest,
        "state_path": state_path,
        "solver_id": _source_solver(manifest),
        "resolved_design": resolved_design,
        "resolved_design_path": design_path,
        "resolved_design_sha256": design_record["sha256"],
        "design_profile_id": design_profile_id,
        "launched_particle_count": launched_count,
        "particle_count": selected_count,
    }


def prepare_family_source_closure(
    *,
    repo_root: Path,
    profile_registry_path: Path,
    adapter_registry_path: Path,
    campaign_path: Path,
    experiment_id: str,
    resolved_output: Path,
    plan_output: Path,
) -> tuple[Path, Path]:
    root = repo_root.resolve()
    workspace = root.parent
    campaign_path = campaign_path.resolve()
    if not campaign_path.is_relative_to(root):
        raise ContractError("integration campaign must be repository-managed")
    campaign = _load(campaign_path)
    validate_schema(campaign, "rf_multipole_oatof_experiment_campaign.schema.json")
    if campaign["integration_id"] != INTEGRATION_ID:
        raise ContractError("campaign integration identity differs")
    identities = [item["experiment_id"] for item in campaign["experiments"]]
    sequences = [item["sequence"] for item in campaign["experiments"]]
    if len(identities) != len(set(identities)) or len(sequences) != len(set(sequences)):
        raise ContractError("campaign experiment IDs and sequences must be unique")
    matches = [item for item in campaign["experiments"] if item["experiment_id"] == experiment_id]
    if len(matches) != 1:
        raise ContractError("campaign experiment must resolve exactly once")
    experiment = matches[0]
    validate_pulse_resolution_optimization_campaign(
        campaign, execution_requested=True, experiment=experiment
    )
    execution_strategy = experiment.get("execution_strategy", "staged_three_stage")
    pulse_schedule_policy = experiment.get("single_flight_pulse_schedule_policy")
    population_declaration = experiment.get("single_flight_population")
    if execution_strategy == "simion_single_flight" and campaign["schema_version"] < 3:
        raise ContractError(
            "SolverAuthorized single-flight execution requires a schema-v3 successor campaign"
        )
    if execution_strategy == "simion_single_flight" and (
        pulse_schedule_policy is None or population_declaration is None
    ):
        raise ContractError("schema-v3 single flight requires resolved clock and population inputs")
    frontend_grid_profile_id = experiment.get(
        "single_flight_frontend_grid_profile_id"
    )
    single_flight_configuration = _load(
        root / "integrations" / INTEGRATION_ID / "config" /
        "simion_single_flight.json"
    )
    source_materialization_profile_id = experiment.get(
        "single_flight_source_materialization_profile_id"
    )
    source_materialization_profile = None
    if source_materialization_profile_id is not None:
        if execution_strategy != "simion_single_flight":
            raise ContractError(
                "source materialization profiles require SIMION single flight"
            )
        matches = [
            item
            for item in single_flight_configuration["source_materialization_profiles"]
            if item["profile_id"] == source_materialization_profile_id
        ]
        if len(matches) != 1:
            raise ContractError(
                "single-flight source materialization profile must resolve exactly once"
            )
        try:
            source_materialization_profile = resolve_source_materialization_profile(
                matches[0], root / "integrations" / INTEGRATION_ID,
            )
        except (KeyError, OSError, TypeError, ValueError) as exc:
            raise ContractError("source phase-space authority is invalid") from exc
    if frontend_grid_profile_id is not None:
        if execution_strategy != "simion_single_flight":
            raise ContractError(
                "single-flight frontend grid profiles require SIMION single flight"
            )
        grid_profiles = [
            item for item in single_flight_configuration["frontend_grid_profiles"]
            if item["profile_id"] == frontend_grid_profile_id
        ]
        if len(grid_profiles) != 1:
            raise ContractError(
                "single-flight frontend grid profile must resolve exactly once"
            )
    oatof_numerical_profile_id = experiment.get(
        "single_flight_oatof_numerical_profile_id"
    )
    oatof_numerical_profile = None
    if oatof_numerical_profile_id is not None:
        if execution_strategy != "simion_single_flight":
            raise ContractError("oaTOF numerical profiles require SIMION single flight")
        matches = [
            item for item in single_flight_configuration["oatof_numerical_profiles"]
            if item["profile_id"] == oatof_numerical_profile_id
        ]
        if len(matches) != 1:
            raise ContractError("oaTOF numerical profile must resolve exactly once")
        oatof_numerical_profile = matches[0]
    trajectory_quality_profile_id = experiment.get(
        "single_flight_trajectory_quality_profile_id"
    )
    if trajectory_quality_profile_id is not None:
        matches = [
            item for item in single_flight_configuration["trajectory_quality_profiles"]
            if item["profile_id"] == trajectory_quality_profile_id
        ]
        if len(matches) != 1:
            raise ContractError("trajectory-quality profile must resolve exactly once")
    time_integration_profile_id = experiment.get(
        "single_flight_time_integration_profile_id"
    )
    if time_integration_profile_id is not None:
        matches = [
            item for item in single_flight_configuration["time_integration_profiles"]
            if item["profile_id"] == time_integration_profile_id
        ]
        if len(matches) != 1:
            raise ContractError("time-integration profile must resolve exactly once")
    spatial_window_profile_id = experiment.get(
        "single_flight_spatial_window_profile_id"
    )
    if spatial_window_profile_id is not None:
        if execution_strategy != "simion_single_flight":
            raise ContractError("spatial-window profiles require SIMION single flight")
        matches = [
            item for item in single_flight_configuration["spatial_window_profiles"]
            if item["profile_id"] == spatial_window_profile_id
        ]
        if len(matches) != 1:
            raise ContractError("spatial-window profile must resolve exactly once")
    accelerator_field_profile_id = (
        canonical_profile_id(experiment.get(
            "single_flight_accelerator_field_profile_id",
            single_flight_configuration["default_accelerator_field_profile_id"],
        ))
        if execution_strategy == "simion_single_flight"
        else None
    )
    if accelerator_field_profile_id is not None:
        if execution_strategy != "simion_single_flight":
            raise ContractError(
                "single-flight accelerator field profiles require SIMION single flight"
            )
        field_profiles = [
            item for item in single_flight_configuration["accelerator_field_profiles"]
            if canonical_profile_id(item["profile_id"]) == accelerator_field_profile_id
        ]
        if len(field_profiles) != 1:
            raise ContractError(
                "single-flight accelerator field profile must resolve exactly once"
            )
    source_release_mode = experiment.get("source_release_mode")
    architecture_generation_id = experiment.get("architecture_generation_id")
    source_profile_id = experiment.get("source_profile_id")
    field_overlay_id = experiment.get("field_overlay_id")
    pre_pulse_source_state = experiment.get("pre_pulse_source_state")
    identity_values = (
        architecture_generation_id, source_profile_id, field_overlay_id,
    )
    if any(value is not None for value in identity_values) and not all(
        isinstance(value, str) and value for value in identity_values
    ):
        raise ContractError("single-flight architecture/source/field identity is incomplete")
    if execution_strategy == "simion_single_flight" and not (
        isinstance(source_release_mode, str) and source_release_mode
    ):
        raise ContractError("single-flight source release identity is incomplete")
    if (
        source_materialization_profile is not None
        and source_materialization_profile["source_profile_id"] != source_profile_id
    ):
        raise ContractError("source materialization and campaign source identities differ")
    if (
        field_overlay_id is not None
        and frontend_grid_profile_id is not None
        and grid_profiles[0].get("field_overlay_id") != field_overlay_id
    ):
        raise ContractError("frontend grid field-overlay identity differs")
    pre_pulse_source_path = None
    pre_pulse_receipt_path = None
    if source_release_mode == "pre_pulse_restart":
        if execution_strategy != "simion_single_flight" or pre_pulse_source_state is None:
            raise ContractError("pre-pulse restart requires a governed source-state record")
        pre_pulse_source_path = _workspace_record(
            workspace, pre_pulse_source_state, "pre-pulse source state"
        )
        if source_materialization_profile is not None:
            required_restart_fields = {
                "materialization_receipt", "source_state_epoch", "source_state_locus",
                "position_rowwise_abs_tolerance_mm",
                "velocity_rowwise_abs_tolerance_m_per_s", "clock_abs_tolerance_us",
                "energy_abs_tolerance_eV", "postselection_prohibited",
            }
            if not required_restart_fields.issubset(pre_pulse_source_state):
                raise ContractError("canonical pulse restart validation contract is incomplete")
            pre_pulse_receipt_path = _workspace_record(
                workspace,
                pre_pulse_source_state["materialization_receipt"],
                "pre-pulse source materialization receipt",
            )
    elif pre_pulse_source_state is not None:
        raise ContractError("pre-pulse source state requires pre-pulse restart mode")
    profile_registry = load_connection_profile_registry(profile_registry_path)
    profile = _unique_profile(profile_registry, experiment["connection_profile_id"])
    expected_project_id = profile["upstream"]["project_id"]

    adapter_registry = load_execution_adapter_registry(adapter_registry_path)
    mapping = resolve_execution_mapping(
        adapter_registry, experiment["connection_profile_id"], repo_root=root
    )
    runtime_binding_record = {
        "path": mapping["runtime_binding_path"],
        "sha256": mapping["runtime_binding_sha256"],
    }
    runtime_binding_path = _repo_record(
        root, runtime_binding_record, "family runtime binding"
    )
    runtime_binding = _load(runtime_binding_path)
    validate_schema(runtime_binding, "rf_multipole_oatof_runtime_binding.schema.json")
    if (
        runtime_binding["schema_version"] != 3
        or runtime_binding["connection_profile_id"]
        != experiment["connection_profile_id"]
        or runtime_binding["upstream_project_id"] != expected_project_id
    ):
        raise ContractError("active family runtime binding identity differs")
    source_adapter_record = runtime_binding["contracts"]["source_adapter_contract"]
    source_adapter_path = _repo_record(
        root, source_adapter_record, "family source adapter"
    )
    source_adapter = _load(source_adapter_path)
    validate_schema(source_adapter, "rf_multipole_oatof_source_adapter.schema.json")
    policy_record = runtime_binding["contracts"]["execution_policy_contract"]
    if policy_record != campaign["execution_policy"]:
        raise ContractError("campaign and runtime execution policies differ")
    policy_path = _repo_record(root, policy_record, "integration execution policy")
    policy = _load(policy_path)
    validate_schema(policy, "rf_multipole_oatof_execution_policy.schema.json")
    validate_full_domain_affine_width_numerics_campaign(
        campaign, single_flight_configuration, policy, root
    )

    evidence = _load_source_evidence(
        workspace=workspace,
        experiment=experiment,
        expected_project_id=expected_project_id,
    )
    source = evidence["source"]
    pulse_contract = campaign.get("pulse_resolution_optimization")
    pulse_prefix_path = None
    pulse_prefix_sha256 = None
    if pulse_contract is not None:
        pulse_prefix_path = plan_output.parent / "inputs" / (
            "pulse_resolution_arm1_all_real_screening_prefix_n100.csv"
        )
        pulse_prefix_path.parent.mkdir(parents=True, exist_ok=True)
        pulse_prefix_sha256 = write_pulse_resolution_screening_prefix(
            _workspace_record(workspace, source["particle_source"],
                              "pulse-resolution mother source"),
            pulse_prefix_path,
            mother_count=int(pulse_contract["population_contract"]["mother_sample_count"]),
            prefix_count=int(pulse_contract["population_contract"]["screening_prefix_count"]),
        )
    single_flight_source = experiment.get("single_flight_particle_source")
    single_flight_source_path = None
    selection_receipt = None
    if single_flight_source is not None:
        if execution_strategy != "simion_single_flight":
            raise ContractError("single-flight particle-source overrides require SIMION single flight")
        single_flight_source_path = _repo_record(
            root, single_flight_source, "single-flight particle source"
        )
        with single_flight_source_path.open(encoding="utf-8-sig", newline="") as handle:
            source_rows = list(csv.DictReader(handle))
        expected_columns = [
            "particle_id", "birth_time_s", "x_mm", "y_mm", "z_mm",
            "vx_m_s", "vy_m_s", "vz_m_s", "mass_amu", "charge_state",
        ]
        if not source_rows or list(source_rows[0]) != expected_columns:
            raise ContractError("single-flight particle source columns differ")
        if len(source_rows) != int(single_flight_source["particle_count"]):
            raise ContractError("single-flight particle source count differs")
        if [int(row["particle_id"]) for row in source_rows] != list(range(1, len(source_rows) + 1)):
            raise ContractError("single-flight particle source IDs must be contiguous")
        if single_flight_source["sampling_mode"] == "pulse_eligible_conditional":
            receipt = single_flight_source.get("selection_receipt")
            if receipt is None:
                raise ContractError("conditional source requires a selection receipt")
            receipt_path = _repo_record(
                root, receipt, "single-flight selection receipt"
            )
            selection_receipt = _load(receipt_path)
            if (
                selection_receipt.get("selected_count") != len(source_rows)
                or selection_receipt.get("candidate_eligible_count", 0) < len(source_rows)
                or selection_receipt.get("candidate_launched_count", 0)
                < selection_receipt.get("candidate_eligible_count", 0)
            ):
                raise ContractError("conditional-source receipt population differs")
    solver_id = evidence["solver_id"]
    if execution_strategy == "simion_single_flight" and solver_id != "simion":
        raise ContractError("SIMION single-flight execution requires a SIMION source run")
    design_evidence = evidence
    design_reference = experiment.get("single_flight_design_reference")
    if design_reference is not None:
        if execution_strategy != "simion_single_flight":
            raise ContractError("design references are only valid for SIMION single flight")
        design_evidence = _load_source_evidence(
            workspace=workspace,
            experiment={"source": design_reference},
            expected_project_id=expected_project_id,
        )
        if design_evidence["solver_id"] != "simion":
            raise ContractError("single-flight design reference requires a SIMION run")
    handoff_publication_record = source.get(
        "handoff_publication_contract",
        runtime_binding["contracts"]["handoff_publication_contract"],
    )
    handoff_publication_path = _repo_record(
        root, handoff_publication_record, "handoff publication contract"
    )
    handoff_publication = _load(handoff_publication_path)
    if (
        handoff_publication.get("schema_version") != 1
        or handoff_publication.get("role")
        != "multipole_handoff_publication_contract"
        or handoff_publication.get("population", {}).get(
            "expected_source_particle_count"
        )
        != source["launched_particle_count"]
        or handoff_publication.get("canonical_state", {}).get(
            "source_component_id"
        )
        != expected_project_id
    ):
        raise ContractError(
            "handoff publication contract differs from the selected source population"
        )
    adapter = copy.deepcopy(source_adapter["adapter"])
    adapter["dependencies"] = {
        "handoff_publication_contract": handoff_publication_record
    }
    resolved_source = copy.deepcopy(source)
    resolved_source.pop("handoff_publication_contract", None)
    resolved_source_contract = {
        "schema_version": 2,
        "role": "rf_multipole_oatof_source_contract",
        "upstream_project_id": expected_project_id,
        "selector": copy.deepcopy(source_adapter["selector"]),
        "adapter": adapter,
        "canonical_state": copy.deepcopy(source_adapter["canonical_state"]),
        "source_branches": {
            solver_id: {
                "solver_id": solver_id,
                "recorded_project_id": expected_project_id,
                "source": resolved_source,
            }
        },
    }
    if design_reference is not None:
        resolved_source_contract["design_reference"] = {
            "run_id": design_reference["run_id"],
            "manifest": copy.deepcopy(design_reference["manifest"]),
        }
    validate_schema(
        resolved_source_contract, "rf_multipole_oatof_source_contract.schema.json"
    )
    plan_output.parent.mkdir(parents=True, exist_ok=True)
    resolved_source_contract_path = plan_output.with_name(
        "resolved_source_contract.json"
    )
    resolved_source_contract_path.write_text(
        json.dumps(resolved_source_contract, indent=2) + "\n", encoding="utf-8"
    )

    upstream_resolved_design_path = plan_output.with_name(
        "upstream_resolved_design.json"
    )
    shutil.copyfile(design_evidence["resolved_design_path"], upstream_resolved_design_path)
    if file_sha256(upstream_resolved_design_path) != design_evidence["resolved_design_sha256"]:
        raise ContractError("frozen upstream resolved design identity differs")

    upstream_port = build_exit_component_port(
        design_evidence["resolved_design"],
        design_profile_id=design_evidence["design_profile_id"],
        authority_path=_workspace_relative(upstream_resolved_design_path, workspace),
        authority_sha256=design_evidence["resolved_design_sha256"],
    )
    upstream_port_path = plan_output.with_name("resolved_upstream_port.json")
    upstream_port_path.write_text(
        json.dumps(upstream_port, indent=2) + "\n", encoding="utf-8"
    )
    resolved_registry = {
        "schema_version": profile_registry["schema_version"],
        "role": profile_registry["role"],
        "integration_id": profile_registry["integration_id"],
        "profiles": [copy.deepcopy(profile)],
    }
    resolved_upstream = resolved_registry["profiles"][0]["upstream"]
    if resolved_upstream.pop("port_binding", None) != "source_run_resolved_design":
        raise ContractError("upstream port is not runtime-bound to source design")
    resolved_upstream["port_contract"] = _workspace_relative(
        upstream_port_path, workspace
    )
    layout_files: dict[str, Path] | None = None
    resolved_region_field_contract_path: Path | None = None
    resolved_region_field_contract: dict[str, Any] | None = None
    if campaign["schema_version"] == 3:
        if execution_strategy != "simion_single_flight":
            raise ContractError("single-flight layout profiles require SIMION single flight")
        layout_registry_path = (
            root / "integrations" / INTEGRATION_ID / "config" /
            "single_flight_layout_profiles.json"
        )
        layout_profile = select_profile(
            _load(layout_registry_path), experiment["single_flight_layout_profile_id"]
        )
        if (
            architecture_generation_id is not None
            and layout_profile["architecture_generation_id"]
            != architecture_generation_id
        ):
            raise ContractError("layout profile architecture generation differs")
        experiment_overrides = experiment.get("single_flight_design_overrides", [])
        if experiment_overrides:
            inherited = list(layout_profile.get("design_overrides", []))
            variables = [item["variable"] for item in inherited + experiment_overrides]
            if len(variables) != len(set(variables)):
                raise ContractError("single-flight design override variable is duplicated")
            layout_profile["design_overrides"] = inherited + copy.deepcopy(
                experiment_overrides
            )
        base_geometry_path = (
            root / "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json"
        )
        base_downstream_port_path = (root / profile["downstream"]["port_contract"]).resolve()
        geometry, downstream_port, _ = compile_geometry_and_port(
            _load(base_geometry_path), _load(base_downstream_port_path), layout_profile
        )
        if oatof_numerical_profile is not None:
            reflectron_mesh = oatof_numerical_profile["reflectron_cell_mm"]
            geometry["simion_geometry_build"]["reflectron"]["cell_axial_mm"] = float(
                reflectron_mesh["axial"]
            )
            geometry["simion_geometry_build"]["reflectron"]["cell_radial_mm"] = float(
                reflectron_mesh["radial"]
            )
        geometry_path = plan_output.with_name("resolved_oatof_geometry.json")
        geometry_path.write_text(json.dumps(geometry, indent=2) + "\n", encoding="utf-8")
        resolved_region_field_contract_path = (
            plan_output.parent / "inputs" / "resolved_region_field_contract.json"
        )
        try:
            resolved_region_field_contract = build_resolved_region_field_contract(
                geometry_path,
                resolved_region_field_contract_path,
                accelerator_field_profile_id or "accelerator_real_pa",
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError("resolved region field contract is invalid") from exc
        downstream_port["authority"]["source_contract"] = _workspace_relative(
            geometry_path, workspace
        )
        downstream_port["authority"]["source_sha256"] = file_sha256(geometry_path)
        downstream_port_path = plan_output.with_name("resolved_downstream_port.json")
        downstream_port_path.write_text(
            json.dumps(downstream_port, indent=2) + "\n", encoding="utf-8"
        )
        validate_schema(downstream_port, "component_port.schema.json")
        resolved_registry["profiles"][0]["downstream"]["port_contract"] = (
            _workspace_relative(downstream_port_path, workspace)
        )
        registration = resolved_registry["profiles"][0]["spatial_registration"]
        registration["translation_mm"] = derive_direct_mating_translation(
            registration["rotation_upstream_to_downstream"],
            upstream_port["mating_surface"]["center_mm"],
            downstream_port["mating_surface"]["center_mm"],
        )
        layout_files = {
            "registry": layout_registry_path,
            "geometry": geometry_path,
            "downstream_port": downstream_port_path,
        }
    resolved_registry_path = plan_output.with_name(
        "resolved_connection_profile_registry.json"
    )
    resolved_registry_path.write_text(
        json.dumps(resolved_registry, indent=2) + "\n", encoding="utf-8"
    )

    source_identity = {
        "source_branch_id": solver_id,
        "solver_id": solver_id,
        "run_id": source["run_id"],
        "project_id": expected_project_id,
        "manifest_sha256": source["manifest"]["sha256"],
        "event_sha256": source["state"]["sha256"],
        "particle_source_sha256": source["particle_source"]["sha256"],
        "metadata_sha256": source["metadata"]["sha256"],
    }
    row_sha256 = _canonical_sha256(experiment)
    registration_receipt_path = None
    registration_receipt_sha256 = None
    if pulse_contract is not None:
        with pulse_prefix_path.open(encoding="utf-8", newline="") as handle:
            prefix_ids = [int(row["particle_id"]) for row in csv.DictReader(handle)]
        if prefix_ids != list(range(1, 101)):
            raise ContractError("pulse-resolution frozen prefix IDs differ")
        paired_candidate = experiment["pulse_resolution_execution_mode"] == (
            "screening_prefix_n100_paired_candidate"
        )
        if paired_candidate:
            baseline_record = experiment["pulse_resolution_baseline_result"]
            baseline_path = _workspace_record(
                workspace, baseline_record, "pulse-resolution baseline result"
            )
            baseline = _load(baseline_path)
            if (
                baseline.get("role") != "rf_oatof_pulse_resolution_baseline_result"
                or baseline.get("experiment_id") != "pulse_resolution_baseline"
                or baseline.get("arm", {}).get("arm_id") != "real_beam_all_real"
                or baseline.get("prefix", {}).get("ordered_particle_ids") != prefix_ids
            ):
                raise ContractError("paired screening baseline result identity differs")
            registration_receipt_path = plan_output.parent / "inputs" / (
                "pulse_resolution_baseline_result_reference.json"
            )
            shutil.copy2(baseline_path, registration_receipt_path)
            registration_receipt_sha256 = file_sha256(registration_receipt_path)
        else:
            registration_receipt = {
            "schema_version": 1,
            "role": "rf_oatof_pulse_resolution_baseline_registration_authority",
            "campaign_id": campaign["campaign_id"],
            "campaign_sha256": repository_text_sha256(campaign_path),
            "experiment_id": experiment_id,
            "experiment_row_sha256": row_sha256,
            "physical_arm": {
                "arm_id": "real_beam_all_real",
                "description": (
                    "real multipole beam + real accelerator field + real reflectron "
                    "field, deterministic N=100 prefix baseline registration"
                ),
            },
            "mother_sample": {
                "run_id": source["run_id"],
                "manifest": source["manifest"],
                "particle_source": source["particle_source"],
                "particle_count": 1000,
            },
            "prefix": {
                "path": "inputs/" + pulse_prefix_path.name,
                "sha256": pulse_prefix_sha256,
                "count": 100,
                "selection_algorithm": "first_100_rows_in_frozen_file_order",
                "selection_seed": None,
                "ordered_particle_ids": prefix_ids,
                "particle_id_sha256_ordered": _canonical_sha256(prefix_ids).lower(),
            },
            "analysis_bootstrap_seed": int(pulse_contract["bootstrap"]["seed"]),
            "execution_status": "baseline_registered_not_candidate",
            "solver_execution_performed": False,
            "promotion_gate_invoked": False,
            "promotion_status": "not_evaluated",
            "formal_gate_passed": False,
        }
            registration_receipt["receipt_sha256"] = _canonical_sha256(
                registration_receipt
            ).lower()
            registration_receipt_path = plan_output.parent / "inputs" / (
                "pulse_resolution_real_beam_real_accelerator_real_reflectron_"
                "n100_baseline_registration_authority.json"
            )
            registration_receipt_path.write_text(
                json.dumps(registration_receipt, indent=2) + "\n", encoding="utf-8"
            )
            registration_receipt_sha256 = file_sha256(registration_receipt_path)
    execution_particle_count = (
        int(population_declaration["execution_population"]["particle_count"])
        if execution_strategy == "simion_single_flight"
        else evidence["particle_count"]
    )
    resolved_budget = {
        "schema_version": 1,
        "role": "integration_resolved_engineering_budget",
        "integration_id": INTEGRATION_ID,
        "connection_profile_id": experiment["connection_profile_id"],
        "campaign_id": campaign["campaign_id"],
        "experiment_id": experiment_id,
        "experiment_row_sha256": row_sha256,
        "execution_strategy": execution_strategy,
        "policy_id": policy["policy_id"],
        "source_identity": source_identity,
        "launched_particle_count": execution_particle_count,
        "particle_count": execution_particle_count,
        "retention_class": policy["retention_class"],
        "stage_limits": policy["stage_limits"],
        "budget_exhaustion_result": policy["budget_exhaustion_result"],
    }
    if frontend_grid_profile_id is not None and grid_profiles[0].get(
        "accelerator_overlay"
    ):
        estimate = grid_profiles[0]["accelerator_overlay"].get(
            "transient_disk_estimate"
        )
        if estimate is not None:
            dimensions = estimate["overlay_grid_dimensions"]
            grid_points = (
                int(dimensions["nx"])
                * int(dimensions["ny"])
                * int(dimensions["nz"])
            )
            pa_family_bytes = (
                grid_points
                * int(estimate["bytes_per_grid_point"])
                * int(estimate["overlay_pa_family_file_count"])
            )
            transient_bytes = round(
                (
                    pa_family_bytes
                    + int(estimate["coarse_frontend_and_iob_bytes"])
                )
                * float(estimate["headroom_factor"])
            )
            resolved_budget["stage_limits"]["single_flight_transport"][
                "transient_run_directory_bytes"
            ] = max(
                transient_bytes,
                int(
                    resolved_budget["stage_limits"]["single_flight_transport"][
                        "transient_run_directory_bytes"
                    ]
                ),
            )
            resolved_budget["transient_disk_estimate"] = {
                "profile_id": frontend_grid_profile_id,
                "formula": "ceil((grid_points*bytes_per_grid_point*pa_family_file_count+coarse_frontend_and_iob_bytes)*headroom_factor)",
                "grid_points": grid_points,
                "estimated_bytes": transient_bytes,
            }
    resolved_budget_path = plan_output.with_name("resolved_engineering_budget.json")
    resolved_budget_path.write_text(
        json.dumps(resolved_budget, indent=2) + "\n", encoding="utf-8"
    )

    resolved_path, plan_path = write_resolved_and_plan(
        resolved_registry_path,
        experiment["connection_profile_id"],
        resolved_output,
        plan_output,
        repo_root=root,
    )
    materialized_source_path = None
    resolved_population_path = None
    if layout_files is not None:
        schedule = derive_pulse_schedule(
            design_evidence["state_path"], _load(resolved_path), _load(layout_files["geometry"]),
            layout_profile,
            campaign_id=campaign["campaign_id"],
            experiment_id=experiment_id,
            experiment_row_sha256=row_sha256,
            population_declaration_sha256=_canonical_sha256(population_declaration),
            policy=pulse_schedule_policy,
            rf_frequency_hz=float(
                design_evidence["resolved_design"]["drive"]["frequency_Hz"]
            ),
        )
        validate_schema(
            schedule, "rf_oatof_resolved_single_flight_pulse_schedule.schema.json"
        )
        schedule_path = plan_output.with_name("resolved_single_flight_pulse_schedule.json")
        schedule_path.write_text(json.dumps(schedule, indent=2) + "\n", encoding="utf-8")
        layout_files["schedule"] = schedule_path
        if pre_pulse_source_path is not None and source_materialization_profile is not None:
            pulse_restart_validation = _validate_canonical_pulse_restart_state(
                pre_pulse_source_path,
                pre_pulse_receipt_path,
                pre_pulse_source_state,
                source_materialization_profile,
                geometry,
                schedule,
            )
            pulse_restart_validation_path = plan_output.with_name(
                "canonical_pulse_restart_target_state_validation.json"
            )
            pulse_restart_validation_path.write_text(
                json.dumps(pulse_restart_validation, indent=2) + "\n",
                encoding="utf-8",
            )
        if (
            source_materialization_profile is not None
            and source_materialization_profile["materialization_mode"]
            == "resolved_layout_pulse_ideal_linear_z_vz"
        ):
            materialized_source_path = plan_output.parent / "inputs" / (
                "single_flight_materialized_particle_source.csv"
            )
            materialization_receipt_path = plan_output.parent / "inputs" / (
                "single_flight_source_materialization_receipt.json"
            )
            pulse_target_source_path = plan_output.parent / "inputs" / (
                "single_flight_pulse_target_state.csv"
            )
            materialization_receipt = materialize_ideal_linear_source(
                materialized_source_path,
                materialization_receipt_path,
                _load(resolved_path),
                geometry,
                schedule,
                source_materialization_profile,
                pulse_target_source_path,
            )
        elif (
            source_materialization_profile is not None
            and source_materialization_profile["materialization_mode"]
            != "canonical_multipole_source"
        ):
            raise ContractError("source materialization mode is unsupported")
        table_binding = population_declaration["source_authority"]["table_binding"]
        if table_binding == "source_contract_particle_source":
            population_path = _workspace_record(
                workspace, source["particle_source"], "population source contract table"
            )
            population_input_role = source["particle_source_manifest_input_role"]
        elif table_binding == "experiment_single_flight_particle_source":
            if single_flight_source_path is None:
                raise ContractError("population declaration requires an experiment source table")
            population_path = single_flight_source_path
            population_input_role = "single_flight_particle_source"
        elif table_binding == "experiment_pre_pulse_source_state":
            if pre_pulse_source_path is None:
                raise ContractError("population declaration requires a pre-pulse source table")
            population_path = pre_pulse_source_path
            population_input_role = "pre_pulse_source_state"
        elif table_binding == "prepared_materialized_particle_source":
            if materialized_source_path is None:
                raise ContractError("population declaration requires a materialized source table")
            population_path = materialized_source_path
            population_input_role = "single_flight_materialized_particle_source"
        elif table_binding == "prepared_deterministic_prefix":
            if pulse_prefix_path is None:
                raise ContractError("population declaration requires a deterministic prefix table")
            population_path = pulse_prefix_path
            population_input_role = "pulse_resolution_screening_prefix"
        elif table_binding == "staged_upstream_source":
            population_path = _workspace_record(
                workspace, source["particle_source"], "staged population source table"
            )
            population_input_role = source["particle_source_manifest_input_role"]
        else:
            raise ContractError("population source table binding is unsupported")
        resolved_population = compile_resolved_population_contract(
            campaign_id=campaign["campaign_id"],
            experiment_id=experiment_id,
            experiment_row_sha256=row_sha256,
            population_declaration_sha256=_canonical_sha256(population_declaration),
            execution_strategy=execution_strategy,
            source_release_mode=source_release_mode,
            declaration=population_declaration,
            source_table=_population_source_table(
                population_path,
                workspace=workspace,
                input_role=population_input_role,
                table_binding=table_binding,
            ),
        )
        resolved_population_path = plan_output.with_name(
            "resolved_population_contract.json"
        )
        resolved_population_path.write_text(
            json.dumps(resolved_population, indent=2) + "\n", encoding="utf-8"
        )
    plan = _load(plan_path)
    plan["execution_steps"] = [
        {
            "step_id": "rf_to_oatof_transfer",
            "adapter": "powershell",
            "entrypoint": mapping["adapter_entrypoint"],
            "arguments": [
                f"adapter_registry_sha256={repository_text_sha256(adapter_registry_path)}",
                f"campaign_path={campaign_path.relative_to(root).as_posix()}",
                f"campaign_sha256={repository_text_sha256(campaign_path)}",
                f"campaign_id={campaign['campaign_id']}",
                f"experiment_id={experiment_id}",
                f"experiment_row_sha256={row_sha256}",
                f"execution_strategy={execution_strategy}",
                f"runtime_binding_path={runtime_binding_record['path']}",
                f"runtime_binding_sha256={runtime_binding_record['sha256']}",
                f"source_branch_id={solver_id}",
                "resolved_budget_filename=resolved_engineering_budget.json",
                f"resolved_budget_sha256={file_sha256(resolved_budget_path)}",
                "resolved_source_contract_filename=resolved_source_contract.json",
                f"resolved_source_contract_sha256={file_sha256(resolved_source_contract_path)}",
                "upstream_resolved_design_filename=upstream_resolved_design.json",
                "upstream_resolved_design_sha256="
                + design_evidence["resolved_design_sha256"],
            ] + ([] if single_flight_source is None else [
                f"single_flight_particle_source_path={single_flight_source['path']}",
                f"single_flight_particle_source_sha256={single_flight_source['sha256']}",
                f"single_flight_particle_source_count={single_flight_source['particle_count']}",
            ]) + ([] if source_materialization_profile is None else [
                "single_flight_source_materialization_profile_id="
                + source_materialization_profile_id,
            ]) + ([] if source_materialization_profile is None or
                    source_materialization_profile["materialization_mode"] ==
                    "canonical_multipole_source" else [
                "single_flight_materialized_source_filename="
                "inputs/single_flight_materialized_particle_source.csv",
                "single_flight_materialized_source_sha256="
                + materialization_receipt["particle_source"]["sha256"],
                "single_flight_materialized_source_count="
                + str(materialization_receipt["particle_count"]),
                "single_flight_materialization_receipt_filename="
                "inputs/single_flight_source_materialization_receipt.json",
                "single_flight_materialization_receipt_sha256="
                + file_sha256(materialization_receipt_path),
            ]) + ([] if pulse_contract is None else [
                "pulse_resolution_attribution_arm_id="
                + experiment["pulse_resolution_attribution_arm_id"],
                "pulse_resolution_execution_mode="
                + experiment["pulse_resolution_execution_mode"],
                "pulse_resolution_prefix_filename=inputs/"
                + pulse_prefix_path.name,
                "pulse_resolution_prefix_sha256=" + pulse_prefix_sha256,
                "pulse_resolution_registration_filename=inputs/"
                + registration_receipt_path.name,
                "pulse_resolution_registration_sha256="
                + registration_receipt_sha256,
            ]) + ([] if experiment.get("pulse_resolution_baseline_checkpoints") is None else [
                "pulse_resolution_baseline_checkpoints_path="
                + experiment["pulse_resolution_baseline_checkpoints"]["path"],
                "pulse_resolution_baseline_checkpoints_sha256="
                + experiment["pulse_resolution_baseline_checkpoints"]["sha256"],
            ]) + ([] if layout_files is None else [
                f"layout_profile_id={experiment['single_flight_layout_profile_id']}",
                "architecture_generation_id="
                + layout_profile["architecture_generation_id"],
                "resolved_oatof_geometry_filename=resolved_oatof_geometry.json",
                f"resolved_oatof_geometry_sha256={file_sha256(layout_files['geometry'])}",
                "resolved_single_flight_pulse_schedule_filename=resolved_single_flight_pulse_schedule.json",
                f"resolved_single_flight_pulse_schedule_sha256={file_sha256(layout_files['schedule'])}",
                "resolved_population_contract_filename=resolved_population_contract.json",
                f"resolved_population_contract_sha256={file_sha256(resolved_population_path)}",
                f"single_flight_layout_registry_sha256={repository_text_sha256(layout_files['registry'])}",
                "resolved_oatof_bore_radius_mm="
                + format(float(geometry["geometry_mm"]["bore_r"]), ".17g"),
                "resolved_oatof_ring_outer_radius_mm="
                + format(float(geometry["geometry_mm"]["ring_outer_r"]), ".17g"),
                "resolved_oatof_shield_inner_radius_mm="
                + format(float(geometry["geometry_mm"]["flight_tube_r"]), ".17g"),
            ]) + ([] if source_release_mode is None else [
                "source_release_mode=" + source_release_mode,
            ]) + ([] if source_profile_id is None else [
                "source_profile_id=" + source_profile_id,
                "field_overlay_id=" + field_overlay_id,
            ]) + ([] if pre_pulse_source_path is None else [
                "pre_pulse_source_state_path="
                + _workspace_relative(pre_pulse_source_path, workspace),
                "pre_pulse_source_state_sha256=" + pre_pulse_source_state["sha256"],
                "pre_pulse_source_state_count="
                + str(pre_pulse_source_state["particle_count"]),
            ]) + ([] if pre_pulse_source_path is None or source_materialization_profile is None else [
                "pre_pulse_restart_position_tolerance_mm="
                + format(float(pre_pulse_source_state["position_rowwise_abs_tolerance_mm"]), ".17g"),
                "pre_pulse_restart_velocity_tolerance_m_per_s="
                + format(float(pre_pulse_source_state["velocity_rowwise_abs_tolerance_m_per_s"]), ".17g"),
                "pre_pulse_restart_clock_tolerance_us="
                + format(float(pre_pulse_source_state["clock_abs_tolerance_us"]), ".17g"),
                "pre_pulse_restart_energy_tolerance_eV="
                + format(float(pre_pulse_source_state["energy_abs_tolerance_eV"]), ".17g"),
                "pre_pulse_restart_validation_filename="
                + pulse_restart_validation_path.name,
                "pre_pulse_restart_validation_sha256="
                + file_sha256(pulse_restart_validation_path),
            ]) + ([] if "single_flight_frontend_grid_profile_id" not in experiment else [
                "single_flight_frontend_grid_profile_id="
                + experiment["single_flight_frontend_grid_profile_id"],
            ]) + ([] if "single_flight_oatof_numerical_profile_id" not in experiment else [
                "single_flight_oatof_numerical_profile_id="
                + experiment["single_flight_oatof_numerical_profile_id"],
            ]) + ([] if "single_flight_trajectory_quality_profile_id" not in experiment else [
                "single_flight_trajectory_quality_profile_id="
                + experiment["single_flight_trajectory_quality_profile_id"],
            ]) + ([] if "single_flight_time_integration_profile_id" not in experiment else [
                "single_flight_time_integration_profile_id="
                + experiment["single_flight_time_integration_profile_id"],
            ]) + ([] if "single_flight_spatial_window_profile_id" not in experiment else [
                "single_flight_spatial_window_profile_id="
                + experiment["single_flight_spatial_window_profile_id"],
            ]) + ([] if resolved_region_field_contract_path is None else [
                "resolved_region_field_contract_filename=inputs/"
                + resolved_region_field_contract_path.name,
                "resolved_region_field_contract_sha256="
                + file_sha256(resolved_region_field_contract_path),
                "resolved_region_field_semantic_sha256="
                + str(resolved_region_field_contract["semantic_sha256"]),
                "resolved_region_field_profile_id="
                + str(resolved_region_field_contract["semantic"]["canonical_profile_id"]),
            ]),
        }
    ]
    validate_schema(plan, "composition_plan.schema.json")
    plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    verify_composition_plan(plan_path, resolved_path, repo_root=root)
    return resolved_path, plan_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--profile-registry", required=True, type=Path)
    parser.add_argument("--adapter-registry", required=True, type=Path)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--resolved-output", required=True, type=Path)
    parser.add_argument("--plan-output", required=True, type=Path)
    args = parser.parse_args()
    resolved, plan = prepare_family_source_closure(
        repo_root=args.repo_root,
        profile_registry_path=args.profile_registry,
        adapter_registry_path=args.adapter_registry,
        campaign_path=args.campaign,
        experiment_id=args.experiment_id,
        resolved_output=args.resolved_output,
        plan_output=args.plan_output,
    )
    print(f"FAMILY_SOURCE_CLOSURE_PREPARE=PASS RESOLVED={resolved} PLAN={plan}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
