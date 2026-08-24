"""Compare observed-source transverse sensitivity or publish sequential source attribution."""

from __future__ import annotations

import argparse
import copy
import csv
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from common.contracts.artifact_naming import validate_run_id
from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.compare_single_flight_apertures import (
    _event_maps,
    _pair_event,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.run_publication import (
    freeze_repository_inputs,
    load_json,
    portable_path,
    publish_manifest,
    record_for_path,
    verified_record,
    write_pending_json,
)
from common.analysis.peak_metrics import (
    compute_peak_metrics,
)


INTEGRATION_ID = "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
MODE = "observed_transverse_sensitivity_comparison"
SEQUENTIAL_MODE = "observed_source_sequential_attribution"
ARM_C = "observed_z_vz_energy_transverse_collapsed"
ARM_D = "full_observed_6d"
ARM_AFFINE_FIXED = "affine_zvz_fixed_10eV_transverse_collapsed"
ARM_OBSERVED_FIXED = "observed_zvz_fixed_10eV_transverse_collapsed"
SEQUENTIAL_ARMS = (
    ARM_AFFINE_FIXED,
    ARM_OBSERVED_FIXED,
    ARM_C,
    ARM_D,
)
SEQUENTIAL_TRANSITIONS = (
    ("affine_to_observed_zvz", ARM_AFFINE_FIXED, ARM_OBSERVED_FIXED),
    ("fixed_10eV_to_observed_energy", ARM_OBSERVED_FIXED, ARM_C),
    ("transverse_collapsed_to_full_observed_6d", ARM_C, ARM_D),
)
SEQUENTIAL_EVENTS = (
    "source_release",
    "pre_pulse_state",
    "accelerator_grid1_forward",
    "accelerator_intermediate2_forward",
    "local_accelerator_exit",
    "accelerator_focus_forward",
    "reflectron_entrance_forward",
    "reflectron_midgrid_forward",
    "reflectron_turning_point",
    "reflectron_exit_return",
    "detector_crossing",
)
PEAK_EVENTS = ("accelerator_focus_forward", "detector_crossing")
FROZEN_CHILD_INPUT_KEYS = (
    "configuration",
    "upstream_resolved_design",
    "oatof_resolved_geometry",
    "resolved_region_field_contract",
    "analyzer_component",
    "pulse_hook",
    "frontend_hook",
    "rf_drive_kernel",
    "particle_row_map",
    "frontend_gem",
    "frontend_contract",
    "frontend_electrode_topology",
    "frontend_pa_cache_manifest",
    "accelerator_overlay_gem",
    "accelerator_overlay_contract",
    "accelerator_overlay_pa_cache_manifest",
    "accelerator_overlay_basis_report",
    "accelerator_overlay_interface_report",
    "flight_tube_pa_cache_manifest",
    "three_zone_t5_candidate",
)
VERSIONED_CHILD_INPUT_KEYS = ("runtime_binding", "resolved_connection", "pulse_schedule")


def _record_path(record: Any, label: str) -> Path:
    value = verified_record(label, record)
    return Path(str(value["path"])).resolve()


def _named_record(records: Any, name: str, label: str) -> Path:
    iterable = records.values() if isinstance(records, dict) else records
    matches = [
        record
        for record in iterable or []
        if isinstance(record, dict) and Path(str(record.get("path", ""))).name == name
    ]
    if len(matches) != 1:
        raise ContractError(f"{label} {name} is not bound exactly once")
    return _record_path(matches[0], f"{label} {name}")


def _keyed_record(records: Any, key: str, label: str) -> tuple[Path, str]:
    if not isinstance(records, dict) or key not in records:
        raise ContractError(f"{label} {key} is not bound")
    record = verified_record(f"{label} {key}", records[key])
    return Path(str(record["path"])).resolve(), str(record["sha256"])


def _comparable_versioned_input(key: str, document: dict[str, Any]) -> dict[str, Any]:
    """Remove only preregistered/run-local identity from an otherwise exact input."""
    comparable = copy.deepcopy(document)
    if key == "pulse_schedule":
        identity_keys = {"campaign_id", "experiment_id", "experiment_row_sha256"}
        if not identity_keys <= comparable.keys():
            raise ContractError("pulse schedule preregistration identity is incomplete")
        for identity_key in identity_keys:
            comparable.pop(identity_key)
    elif key == "runtime_binding":
        implementation = comparable.get("implementation_binding")
        if not isinstance(implementation, dict) or "sha256" not in implementation:
            raise ContractError("runtime binding implementation version identity is missing")
        implementation.pop("sha256")
    elif key == "resolved_connection":
        sources = comparable.get("sources")
        expected_sources = {
            "profile_sha256",
            "upstream_port",
            "downstream_port",
            "upstream_authority",
            "downstream_authority",
            "profile_registry",
        }
        if not isinstance(sources, dict) or set(sources) != expected_sources:
            raise ContractError("resolved connection run-local sources are missing")
        for source_name in expected_sources - {"profile_sha256"}:
            if not isinstance(sources[source_name], dict) or set(sources[source_name]) != {"path", "sha256"}:
                raise ContractError("resolved connection run-local source record differs")
        comparable.pop("sources")
    else:
        raise ContractError(f"unsupported versioned child input {key}")
    return comparable


def _load_arm(runs_root: Path, parent_run_id: str, expected_arm: str) -> dict[str, Any]:
    validate_run_id(parent_run_id)
    parent = (runs_root / parent_run_id).resolve()
    manifest_path = parent / "run_manifest.json"
    manifest = load_json(manifest_path, "parent manifest")
    if (
        manifest.get("role") != "simulation_run_manifest"
        or manifest.get("status") != "success"
        or manifest.get("run_id") != parent_run_id
        or manifest.get("project") != INTEGRATION_ID
        or manifest.get("mode") != "multipole_family_source_closure"
    ):
        raise ContractError("parent manifest identity differs")
    config_path = _record_path(manifest.get("run_config"), "parent run_config")
    config = load_json(config_path, "parent run_config")
    identity = config.get("source_particle_identity", {})
    projection = identity.get("observed_pre_pulse_projection", {})
    particle_count = config.get("particle_count")
    if (
        not isinstance(particle_count, int)
        or isinstance(particle_count, bool)
        or particle_count < 1
        or config.get("formal_gate_passed") is not False
        or projection.get("arm_id") != expected_arm
    ):
        raise ContractError("parent observed arm identity differs")
    child_manifest_path = Path(str(config.get("inputs", {}).get("single_flight_transport_manifest", "")))
    if not child_manifest_path.is_absolute():
        child_manifest_path = (Path(str(config["project_root"])) / child_manifest_path).resolve()
    parent_child_record = record_for_path(manifest.get("inputs"), child_manifest_path, "parent child manifest")
    child_manifest = load_json(child_manifest_path, "child manifest")
    if (
        parent_child_record.get("sha256") != verified_record("parent child manifest", parent_child_record).get("sha256")
        or child_manifest.get("role") != "simulation_run_manifest"
        or child_manifest.get("status") != "success"
        or child_manifest.get("formal_eligible") is not False
    ):
        raise ContractError("child manifest identity differs")
    child_config_path = _record_path(child_manifest.get("run_config"), "child run_config")
    child_config = load_json(child_config_path, "child run_config")
    if (
        child_config.get("project") != INTEGRATION_ID
        or child_config.get("upstream_source_identity") != identity
        or child_config.get("formal_gate_passed") is not False
    ):
        raise ContractError("child source identity differs from parent")
    checkpoints = _named_record(child_manifest.get("outputs"), "single_flight_particle_checkpoints.csv", "child output")
    summary = _named_record(child_manifest.get("outputs"), "summary.json", "child output")
    summary_document = load_json(summary, "child summary")
    if (
        summary_document.get("role") != "rf_oatof_simion_single_flight_summary"
        or summary_document.get("status") != "success"
        or summary_document.get("formal_gate_passed") is not False
        or summary_document.get("resolution_time_basis") != "detector_time_minus_pulse_effective_time"
    ):
        raise ContractError("child summary identity or clock basis differs")
    child_inputs = child_manifest.get("inputs")
    input_sha256s = {key: _keyed_record(child_inputs, key, "child input")[1] for key in FROZEN_CHILD_INPUT_KEYS}
    versioned_inputs = {}
    for key in VERSIONED_CHILD_INPUT_KEYS:
        path, _ = _keyed_record(child_inputs, key, "child input")
        versioned_inputs[key] = _comparable_versioned_input(key, load_json(path, f"child {key}"))
    validation_path, _ = _keyed_record(child_inputs, "pre_pulse_restart_validation", "child input")
    particle_row_map_path, _ = _keyed_record(child_inputs, "particle_row_map", "child input")
    validation = load_json(validation_path, "pre-pulse restart validation")
    projection_receipt = parent / "inputs" / "observed_pre_pulse_projection_receipt.json"
    if (
        not projection_receipt.is_file()
        or validation.get("role") != "canonical_pulse_restart_target_state_validation"
        or validation.get("status") != "PASS"
        or validation.get("projection_arm_id") != expected_arm
        or validation.get("particle_count") != particle_count
        or validation.get("materialization_receipt_sha256") != file_sha256(projection_receipt)
    ):
        raise ContractError("parent projection receipt is missing or not child-bound")
    projection_receipt_document = load_json(projection_receipt, "projection receipt")
    selected_arm = projection_receipt_document.get("arms", {}).get(expected_arm, {})
    mother_source_sha256 = _keyed_record(child_inputs, "mother_particle_source", "child input")[1]
    projection = projection_receipt_document.get("projection", {})
    required_invariants = {
        "full_observed_velocity_preserved",
        "full_observed_position_common_translation",
        "collapsed_z_vz_energy_clock_equal_full",
        "collapsed_x_y_equal_current_center",
        "collapsed_vy_zero",
        "collapsed_positive_vx_preserves_transverse_speed",
        "energy_recomputed_from_velocity",
    }
    if (
        projection_receipt_document.get("role") != "rf_oatof_observed_pre_pulse_projection_receipt"
        or projection_receipt_document.get("status") != "PASS"
        or selected_arm.get("sha256") != mother_source_sha256
        or validation.get("target_pulse_state_sha256") != mother_source_sha256
        or any(projection_receipt_document.get("invariants", {}).get(name) is not True for name in required_invariants)
    ):
        raise ContractError("selected projection arm receipt identity differs")
    if expected_arm in {ARM_AFFINE_FIXED, ARM_OBSERVED_FIXED} and (
        projection_receipt_document.get("schema_version") != 2
        or projection.get("method") != "observed_z_four_arm_energy_decomposition_v2"
        or not isinstance(projection.get("fixed_kinetic_energy_eV"), (int, float))
        or isinstance(projection.get("fixed_kinetic_energy_eV"), bool)
        or not math.isfinite(float(projection["fixed_kinetic_energy_eV"]))
        or float(projection["fixed_kinetic_energy_eV"]) <= 0
    ):
        raise ContractError("fixed-energy sequential arm receipt identity differs")
    return {
        "parent_manifest": manifest_path,
        "parent_config": config_path,
        "child_manifest": child_manifest_path,
        "child_config": child_config_path,
        "checkpoints": checkpoints,
        "summary": summary,
        "projection_receipt": projection_receipt,
        "pre_pulse_restart_validation": validation_path,
        "particle_row_map": particle_row_map_path,
        "projection_receipt_document": projection_receipt_document,
        "source_identity": identity,
        "child_parameters": child_config.get("parameters"),
        "child_input_sha256s": input_sha256s,
        "versioned_child_inputs": versioned_inputs,
        "summary_document": summary_document,
        "particle_count": particle_count,
    }


def _paired_authority_gate(c: dict[str, Any], d: dict[str, Any]) -> None:
    left, right = copy.deepcopy(c["source_identity"]), copy.deepcopy(d["source_identity"])
    left["observed_pre_pulse_projection"].pop("arm_id")
    right["observed_pre_pulse_projection"].pop("arm_id")
    if left != right:
        raise ContractError("collapsed/full source authorities differ beyond arm_id")
    excluded = {
        "resolved_population_contract_sha256",
        "three_zone_solver_gate_id",
        "three_zone_n1_solver_authorization_receipt_sha256",
        "three_zone_n1_producer_parent_manifest_sha256",
        "three_zone_source_identity_sha256",
    }
    c_parameters = {key: value for key, value in c["child_parameters"].items() if key not in excluded}
    d_parameters = {key: value for key, value in d["child_parameters"].items() if key not in excluded}
    if c_parameters != d_parameters:
        raise ContractError("collapsed/full PA, geometry, or numerical identities differ")
    c_receipt = load_json(c["projection_receipt"], "observed-energy transverse-collapsed projection receipt")
    d_receipt = load_json(d["projection_receipt"], "full-observed-6D projection receipt")
    for key in (
        "manifest",
        "prepared_arms",
        "observed_state",
        "old_geometry",
        "current_target",
        "current_subset_receipt",
    ):
        if c_receipt["authorities"][key]["sha256"] != d_receipt["authorities"][key]["sha256"]:
            raise ContractError(f"collapsed/full projection {key} authority differs")
    if (
        c_receipt["projection"] != d_receipt["projection"]
        or c_receipt["invariants"] != d_receipt["invariants"]
        or any(c_receipt["arms"][arm]["sha256"] != d_receipt["arms"][arm]["sha256"] for arm in (ARM_C, ARM_D))
    ):
        raise ContractError("collapsed/full projection paired-state identity differs")


def _comparable_source_identity(arm: dict[str, Any]) -> dict[str, Any]:
    identity = copy.deepcopy(arm["source_identity"])
    projection = identity.get("observed_pre_pulse_projection", {})
    projection.pop("arm_id", None)
    projection.pop("comparison_claim", None)
    return identity


def _comparable_child_parameters(arm: dict[str, Any]) -> dict[str, Any]:
    excluded = {
        "resolved_population_contract_sha256",
        "three_zone_solver_gate_id",
        "three_zone_n1_solver_authorization_receipt_sha256",
        "three_zone_n1_producer_parent_manifest_sha256",
        "three_zone_source_identity_sha256",
    }
    return {key: value for key, value in arm["child_parameters"].items() if key not in excluded}


def _stable_projection_receipt_identity(arm: dict[str, Any]) -> dict[str, Any]:
    receipt = arm["projection_receipt_document"]
    authority_names = ("manifest", "prepared_arms", "observed_state", "old_geometry")
    projection_names = (
        "old_center_mm",
        "current_center_mm",
        "translation_mm",
        "old_instrument_time_us",
        "current_instrument_time_us",
        "simulation_to_source_particle_id",
    )
    return {
        "authorities": {name: receipt["authorities"][name]["sha256"] for name in authority_names},
        "projection": {name: receipt["projection"][name] for name in projection_names},
    }


def _sequential_authority_gate(arms: dict[str, dict[str, Any]]) -> None:
    if set(arms) != set(SEQUENTIAL_ARMS):
        raise ContractError("sequential attribution requires exactly four named arms")
    reference = arms[ARM_AFFINE_FIXED]
    reference_source = _comparable_source_identity(reference)
    reference_parameters = _comparable_child_parameters(reference)
    reference_inputs = reference["child_input_sha256s"]
    reference_versioned_inputs = reference["versioned_child_inputs"]
    reference_projection = _stable_projection_receipt_identity(reference)
    for arm_name in SEQUENTIAL_ARMS:
        arm = arms[arm_name]
        if (
            _comparable_source_identity(arm) != reference_source
            or _comparable_child_parameters(arm) != reference_parameters
            or arm["child_input_sha256s"] != reference_inputs
            or arm["versioned_child_inputs"] != reference_versioned_inputs
            or _stable_projection_receipt_identity(arm) != reference_projection
        ):
            raise ContractError("sequential source, PA, geometry, numerics, or particle identity differs")
    fixed_receipts = [arms[name]["projection_receipt_document"] for name in (ARM_AFFINE_FIXED, ARM_OBSERVED_FIXED)]
    fixed_projection_identity = {
        key: fixed_receipts[0]["projection"][key] for key in ("method", "fixed_kinetic_energy_eV", "affine_authority")
    }
    if any(
        {key: receipt["projection"][key] for key in fixed_projection_identity} != fixed_projection_identity
        for receipt in fixed_receipts[1:]
    ):
        raise ContractError("four-arm affine authority differs")
    required_four_arm_invariants = {
        "all_arms_observed_z_id_clock_equal",
        "affine_arm_vz_from_frozen_authority",
        "observed_fixed_arm_observed_vz_preserved",
        "fixed_10eV_arms_energy_equal",
        "fixed_10eV_arms_centered_xy_vy_zero_positive_vx",
    }
    for receipt in fixed_receipts:
        if any(receipt.get("invariants", {}).get(name) is not True for name in required_four_arm_invariants):
            raise ContractError("four-arm projection physical invariants differ")
    expected_arm_sha256s = {name: fixed_receipts[0]["arms"][name]["sha256"] for name in SEQUENTIAL_ARMS}
    for receipt in fixed_receipts[1:]:
        if {name: receipt["arms"][name]["sha256"] for name in SEQUENTIAL_ARMS} != expected_arm_sha256s:
            raise ContractError("four-arm projection output identities differ")
    for arm_name in SEQUENTIAL_ARMS:
        selected = arms[arm_name]["projection_receipt_document"]["arms"][arm_name]
        if selected["sha256"] != expected_arm_sha256s[arm_name]:
            raise ContractError("selected sequential projection output differs")


def compare_frames(
    c_frame: pd.DataFrame,
    d_frame: pd.DataFrame,
    c_peak: dict[str, Any],
    d_peak: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Compare strict detector cohorts, reusing the canonical event pairing helper."""
    c_detector = _event_maps(c_frame)["detector_crossing"]
    d_detector = _event_maps(d_frame)["detector_crossing"]
    if not c_detector or set(c_detector) != set(d_detector):
        raise ContractError("collapsed/full detector particle IDs must be nonempty and exactly paired")
    metrics, residuals = _pair_event(c_detector, d_detector)
    rows: list[dict[str, Any]] = []
    for residual in residuals:
        row = {"particle_id": int(residual["particle_id"])}
        row["delta_time_full_minus_collapsed_ns"] = residual["delta_time_small_minus_wide_ns"]
        for axis in "xyz":
            row[f"delta_{axis}_full_minus_collapsed_mm"] = residual[f"delta_{axis}_mm"]
            raw_velocity = float(residual[f"delta_v{axis}_m_s"])
            row[f"delta_v{axis}_full_minus_collapsed_m_s"] = raw_velocity if math.isfinite(raw_velocity) else None
        row["position_delta_norm_mm"] = float(
            np.sqrt(sum(float(row[f"delta_{axis}_full_minus_collapsed_mm"]) ** 2 for axis in "xyz"))
        )
        velocity_components = [row[f"delta_v{axis}_full_minus_collapsed_m_s"] for axis in "xyz"]
        row["velocity_delta_norm_m_s"] = (
            float(np.sqrt(sum(float(value) ** 2 for value in velocity_components)))
            if all(value is not None for value in velocity_components)
            else None
        )
        rows.append(row)

    def distribution(field: str) -> dict[str, float | int | None]:
        values = np.asarray([float(row[field]) for row in rows if row[field] is not None])
        if values.size == 0:
            return {
                "available_count": 0,
                "mean": None,
                "sample_sigma": None,
                "rms": None,
                "max_abs": None,
            }
        return {
            "available_count": int(values.size),
            "mean": float(np.mean(values)),
            "sample_sigma": float(np.std(values, ddof=1)),
            "rms": float(np.sqrt(np.mean(values**2))),
            "max_abs": float(np.max(np.abs(values))),
        }

    paired = {field: distribution(field) for field in rows[0] if field != "particle_id"}
    peak_delta = {
        field: float(d_peak[field]) - float(c_peak[field])
        for field in ("mean_tof_us", "std_tof_ns", "direct_fwhm_tof_ns", "mass_resolution")
    }
    peak_delta["direct_fwhm_tof_pct"] = 100.0 * peak_delta["direct_fwhm_tof_ns"] / float(c_peak["direct_fwhm_tof_ns"])
    peak_delta["std_tof_pct"] = 100.0 * peak_delta["std_tof_ns"] / float(c_peak["std_tof_ns"])
    peak_delta["mass_resolution_pct"] = 100.0 * peak_delta["mass_resolution"] / float(c_peak["mass_resolution"])
    result = {
        "schema_version": 1,
        "role": "rf_oatof_observed_transverse_sensitivity_comparison",
        "status": "FUNCTIONAL_ONLY",
        "formal_gate_passed": False,
        "paired_particle_count": len(rows),
        "detector_identity": {
            "transverse_collapsed_particles": metrics["wide_particles"],
            "full_observed_6d_particles": metrics["small_particles"],
            "common_particles": metrics["common_particles"],
            "transverse_collapsed_only_particles": metrics["wide_only_particles"],
            "full_observed_6d_only_particles": metrics["small_only_particles"],
            "jaccard_identity": metrics["jaccard_identity"],
            "mean_delta_time_full_minus_collapsed_ns": metrics["mean_delta_time_small_minus_wide_ns"],
            "rms_delta_time_full_minus_collapsed_ns": metrics["rms_delta_time_ns"],
            "position_vector_rms_full_minus_collapsed_mm": metrics["position_vector_rms_mm"],
            "velocity_vector_rms_full_minus_collapsed_m_s": metrics["velocity_vector_rms_m_s"],
        },
        "paired_detector_deltas_full_minus_collapsed": paired,
        "peak_metrics": {
            "transverse_collapsed": c_peak,
            "full_observed_6d": d_peak,
            "full_minus_collapsed": peak_delta,
        },
        "thresholds": None,
        "qualification_decision_made": False,
    }
    return result, rows


def _event_map(frame: pd.DataFrame, event: str) -> dict[int, dict[str, float]]:
    maps = _event_maps(frame)
    if event in maps:
        return maps[event]
    required = {
        "particle_id",
        "event",
        "instrument_time_us",
        "x_mm",
        "y_mm",
        "z_mm",
        "vx_mm_per_us",
        "vy_mm_per_us",
        "vz_mm_per_us",
    }
    if missing := sorted(required - set(frame.columns)):
        raise ContractError(f"checkpoint columns are missing: {', '.join(missing)}")
    rows = frame.loc[frame["event"].eq(event)]
    if rows["particle_id"].duplicated().any():
        raise ContractError(f"duplicate particle identity at event {event}")
    return {
        int(row.particle_id): {
            "time_us": float(row.instrument_time_us),
            "x_mm": float(row.x_mm),
            "y_mm": float(row.y_mm),
            "z_mm": float(row.z_mm),
            "vx_mm_per_us": float(row.vx_mm_per_us),
            "vy_mm_per_us": float(row.vy_mm_per_us),
            "vz_mm_per_us": float(row.vz_mm_per_us),
        }
        for row in rows.itertuples(index=False)
    }


def _distribution(values: list[float | None]) -> dict[str, float | int | None]:
    finite = np.asarray([float(value) for value in values if value is not None and math.isfinite(value)])
    if finite.size == 0:
        return {
            "available_count": 0,
            "mean": None,
            "sample_sigma": None,
            "rms": None,
            "max_abs": None,
        }
    return {
        "available_count": int(finite.size),
        "mean": float(np.mean(finite)),
        "sample_sigma": float(np.std(finite, ddof=1)),
        "rms": float(np.sqrt(np.mean(finite**2))),
        "max_abs": float(np.max(np.abs(finite))),
    }


def _renamed_residuals(
    left: dict[int, dict[str, float]],
    right: dict[int, dict[str, float]],
) -> dict[int, dict[str, float | None]]:
    metrics, residuals = _pair_event(left, right)
    if (
        metrics["wide_particles"] < 1
        or metrics["small_particles"] < 1
        or metrics["common_particles"] != metrics["wide_particles"]
        or metrics["wide_only_particles"] != 0
        or metrics["small_only_particles"] != 0
    ):
        raise ContractError("sequential checkpoint identities must be nonempty and exactly paired")
    result: dict[int, dict[str, float | None]] = {}
    for residual in residuals:
        row: dict[str, float | None] = {
            "time_ns": float(residual["delta_time_small_minus_wide_ns"]),
        }
        for axis in "xyz":
            row[f"{axis}_mm"] = float(residual[f"delta_{axis}_mm"])
            velocity = float(residual[f"delta_v{axis}_m_s"])
            row[f"v{axis}_m_s"] = velocity if math.isfinite(velocity) else None
        result[int(residual["particle_id"])] = row
    return result


def _peak_delta(predecessor: dict[str, Any], successor: dict[str, Any]) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for field in (
        "mean_tof_us",
        "std_tof_ns",
        "direct_fwhm_tof_ns",
        "mass_resolution",
        "significant_kde_modes",
    ):
        delta = float(successor[field]) - float(predecessor[field])
        result[field] = delta
        denominator = float(predecessor[field])
        result[f"{field}_pct_of_predecessor"] = 100.0 * delta / denominator if denominator != 0.0 else None
    return result


def compare_sequential_frames(
    frames: dict[str, pd.DataFrame],
    pulse_effective_time_us: dict[str, float],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Compute the frozen ordered source decomposition and telescoping closure."""
    if set(frames) != set(SEQUENTIAL_ARMS):
        raise ContractError("sequential comparison requires exactly four named frames")
    if len(set(pulse_effective_time_us.values())) != 1:
        raise ContractError("sequential arms use different pulse-effective clocks")
    event_results: dict[str, Any] = {}
    paired_rows: list[dict[str, Any]] = []
    for event in SEQUENTIAL_EVENTS:
        event_maps = {name: _event_map(frames[name], event) for name in SEQUENTIAL_ARMS}
        particle_ids = set(event_maps[ARM_AFFINE_FIXED])
        if not particle_ids or any(set(mapping) != particle_ids for mapping in event_maps.values()):
            raise ContractError(f"sequential arm particle IDs at {event} must be nonempty and exactly paired")
        transitions = {
            name: _renamed_residuals(event_maps[left], event_maps[right])
            for name, left, right in SEQUENTIAL_TRANSITIONS
        }
        total = _renamed_residuals(event_maps[ARM_AFFINE_FIXED], event_maps[ARM_D])
        fields = tuple(next(iter(total.values())))
        closure_values: dict[str, list[float | None]] = {field: [] for field in fields}
        transition_values = {name: {field: [] for field in fields} for name, _, _ in SEQUENTIAL_TRANSITIONS}
        total_values = {field: [] for field in fields}
        for particle_id in sorted(particle_ids):
            output_row: dict[str, Any] = {
                "event": event,
                "particle_id": particle_id,
            }
            for field in fields:
                components = [transitions[name][particle_id][field] for name, _, _ in SEQUENTIAL_TRANSITIONS]
                total_value = total[particle_id][field]
                for (name, _, _), value in zip(SEQUENTIAL_TRANSITIONS, components, strict=True):
                    output_row[f"delta_{field}_{name}"] = value
                    transition_values[name][field].append(value)
                output_row[f"delta_{field}_total_affine_to_full_observed"] = total_value
                total_values[field].append(total_value)
                closure = (
                    float(total_value) - sum(float(value) for value in components)
                    if total_value is not None and all(value is not None for value in components)
                    else None
                )
                output_row[f"closure_residual_{field}"] = closure
                closure_values[field].append(closure)
            paired_rows.append(output_row)
        event_results[event] = {
            "arm_particle_counts": {name: len(particle_ids) for name in SEQUENTIAL_ARMS},
            "adjacent_transitions": {
                name: {field: _distribution(values) for field, values in transition_values[name].items()}
                for name, _, _ in SEQUENTIAL_TRANSITIONS
            },
            "total_affine_to_full_observed": {field: _distribution(values) for field, values in total_values.items()},
            "telescoping_closure_residual": {field: _distribution(values) for field, values in closure_values.items()},
        }
    peak_metrics: dict[str, Any] = {}
    pulse_time = next(iter(pulse_effective_time_us.values()))
    for event in PEAK_EVENTS:
        arms: dict[str, Any] = {}
        particle_ids: set[int] | None = None
        for name in SEQUENTIAL_ARMS:
            mapping = _event_map(frames[name], event)
            if particle_ids is None:
                particle_ids = set(mapping)
            if not particle_ids or set(mapping) != particle_ids:
                raise ContractError(f"sequential arm particle IDs at {event} must be nonempty and exactly paired")
            tof = np.asarray([mapping[particle_id]["time_us"] - pulse_time for particle_id in sorted(particle_ids)])
            arms[name] = compute_peak_metrics(tof, 100.0)[0]
        peak_metrics[event] = {
            "arms": arms,
            "adjacent_transitions": {
                transition: _peak_delta(arms[left], arms[right]) for transition, left, right in SEQUENTIAL_TRANSITIONS
            },
            "total_affine_to_full_observed": _peak_delta(arms[ARM_AFFINE_FIXED], arms[ARM_D]),
        }
    result = {
        "schema_version": 1,
        "role": "rf_oatof_observed_source_sequential_attribution",
        "status": "FUNCTIONAL_ONLY",
        "formal_gate_passed": False,
        "paired_particle_count": len(_event_map(frames[ARM_AFFINE_FIXED], "detector_crossing")),
        "decomposition": {
            "order_dependent": True,
            "factorial_effects": False,
            "arm_order": list(SEQUENTIAL_ARMS),
            "adjacent_transitions": [name for name, _, _ in SEQUENTIAL_TRANSITIONS],
            "total_transition": "total_affine_to_full_observed",
        },
        "events": event_results,
        "peak_metrics": peak_metrics,
        "thresholds": None,
        "qualification_decision_made": False,
    }
    return result, paired_rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    pending = path.with_name(f".{path.name}.pending")
    pending.parent.mkdir(parents=True, exist_ok=True)
    with pending.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    os.replace(pending, path)


def _sequential_mode_requested(
    affine_fixed_parent_id: str | None,
    observed_fixed_parent_id: str | None,
) -> bool:
    if (affine_fixed_parent_id is None) != (observed_fixed_parent_id is None):
        raise ContractError("fixed-energy sequential parent arguments are all-or-none")
    return affine_fixed_parent_id is not None


def publish(
    repo_root: Path,
    run_id: str,
    c_parent_id: str,
    d_parent_id: str,
    affine_fixed_parent_id: str | None = None,
    observed_fixed_parent_id: str | None = None,
) -> Path:
    validate_run_id(run_id)
    repo_root = repo_root.resolve()
    workspace = repo_root.parent
    runs_root = workspace / "artifacts" / "projects" / INTEGRATION_ID / "runs"
    run_dir = runs_root / run_id
    if run_dir.exists():
        raise ContractError(f"analysis run already exists: {run_dir}")
    sequential = _sequential_mode_requested(affine_fixed_parent_id, observed_fixed_parent_id)
    c = _load_arm(runs_root, c_parent_id, ARM_C)
    d = _load_arm(runs_root, d_parent_id, ARM_D)
    if sequential:
        arms = {
            ARM_AFFINE_FIXED: _load_arm(runs_root, str(affine_fixed_parent_id), ARM_AFFINE_FIXED),
            ARM_OBSERVED_FIXED: _load_arm(runs_root, str(observed_fixed_parent_id), ARM_OBSERVED_FIXED),
            ARM_C: c,
            ARM_D: d,
        }
        _sequential_authority_gate(arms)
        inputs = {
            f"{arm_name}_{key}": value
            for arm_name, arm in arms.items()
            for key, value in arm.items()
            if isinstance(value, Path)
        }
    else:
        _paired_authority_gate(c, d)
        inputs = {
            f"observed_energy_transverse_collapsed_{key}": value for key, value in c.items() if isinstance(value, Path)
        }
        inputs.update({f"full_observed_6d_{key}": value for key, value in d.items() if isinstance(value, Path)})
    inputs["implementation"] = Path(__file__).resolve()
    run_dir.mkdir(parents=True)
    frozen = freeze_repository_inputs(inputs, repo_root=repo_root, run_dir=run_dir)
    config_path, summary_path = run_dir / "run_config.json", run_dir / "summary.json"
    result_path = (
        run_dir
        / "results"
        / ("observed_source_sequential_attribution.json" if sequential else "observed_transverse_sensitivity.json")
    )
    pairs_path = (
        run_dir
        / "results"
        / ("observed_source_sequential_particle_deltas.csv" if sequential else "observed_transverse_detector_pairs.csv")
    )
    manifest_path = run_dir / "run_manifest.json"
    config = {
        "schema_version": 2,
        "run_id": run_id,
        "project": INTEGRATION_ID,
        "mode": SEQUENTIAL_MODE if sequential else MODE,
        "project_root": str(workspace),
        "inputs": {key: portable_path(value, workspace) for key, value in frozen.items()},
        "parameters": (
            {
                "parent_run_ids": {
                    ARM_AFFINE_FIXED: affine_fixed_parent_id,
                    ARM_OBSERVED_FIXED: observed_fixed_parent_id,
                    ARM_C: c_parent_id,
                    ARM_D: d_parent_id,
                },
                "decomposition_order": list(SEQUENTIAL_ARMS),
                "order_dependent": True,
                "analysis_class": "FUNCTIONAL_ONLY",
                "particle_count": arms[ARM_AFFINE_FIXED]["particle_count"],
                "qualification_decision_made": False,
            }
            if sequential
            else {
                "transverse_collapsed_parent_run_id": c_parent_id,
                "full_observed_6d_parent_run_id": d_parent_id,
                "analysis_class": "FUNCTIONAL_ONLY",
                "particle_count": c["particle_count"],
                "qualification_decision_made": False,
            }
        ),
        "artifact_retention": {"policy_version": 1, "class": "compact", "reason": None},
        "formal_gate_passed": False,
    }
    write_pending_json(config_path, config)
    write_pending_json(
        summary_path,
        {
            "schema_version": 1,
            "role": (
                "rf_oatof_observed_source_sequential_attribution_summary"
                if sequential
                else "rf_oatof_observed_transverse_sensitivity_summary"
            ),
            "status": "interrupted",
            "analysis_status": "NOT_RUN",
            "formal_gate_passed": False,
        },
    )
    pending = manifest_path.with_name(".run_manifest.json.pending")
    publish_manifest(
        repo_root=repo_root,
        run_config=config_path,
        manifest_path=pending,
        status="interrupted",
        outputs=(summary_path,),
        project=INTEGRATION_ID,
        mode=SEQUENTIAL_MODE if sequential else MODE,
        label=("observed-source-sequential-attribution" if sequential else "observed-transverse-sensitivity"),
    )
    os.replace(pending, manifest_path)
    if sequential:
        result, rows = compare_sequential_frames(
            {arm_name: pd.read_csv(arm["checkpoints"]) for arm_name, arm in arms.items()},
            {arm_name: float(arm["summary_document"]["pulse_effective_time_us"]) for arm_name, arm in arms.items()},
        )
    else:
        result, rows = compare_frames(
            pd.read_csv(c["checkpoints"]),
            pd.read_csv(d["checkpoints"]),
            c["summary_document"]["pulse_effective_peak"],
            d["summary_document"]["pulse_effective_peak"],
        )
    write_pending_json(result_path, result)
    _write_csv(pairs_path, rows)
    summary = {
        "schema_version": 1,
        "role": (
            "rf_oatof_observed_source_sequential_attribution_summary"
            if sequential
            else "rf_oatof_observed_transverse_sensitivity_summary"
        ),
        "status": "success",
        "analysis_status": "FUNCTIONAL_ONLY",
        "paired_particle_count": result["paired_particle_count"],
        "result": portable_path(result_path, run_dir),
        "paired_detector_rows": portable_path(pairs_path, run_dir),
        "formal_gate_passed": False,
    }
    write_pending_json(summary_path, summary)
    publish_manifest(
        repo_root=repo_root,
        run_config=config_path,
        manifest_path=pending,
        status="success",
        outputs=(result_path, pairs_path, summary_path),
        project=INTEGRATION_ID,
        mode=SEQUENTIAL_MODE if sequential else MODE,
        label=("observed-source-sequential-attribution" if sequential else "observed-transverse-sensitivity"),
    )
    os.replace(pending, manifest_path)
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--collapsed-parent-run-id",
        required=True,
        help="Observed-energy transverse-collapsed parent (also the third sequential arm).",
    )
    parser.add_argument(
        "--full-parent-run-id",
        required=True,
        help="Full-observed-6D parent (also the fourth sequential arm).",
    )
    parser.add_argument(
        "--affine-fixed10-collapsed-parent-run-id",
        help="Affine-z-vz fixed-10-eV transverse-collapsed first sequential parent.",
    )
    parser.add_argument(
        "--observed-fixed10-collapsed-parent-run-id",
        help="Observed-z-vz fixed-10-eV transverse-collapsed second sequential parent.",
    )
    args = parser.parse_args()
    manifest = publish(
        repo_root=args.repo_root,
        run_id=args.run_id,
        c_parent_id=args.collapsed_parent_run_id,
        d_parent_id=args.full_parent_run_id,
        affine_fixed_parent_id=args.affine_fixed10_collapsed_parent_run_id,
        observed_fixed_parent_id=args.observed_fixed10_collapsed_parent_run_id,
    )
    label = (
        "OBSERVED_SOURCE_SEQUENTIAL_ATTRIBUTION"
        if args.affine_fixed10_collapsed_parent_run_id is not None
        else "OBSERVED_TRANSVERSE_SENSITIVITY"
    )
    print(f"{label}=PASS MANIFEST={manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
