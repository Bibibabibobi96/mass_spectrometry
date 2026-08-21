"""Publish the registered full-domain affine five-cell assessment.

This is an internal terminal stage of ``family_source_closure``.  It has no
independent CLI: completion of the fifth registered row is the only public
trigger.
"""

from __future__ import annotations

import csv
import math
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from common.contracts.file_identity import file_sha256, repository_text_sha256
from common.contracts.machine_contracts import ContractError, validate_schema
from common.contracts.verify_run_manifest import verify_record
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.run_publication import (
    freeze_repository_inputs,
    load_json,
    publish_manifest,
    restore_interrupted,
    terminalize_failure,
    write_pending_json,
)


PROJECT_ID = "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
MODE = "full_domain_affine_width_numerics_assessment"
SUMMARY_ROLE = "rf_oatof_full_domain_affine_width_numerics_assessment"
EXPECTED_CLOCK = "detector_time_minus_pulse_effective_time"
EXPECTED_PULSE_BASIS = "pulse_effective_elapsed_us"
CANONICAL_FIELD_CONFIGURATION_ID = "FULL_DOMAIN_PIECEWISE_IDEAL_FIELD"
REGISTERED_CHECKPOINT_EVENTS = (
    "source_release",
    "pre_pulse_state",
    "accelerator_grid1_forward",
    "local_accelerator_exit",
    "accelerator_focus_forward",
    "reflectron_entrance_forward",
    "reflectron_midgrid_forward",
    "reflectron_turning_point",
    "reflectron_exit_return",
    "detector_crossing",
)


def _verified(record: Any, label: str) -> Path:
    if not isinstance(record, dict):
        raise ContractError(f"{label} record is missing")
    try:
        verify_record(label, record)
    except (AssertionError, KeyError, TypeError) as error:
        raise ContractError(f"{label} record identity failed") from error
    path = Path(str(record["path"])).resolve()
    if not path.is_file():
        raise ContractError(f"{label} path is missing")
    return path


def _output_named(manifest: Mapping[str, Any], name: str, label: str) -> Path:
    outputs = manifest.get("outputs")
    rows = (
        [outputs]
        if isinstance(outputs, Mapping) and "path" in outputs
        else outputs.values()
        if isinstance(outputs, Mapping)
        else outputs
    )
    if not isinstance(rows, (list, tuple, type({}.values()))):
        raise ContractError(f"{label} outputs are invalid")
    matches = [
        row for row in rows
        if isinstance(row, dict) and Path(str(row.get("path", ""))).name == name
    ]
    if len(matches) != 1:
        raise ContractError(f"{label} output {name} is not bound exactly once")
    return _verified(matches[0], f"{label} output {name}")


def _output_records(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    outputs = manifest.get("outputs")
    if isinstance(outputs, list):
        return [row for row in outputs if isinstance(row, dict)]
    if isinstance(outputs, Mapping) and "path" in outputs:
        return [dict(outputs)]
    if isinstance(outputs, Mapping):
        return [row for row in outputs.values() if isinstance(row, dict)]
    raise ContractError("manifest outputs are invalid")


def _batch_resource_usage(
    manifest: Mapping[str, Any], manifest_bound_run_config: Mapping[str, Any],
) -> dict[str, Any]:
    parameters = manifest_bound_run_config.get("parameters")
    if not isinstance(parameters, Mapping):
        raise ContractError("child run_config parameters are missing")
    execution_batch_count = parameters.get("execution_batch_count")
    max_parallel_batches = parameters.get("max_parallel_batches")
    if (
        isinstance(execution_batch_count, bool)
        or not isinstance(execution_batch_count, int)
        or execution_batch_count < 1
        or isinstance(max_parallel_batches, bool)
        or not isinstance(max_parallel_batches, int)
        or max_parallel_batches < 1
    ):
        raise ContractError("child run_config batch execution parameters are invalid")
    records = [
        row for row in _output_records(manifest)
        if Path(str(row.get("path", ""))).name.startswith("resource_usage__batch")
    ]
    observed_names = sorted(Path(str(row["path"])).name for row in records)
    expected_names = [
        f"resource_usage__batch{index:02d}.json"
        for index in range(1, execution_batch_count + 1)
    ]
    if observed_names != expected_names:
        raise ContractError(
            "batch resource-usage records differ from the manifest-bound run_config"
        )
    batches = []
    for record in sorted(records, key=lambda row: str(row["path"])):
        path = _verified(record, "batch resource usage")
        value = load_json(path, "batch resource usage")
        if value.get("status") != "completed":
            raise ContractError("batch resource usage is incomplete")
        started = datetime.fromisoformat(str(value["started_at_utc"]))
        wall = _finite(value["wall_clock_seconds"], "batch wall clock")
        batches.append({
            "batch": path.stem.removeprefix("resource_usage__"),
            "started_at_utc": started.isoformat(),
            "wall_clock_seconds": wall,
            "peak_process_tree_working_set_bytes": int(
                value["peak_process_tree_working_set_bytes"]
            ),
        })
    start = min(datetime.fromisoformat(row["started_at_utc"]) for row in batches)
    end = max(
        datetime.fromisoformat(row["started_at_utc"])
        + timedelta(seconds=row["wall_clock_seconds"])
        for row in batches
    )
    return {
        "scope": "SIMION_particle_execution_batches_only_excludes_PA_preparation",
        "execution_batch_count": execution_batch_count,
        "max_parallel_batches": max_parallel_batches,
        "dispatch_wave_contract": f"up_to_{max_parallel_batches}_concurrent_batches",
        "observed_batch_span_seconds": (end - start).total_seconds(),
        "sum_batch_wall_clock_seconds": sum(row["wall_clock_seconds"] for row in batches),
        "batches": batches,
    }


def _finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ContractError(f"{label} is not numeric") from error
    if not math.isfinite(result):
        raise ContractError(f"{label} is not finite")
    return result


def _claim_status(
    *, source_identity_passed: bool, width_passed: bool, numerical_passed: bool
) -> str:
    if not source_identity_passed:
        return "INVALID_IDENTITY_OR_CENSUS"
    if not width_passed:
        return "WIDTH_NOT_SUPPORTED"
    if not numerical_passed:
        return "INCONCLUSIVE_NUMERICAL"
    return (
        "SUPPORTED_STRONG_NONLINEAR_WIDTH_RESPONSE_IN_FIXED_LONG_AFFINE_"
        "FULL_DOMAIN_PIECEWISE_IDEAL_FIELD"
    )


def _verify_manifest_process(
    *, repo_root: Path, manifest_path: Path, status: str
) -> subprocess.CompletedProcess[str]:
    manifest = load_json(manifest_path, "run manifest")
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "common.contracts.verify_run_manifest",
            str(manifest_path),
            "--require-status",
            status,
            "--require-local-run-config",
            "--require-run-id",
            str(manifest["run_id"]),
            "--require-project",
            str(manifest["project"]),
            "--require-mode",
            str(manifest["mode"]),
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )


def _load_detector_times(path: Path) -> tuple[np.ndarray, list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    detector = [row for row in rows if row.get("event") == "detector_crossing"]
    if len(detector) != 1000 or [int(row["particle_id"]) for row in detector] != list(range(1, 1001)):
        raise ContractError("detector checkpoint census/order differs")
    values = np.asarray(
        [_finite(row.get("pulse_effective_elapsed_us"), "detector pulse time") for row in detector],
        dtype=float,
    )
    return values, rows


def _validate_registered_checkpoint_census(
    summary: Mapping[str, Any], rows: list[dict[str, str]]
) -> dict[str, int]:
    census = summary.get("census")
    if not isinstance(census, Mapping):
        raise ContractError("checkpoint census is missing")
    if census.get("launched") != 1000 or census.get("multipole_handoff") != 0:
        raise ContractError("launch/handoff census differs")
    result: dict[str, int] = {}
    expected_ids = list(range(1, 1001))
    for event in REGISTERED_CHECKPOINT_EVENTS:
        event_rows = [row for row in rows if row.get("event") == event]
        if (
            census.get(event) != 1000
            or len(event_rows) != 1000
            or [int(row["particle_id"]) for row in event_rows] != expected_ids
        ):
            raise ContractError(f"registered checkpoint census/order differs: {event}")
        result[event] = 1000
    return {"launched": 1000, "multipole_handoff": 0, **result}


def _source_release_errors(
    target_path: Path,
    checkpoint_rows: list[dict[str, str]],
    validation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    with target_path.open("r", encoding="utf-8-sig", newline="") as stream:
        target = list(csv.DictReader(stream))
    event = "source_release" if validation is not None else "pre_pulse_state"
    actual = [row for row in checkpoint_rows if row.get("event") == event]
    if (
        len(target) != 1000
        or len(actual) != 1000
        or [int(row["particle_id"]) for row in target] != list(range(1, 1001))
        or [int(row["particle_id"]) for row in actual] != list(range(1, 1001))
    ):
        raise ContractError("pulse target/actual particle identity differs")
    fields = {
        "instrument_time_us": ("instrument_time_us", "instrument_time_us", 1.0),
        "position_x_mm": ("position_x_mm", "x_mm", 1.0),
        "position_y_mm": ("position_y_mm", "y_mm", 1.0),
        "position_z_mm": ("position_z_mm", "z_mm", 1.0),
        "velocity_x_m_s": ("velocity_x_m_s", "vx_mm_per_us", 1000.0),
        "velocity_y_m_s": ("velocity_y_m_s", "vy_mm_per_us", 1000.0),
        "velocity_z_m_s": ("velocity_z_m_s", "vz_mm_per_us", 1000.0),
        "kinetic_energy_eV": ("kinetic_energy_eV", "kinetic_energy_eV", 1.0),
    }
    errors: dict[str, Any] = {}
    for name, (target_key, actual_key, scale) in fields.items():
        difference = np.asarray(
            [
                _finite(observed[actual_key], actual_key) * scale
                - _finite(expected[target_key], target_key)
                for expected, observed in zip(target, actual, strict=True)
            ],
            dtype=float,
        )
        errors[name] = {
            "mean_signed_error": float(np.mean(difference)),
            "rms_error": float(np.sqrt(np.mean(difference * difference))),
            "maximum_absolute_error": float(np.max(np.abs(difference))),
        }
    result = {
        "status": "FAIL",
        "reason": "actual_pulse_state_not_validated_against_registered_affine_target",
        "particle_count": 1000,
        "errors": errors,
    }
    if validation is None:
        return result
    tolerance_pairs = {
        "maximum_position_rowwise_abs_error_mm": "position_rowwise_abs_tolerance_mm",
        "maximum_velocity_rowwise_abs_error_m_per_s": "velocity_rowwise_abs_tolerance_m_per_s",
        "maximum_clock_abs_error_us": "clock_abs_tolerance_us",
        "maximum_energy_abs_error_eV": "energy_abs_tolerance_eV",
    }
    valid = (
        validation.get("status") == "PASS"
        and validation.get("checkpoint") == "source_release"
        and validation.get("particle_count") == 1000
        and validation.get("ordered_particle_ids_exact") is True
    )
    for observed_name, tolerance_name in tolerance_pairs.items():
        observed = _finite(validation.get(observed_name), observed_name)
        tolerance = _finite(validation.get(tolerance_name), tolerance_name)
        valid = valid and observed >= 0.0 and tolerance >= 0.0 and observed <= tolerance
    result["status"] = "PASS" if valid else "FAIL"
    result["reason"] = (
        "registered_restart_source_release_identity_verified"
        if valid
        else "registered_restart_source_release_identity_failed"
    )
    result["validation"] = dict(validation)
    return result


def _pulse_metrics(summary: Mapping[str, Any], times_us: np.ndarray) -> dict[str, Any]:
    """Return metrics using only the registered pulse-effective clock authority."""

    if (
        summary.get("resolution_time_basis") != EXPECTED_CLOCK
        or summary.get("detector_pulse_effective_time_basis") != EXPECTED_PULSE_BASIS
    ):
        raise ContractError("pulse-effective clock authority differs")
    peak = summary.get("pulse_effective_peak")
    if not isinstance(peak, dict):
        raise ContractError("pulse_effective_peak is missing")
    required = (
        "std_tof_ns", "direct_fwhm_tof_ns", "mass_resolution",
        "significant_kde_modes", "mean_tof_us",
    )
    if any(name not in peak for name in required):
        raise ContractError("pulse_effective_peak metrics are incomplete")
    sample_sigma = _finite(peak["std_tof_ns"], "sample sigma")
    recomputed_sample_sigma = float(np.std(times_us, ddof=1) * 1000.0)
    if not math.isclose(sample_sigma, recomputed_sample_sigma, rel_tol=1e-10, abs_tol=1e-12):
        raise ContractError("pulse-effective sample sigma does not match checkpoints")
    return {
        "clock_authority": "pulse_effective_peak",
        "resolution_time_basis": EXPECTED_CLOCK,
        "population_sigma_tof_ns": float(np.std(times_us, ddof=0) * 1000.0),
        "sample_sigma_tof_ns": sample_sigma,
        "direct_fwhm_tof_ns": _finite(peak["direct_fwhm_tof_ns"], "FWHM"),
        "mass_resolution": _finite(peak["mass_resolution"], "R"),
        "significant_kde_modes": int(peak["significant_kde_modes"]),
        "mean_tof_us": _finite(peak["mean_tof_us"], "mean TOF"),
        "central80_tof_ns": float((np.quantile(times_us, 0.9) - np.quantile(times_us, 0.1)) * 1000.0),
        "span_tof_ns": float((np.max(times_us) - np.min(times_us)) * 1000.0),
    }


def _path_free_field_identity(
    child_manifest: Mapping[str, Any]
) -> dict[str, Any]:
    metadata_path = _verified(
        child_manifest.get("inputs", {}).get("program_metadata"),
        "child program metadata",
    )
    metadata = load_json(metadata_path, "child program metadata")
    contract_path = metadata_path.with_name("resolved_region_field_contract.json")
    contract = load_json(contract_path, "global field contract")
    semantic = contract.get("semantic")
    if (
        contract.get("schema_version") != 1
        or contract.get("role") != "rf_oatof_resolved_region_field_contract"
        or not isinstance(semantic, Mapping)
        or semantic.get("field_configuration_id")
        != "FULL_DOMAIN_PIECEWISE_IDEAL_FIELD"
        or semantic.get("canonical_profile_id")
        != "full_domain_piecewise_ideal_field"
        or semantic.get("real_pa_field_blending_allowed") is not False
        or metadata.get("resolved_region_field_contract_sha256")
        != file_sha256(contract_path)
        or metadata.get("resolved_region_field_semantic_sha256")
        != contract.get("semantic_sha256")
    ):
        raise ContractError("full-domain piecewise ideal-field identity differs")
    fields = semantic.get("fields_V_per_mm")
    if not isinstance(fields, Mapping):
        raise ContractError("full-domain field values are missing")
    modes = semantic.get("region_modes")
    if not isinstance(modes, Mapping) or modes.get("drift") != "zero_field":
        raise ContractError("full-domain drift field identity differs")
    for region in (
        "accelerator_stage1", "accelerator_stage2",
        "reflectron_stage1", "reflectron_stage2",
    ):
        if _finite(fields.get(region), f"{region} field") == 0.0:
            raise ContractError(f"{region} ideal field is zero")
    return {
        "canonical_field_configuration_id": CANONICAL_FIELD_CONFIGURATION_ID,
        "domain": semantic["effective_domain"]["longitudinal"],
        "region_field_authority": dict(modes),
        "real_pa_field_blending_allowed": False,
        "reflectron_pa_semantics": (
            "geometry_and_collision_carrier_only_under_analytic_ideal_field_override"
        ),
    }


def _single_flight_ownership_lineage(
    *,
    child_manifest: Mapping[str, Any],
    child_config: Mapping[str, Any],
    expected_upstream_project_id: str,
) -> str:
    """Classify explicit current or read-only legacy single-flight ownership."""
    manifest_project = child_manifest.get("project")
    config_project = child_config.get("project")
    if manifest_project == PROJECT_ID and config_project == PROJECT_ID:
        if child_config.get("upstream_project_id") != expected_upstream_project_id:
            raise ContractError("integration-owned child upstream lineage differs")
        return "integration_owned_with_upstream_input_lineage"

    upstream_source_identity = child_config.get("upstream_source_identity")
    if (
        manifest_project == expected_upstream_project_id
        and config_project == expected_upstream_project_id
        and isinstance(upstream_source_identity, Mapping)
        and upstream_source_identity.get("project_id") == expected_upstream_project_id
    ):
        return "legacy_upstream_project_owned_single_flight_read_only"

    raise ContractError("single-flight child ownership lineage differs")


def _case(
    *, repo_root: Path, workspace_root: Path, parent_root: Path,
    experiment: Mapping[str, Any], campaign_id: str,
) -> dict[str, Any]:
    is_restart = experiment.get("source_release_mode") == "pre_pulse_restart"
    parent_manifest_path = parent_root / "run_manifest.json"
    parent_manifest = load_json(parent_manifest_path, "parent manifest")
    if any(
        parent_manifest.get(key) != value
        for key, value in {
            "schema_version": 2,
            "role": "simulation_run_manifest",
            "run_id": experiment["run_id"],
            "project": PROJECT_ID,
            "mode": "multipole_family_source_closure",
            "status": "success",
        }.items()
    ):
        raise ContractError("parent success-v2 identity differs")
    campaign_record = parent_manifest.get("inputs", {}).get("campaign")
    if not isinstance(campaign_record, dict):
        raise ContractError("parent campaign record differs")
    parent_verification = _verify_manifest_process(
        repo_root=repo_root, manifest_path=parent_manifest_path, status="success"
    )
    parent_verification_text = parent_verification.stdout + parent_verification.stderr
    if not is_restart:
        raise ContractError("full-domain assessment requires official pre-pulse restart")
    if parent_verification.returncode != 0:
        raise ContractError(
            "restart parent success-v2 manifest verification failed: "
            + parent_verification_text.strip()
        )
    parent_config_path = _verified(parent_manifest.get("run_config"), "parent run_config")
    parent_config = load_json(parent_config_path, "parent run_config")
    if (
        parent_config.get("formal_gate_passed") is not False
        or parent_manifest.get("formal_eligible") is not False
    ):
        raise ContractError("full-domain diagnostic parent must remain non-Formal")
    parent_summary_path = _output_named(parent_manifest, "summary.json", "parent")
    parent_summary = load_json(parent_summary_path, "parent summary")
    if (
        parent_summary.get("status") != "success"
        or parent_summary.get("campaign_id") != campaign_id
        or parent_summary.get("experiment_id") != experiment["experiment_id"]
        or parent_summary.get("experiment_row_sha256")
        != experiment["_frozen_row_sha256"]
    ):
        raise ContractError("parent summary campaign identity differs")
    child_manifest_path = _verified(
        parent_manifest.get("inputs", {}).get("single_flight_transport_manifest"),
        "child manifest",
    )
    child_manifest = load_json(child_manifest_path, "child manifest")
    if any(
        child_manifest.get(key) != value
        for key, value in {
            "schema_version": 2,
            "role": "simulation_run_manifest",
            "mode": "rf_to_oatof_simion_single_flight",
            "status": "success",
        }.items()
    ):
        raise ContractError("child success-v2 identity differs")
    child_verification = _verify_manifest_process(
        repo_root=repo_root, manifest_path=child_manifest_path, status="success"
    )
    if child_verification.returncode != 0:
        raise ContractError(
            "child success-v2 manifest verification failed: "
            + (child_verification.stdout + child_verification.stderr).strip()
        )
    child_config_path = _verified(child_manifest.get("run_config"), "child run_config")
    child_config = load_json(child_config_path, "child run_config")
    source_particle_identity = parent_config.get("source_particle_identity")
    if not isinstance(source_particle_identity, Mapping):
        raise ContractError("parent source particle identity is missing")
    upstream_project_id = source_particle_identity.get("project_id")
    if not isinstance(upstream_project_id, str) or not upstream_project_id:
        raise ContractError("parent upstream project identity is missing")
    child_ownership_lineage = _single_flight_ownership_lineage(
        child_manifest=child_manifest,
        child_config=child_config,
        expected_upstream_project_id=upstream_project_id,
    )
    if (
        child_config.get("formal_gate_passed") is not False
        or child_manifest.get("formal_eligible") is not False
    ):
        raise ContractError("full-domain diagnostic child must remain non-Formal")
    summary_path = _output_named(child_manifest, "summary.json", "child")
    checkpoint_path = _output_named(
        child_manifest, "single_flight_particle_checkpoints.csv", "child"
    )
    summary = load_json(summary_path, "child summary")
    if summary.get("status") != "success":
        raise ContractError("child summary status differs")
    if summary.get("census", {}).get("detector_crossing") != 1000:
        raise ContractError("child detector census differs")
    times, checkpoint_rows = _load_detector_times(checkpoint_path)
    checkpoint_census = _validate_registered_checkpoint_census(
        summary, checkpoint_rows
    )
    source_state = experiment.get("pre_pulse_source_state") if is_restart else None
    target_path = (
        workspace_root / str(source_state["path"])
        if isinstance(source_state, Mapping)
        else parent_root / "inputs" / "single_flight_pulse_target_state.csv"
    )
    receipt_path = (
        workspace_root / str(source_state["materialization_receipt"]["path"])
        if isinstance(source_state, Mapping)
        else parent_root / "inputs" / "single_flight_source_materialization_receipt.json"
    )
    receipt = load_json(receipt_path, "source materialization receipt")
    if (
        not target_path.is_file()
        or file_sha256(target_path)
        != (source_state.get("sha256") if isinstance(source_state, Mapping) else receipt.get("pulse_target_state", {}).get("sha256"))
        or (isinstance(source_state, Mapping) and file_sha256(receipt_path) != source_state["materialization_receipt"]["sha256"])
    ):
        raise ContractError("registered pulse target identity differs")
    cache_names = (
        "frontend_pa_cache_manifest",
        "accelerator_overlay_pa_cache_manifest",
        "flight_tube_pa_cache_manifest",
    )
    cache = {}
    for name in cache_names:
        path = child_config.get("inputs", {}).get(name)
        if not isinstance(path, str):
            raise ContractError(f"{name} is missing")
        manifest = load_json(Path(path), name)
        cache[name] = {
            "cache_key": manifest.get("cache_key"),
            "provider_run_id": manifest.get("provider_run_id"),
            "sha256": file_sha256(Path(path)),
        }
    return {
        "experiment_id": experiment["experiment_id"],
        "registered_source_profile_id": experiment["source_profile_id"],
        "canonical_field_configuration_id": CANONICAL_FIELD_CONFIGURATION_ID,
        "observed_population_label": (
            "REGISTERED-PRE-PULSE-RESTART" if is_restart else "AT-ACTUAL-PULSE-STATE"
        ),
        "parent_run": {
            "run_id": experiment["run_id"],
            "path": parent_root.resolve().relative_to(workspace_root).as_posix(),
            "manifest_sha256": file_sha256(parent_manifest_path),
            "manifest_verification": (
                "PASS" if is_restart else "EXPECTED_FAILURE_ARCHIVED_CAMPAIGN_INPUT_NOT_BYTE_LIVE"
            ),
            "campaign_input_record": campaign_record,
        },
        "child_run": {
            "run_id": child_manifest["run_id"],
            "path": child_manifest_path.parent.relative_to(workspace_root).as_posix(),
            "manifest_sha256": file_sha256(child_manifest_path),
            "ownership_lineage": child_ownership_lineage,
        },
        "pulse_effective_metrics": _pulse_metrics(summary, times),
        "field_configuration": _path_free_field_identity(child_manifest),
        "census": checkpoint_census,
        "source_release_identity": _source_release_errors(
            target_path,
            checkpoint_rows,
            summary.get("pre_pulse_restart_source_release_validation") if is_restart else None,
        ),
        "pa_cache": cache,
        "resource_usage": _batch_resource_usage(child_manifest, child_config),
    }


def compute_assessment(
    *, repo_root: Path, workspace_root: Path, campaign_path: Path
) -> dict[str, Any]:
    campaign = load_json(campaign_path, "campaign")
    validate_schema(campaign, "rf_multipole_oatof_experiment_campaign.schema.json")
    from .prepare import validate_full_domain_affine_width_numerics_campaign

    integration_root = repo_root / "integrations" / PROJECT_ID
    single_flight = load_json(
        integration_root / "config" / "simion_single_flight.json",
        "single-flight configuration",
    )
    policy = load_json(
        integration_root / "config" / "execution_policy.json",
        "execution policy",
    )
    validate_full_domain_affine_width_numerics_campaign(
        campaign, single_flight, policy, repo_root
    )
    campaign_id = str(campaign.get("campaign_id"))
    if campaign.get("status") != "authorized":
        raise ContractError("full-domain assessment campaign must be authorized")
    row_hashes = campaign.get("preregistration", {}).get("frozen_experiment_row_sha256", {})
    runs_root = workspace_root / "artifacts" / "projects" / PROJECT_ID / "runs"
    cases = []
    for experiment in sorted(campaign["experiments"], key=lambda row: row["sequence"]):
        row = dict(experiment)
        row["_frozen_row_sha256"] = row_hashes.get(row["experiment_id"])
        cases.append(
            _case(
                repo_root=repo_root,
                workspace_root=workspace_root,
                parent_root=runs_root / row["run_id"],
                experiment=row,
                campaign_id=campaign_id,
            )
        )
    if len(cases) != 5:
        raise ContractError("full-domain assessment requires exactly five registered rows")
    by_id = {case["experiment_id"]: case for case in cases}
    ordered_ids = [row["experiment_id"] for row in sorted(campaign["experiments"], key=lambda row: row["sequence"])]
    width_ids = tuple(ordered_ids[:3])
    dt_id, q_id = ordered_ids[3:]
    sigma = {
        experiment_id: by_id[experiment_id]["pulse_effective_metrics"]["population_sigma_tof_ns"]
        for experiment_id in (*width_ids, dt_id, q_id)
    }
    delta_width = sigma[width_ids[2]] - sigma[width_ids[0]]
    width_ratio = sigma[width_ids[2]] / sigma[width_ids[0]]
    width_monotonic = sigma[width_ids[0]] < sigma[width_ids[1]] < sigma[width_ids[2]]
    dt_change = abs(sigma[dt_id] - sigma[width_ids[2]])
    q_change = abs(sigma[q_id] - sigma[width_ids[2]])
    numerical_limit = 0.10 * delta_width
    widths = np.asarray([1.0, 1.5, 2.2], dtype=float)
    width_sigmas = np.asarray([sigma[name] for name in width_ids], dtype=float)
    slope = float(np.polyfit(np.log(widths), np.log(width_sigmas), 1)[0])
    source_identity_passed = all(
        case["source_release_identity"]["status"] == "PASS" for case in cases
    )
    field_configurations = [case["field_configuration"] for case in cases]
    if any(value != field_configurations[0] for value in field_configurations[1:]):
        raise ContractError("five-cell semantic field identities differ")
    diagnostic = {
        "width_population_sigma_monotonic": width_monotonic,
        "width_sigma_ratio_2p2_over_1": width_ratio,
        "width_sigma_ratio_threshold": 5.0,
        "delta_width_population_sigma_ns": delta_width,
        "dt320_absolute_sigma_change_ns": dt_change,
        "q108_absolute_sigma_change_ns": q_change,
        "numerical_change_limit_ns": numerical_limit,
        "dt320_change_fraction_of_delta_width": dt_change / delta_width,
        "q108_change_fraction_of_delta_width": q_change / delta_width,
        "descriptive_log_sigma_width_slope": slope,
        "width_response_thresholds_passed": width_monotonic and width_ratio >= 5.0,
        "numerical_robustness_threshold_passed": max(dt_change, q_change) <= numerical_limit,
    }
    claim_status = _claim_status(
        source_identity_passed=source_identity_passed,
        width_passed=diagnostic["width_response_thresholds_passed"],
        numerical_passed=diagnostic["numerical_robustness_threshold_passed"],
    )
    claim_passed = claim_status.startswith("SUPPORTED_")
    artifact_success = source_identity_passed
    if claim_passed:
        claim_limit = (
            "The result is limited to the registered 1.0--2.2 mm width range and "
            "the fixed long-focus FULL_DOMAIN_PIECEWISE_IDEAL_FIELD geometry/field "
            "contract; the log slope is descriptive and does not by itself identify "
            "a unique polynomial term. This experiment is non-Formal."
        )
    elif claim_status == "WIDTH_NOT_SUPPORTED":
        claim_limit = (
            "The registered source identity and numerical checks are evaluable, but "
            "the preregistered nonlinear width-response thresholds are not satisfied."
        )
    elif claim_status == "INCONCLUSIVE_NUMERICAL":
        claim_limit = (
            "The registered width response is not separable from the preregistered "
            "time-step/trajectory-quality sensitivity limit."
        )
    else:
        claim_limit = (
            "The solver outputs are retained only as identity-invalid diagnostics; "
            "width and numerical trends do not qualify the registered-source claim."
        )
    return {
        "schema_version": 1,
        "role": SUMMARY_ROLE,
        "status": "success" if artifact_success else "failed",
        "claim_status": claim_status,
        "failure_reasons": [] if artifact_success else [
            "SOURCE_IDENTITY_MISMATCH", "HISTORICAL_CAMPAIGN_INPUT_NOT_BYTE_LIVE"
        ],
        "campaign": {
            "campaign_id": campaign_id,
            "path": campaign_path.resolve().relative_to(workspace_root).as_posix(),
            "sha256": repository_text_sha256(campaign_path),
        },
        "clock_authority": {
            "metric_object": "pulse_effective_peak",
            "resolution_time_basis": EXPECTED_CLOCK,
            "instrument_clock_peak_allowed_for_resolution": False,
        },
        "field_configuration": field_configurations[0],
        "registered_source": {
            "source_identity_gate_passed": source_identity_passed,
            "width_and_numerics_thresholds": diagnostic,
            "claim_status": claim_status,
        },
        "cases": cases,
        "formal_gate_passed": False,
        "threshold_result_eligible": source_identity_passed,
        "claim_limit": claim_limit,
    }


def _report(assessment: Mapping[str, Any]) -> str:
    lines = [
        "# Full-domain affine five-cell assessment",
        "",
        f"Claim: `{assessment['claim_status']}`; artifact status: `{assessment['status']}`; "
        "Formal eligibility: `false`.",
        "",
        "All resolution values below use the sole registered authority "
        "`pulse_effective_peak`; `instrument_clock_peak` is prohibited.",
        "",
        "| Cell | Observed population | sigma (ns) | direct FWHM (ns) | R | modes | detector |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for case in assessment["cases"]:
        metric = case["pulse_effective_metrics"]
        lines.append(
            f"|`{case['experiment_id']}`|`{case['observed_population_label']}`|"
            f"{metric['population_sigma_tof_ns']:.12g}|{metric['direct_fwhm_tof_ns']:.12g}|"
            f"{metric['mass_resolution']:.12g}|{metric['significant_kde_modes']}|"
            f"{case['census']['detector_crossing']}/1000|"
        )
    diagnostic = assessment["registered_source"]["width_and_numerics_thresholds"]
    claim_status = assessment["claim_status"]
    if str(claim_status).startswith("SUPPORTED_"):
        interpretation = (
            "All registered restart-source identity and census gates pass. The monotonic "
            "width response is much larger than the dt/q sensitivity under the fixed "
            "field contract, supporting strong nonlinear residual width dependence."
        )
    elif claim_status == "WIDTH_NOT_SUPPORTED":
        interpretation = "The registered nonlinear width-response threshold is not satisfied."
    elif claim_status == "INCONCLUSIVE_NUMERICAL":
        interpretation = "Numerical sensitivity is too large to separate from the width response."
    else:
        interpretation = (
            "The actual pulse states fail the preregistered source identity gate; "
            "width and numerical trends remain diagnostic only."
        )
    lines += [
        "",
        interpretation,
        "",
        f"Observed width ratio: {diagnostic['width_sigma_ratio_2p2_over_1']:.12g}; "
        f"log slope: {diagnostic['descriptive_log_sigma_width_slope']:.12g}; "
        f"dt fraction: {diagnostic['dt320_change_fraction_of_delta_width']:.12g}; "
        f"q fraction: {diagnostic['q108_change_fraction_of_delta_width']:.12g}.",
        "",
    ]
    return "\n".join(lines)


def _analysis_run_id(campaign: Mapping[str, Any]) -> str:
    final_stamp = str(max(campaign["experiments"], key=lambda row: row["sequence"])["run_id"])[:15]
    moment = datetime.strptime(final_stamp, "%Y%m%d_%H%M%S") + timedelta(minutes=5)
    return moment.strftime("%Y%m%d_%H%M%S") + "__analysis__python__full-domain-affine-width-numerics__n1000"


def is_full_domain_width_numerics_campaign(campaign: Mapping[str, Any]) -> bool:
    """Identify the terminal assessment from canonical experiment semantics."""

    experiments = campaign.get("experiments")
    if not isinstance(experiments, list) or len(experiments) != 5:
        return False
    expected = {
        ("canonical_ideal_linear_z_vz_1mm_n1000", "tqual_8", "dt160"),
        ("canonical_ideal_linear_z_vz_1p5mm_n1000", "tqual_8", "dt160"),
        ("canonical_ideal_linear_z_vz_2p2mm_n1000", "tqual_8", "dt160"),
        ("canonical_ideal_linear_z_vz_2p2mm_n1000", "tqual_8", "dt320"),
        ("canonical_ideal_linear_z_vz_2p2mm_n1000", "tqual_108", "dt160"),
    }
    observed = {
        (
            row.get("single_flight_source_materialization_profile_id"),
            row.get("single_flight_trajectory_quality_profile_id"),
            row.get("single_flight_time_integration_profile_id"),
        )
        for row in experiments
        if isinstance(row, Mapping)
    }
    return (
        campaign.get("status") == "authorized"
        and observed == expected
        and all(
            row.get("source_release_mode") == "pre_pulse_restart"
            and row.get("single_flight_accelerator_field_profile_id")
            == "full_domain_piecewise_ideal_field"
            for row in experiments
        )
    )


def publish_completed_assessment(
    *, repo_root: Path, workspace_root: Path, campaign_path: Path
) -> Path | None:
    campaign = load_json(campaign_path, "campaign")
    if not is_full_domain_width_numerics_campaign(campaign):
        return None
    campaign_id = str(campaign["campaign_id"])
    run_id = _analysis_run_id(campaign)
    run_dir = workspace_root / "artifacts" / "projects" / PROJECT_ID / "runs" / run_id
    if run_dir.exists():
        raise ContractError(f"assessment run already exists: {run_id}")
    run_dir.mkdir(parents=True)
    config_path = run_dir / "run_config.json"
    summary_path = run_dir / "summary.json"
    report_path = run_dir / "results" / "assessment.md"
    manifest_path = run_dir / "run_manifest.json"
    manifest_pending = run_dir / ".run_manifest.json.pending"
    parent_runs_root = (
        workspace_root / "artifacts" / "projects" / PROJECT_ID / "runs"
    )
    input_paths = {"campaign": campaign_path}
    for experiment in campaign["experiments"]:
        experiment_id = str(experiment["experiment_id"])
        parent_manifest_path = (
            parent_runs_root / str(experiment["run_id"]) / "run_manifest.json"
        )
        parent_manifest = load_json(parent_manifest_path, "parent manifest")
        parent_config_path = _verified(
            parent_manifest.get("run_config"), "parent run_config"
        )
        child_manifest_path = _verified(
            parent_manifest.get("inputs", {}).get("single_flight_transport_manifest"),
            "child manifest",
        )
        child_manifest = load_json(child_manifest_path, "child manifest")
        child_config_path = _verified(
            child_manifest.get("run_config"), "child run_config"
        )
        field_contract_path = child_config_path.parent / "inputs" / "resolved_region_field_contract.json"
        if not field_contract_path.is_file():
            raise ContractError("global field contract input is missing")
        input_paths[f"parent_manifest__{experiment_id}"] = parent_manifest_path
        input_paths[f"parent_run_config__{experiment_id}"] = parent_config_path
        input_paths[f"child_manifest__{experiment_id}"] = child_manifest_path
        input_paths[f"child_run_config__{experiment_id}"] = child_config_path
        input_paths[f"field_contract__{experiment_id}"] = field_contract_path
    frozen = freeze_repository_inputs(
        input_paths, repo_root=repo_root, run_dir=run_dir
    )
    run_config = {
        "schema_version": 2,
        "run_id": run_id,
        "project": PROJECT_ID,
        "mode": MODE,
        "project_root": str(workspace_root.resolve()),
        "inputs": {
            name: str(path.resolve()) for name, path in sorted(frozen.items())
        },
        "campaign_id": campaign_id,
        "artifact_retention": {"policy_version": 1, "class": "compact", "reason": None},
        "formal_gate_passed": False,
    }
    write_pending_json(config_path, run_config)
    interrupted = {
        "schema_version": 1,
        "role": SUMMARY_ROLE,
        "status": "interrupted",
        "claim_status": "NOT_RUN",
        "formal_gate_passed": False,
    }
    write_pending_json(summary_path, interrupted)
    publish_manifest(
        repo_root=repo_root,
        run_config=config_path,
        manifest_path=manifest_pending,
        status="interrupted",
        outputs=(summary_path,),
        project=PROJECT_ID,
        mode=MODE,
        label="full-domain width/numerics assessment",
    )
    os.replace(manifest_pending, manifest_path)
    interrupted_summary = summary_path.read_bytes()
    interrupted_manifest = manifest_path.read_bytes()
    try:
        assessment = compute_assessment(
            repo_root=repo_root,
            workspace_root=workspace_root,
            campaign_path=campaign_path,
        )
        write_pending_json(summary_path, assessment)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        pending_report = report_path.with_name(".assessment.md.pending")
        pending_report.write_text(_report(assessment), encoding="utf-8")
        os.replace(pending_report, report_path)
        publish_manifest(
            repo_root=repo_root,
            run_config=config_path,
            manifest_path=manifest_pending,
            status=str(assessment["status"]),
            outputs=(summary_path, report_path),
            project=PROJECT_ID,
            mode=MODE,
            label="full-domain width/numerics assessment",
        )
        os.replace(manifest_pending, manifest_path)
        return manifest_path
    except (KeyboardInterrupt, SystemExit):
        restore_interrupted(
            summary_path=summary_path,
            manifest_path=manifest_path,
            manifest_pending=manifest_pending,
            summary_bytes=interrupted_summary,
            manifest_bytes=interrupted_manifest,
        )
        raise
    except Exception as error:
        failed = {
            "schema_version": 1,
            "role": SUMMARY_ROLE,
            "status": "failed",
            "claim_status": "INVALID_IDENTITY_OR_CENSUS",
            "reason": str(error),
            "failure_stage": "governed_five_cell_assessment",
            "formal_gate_passed": False,
        }
        terminalize_failure(
            publish=lambda **kwargs: publish_manifest(
                **kwargs, project=PROJECT_ID, mode=MODE,
                label="full-domain width/numerics assessment"
            ),
            repo_root=repo_root,
            run_config_path=config_path,
            summary_path=summary_path,
            manifest_path=manifest_path,
            manifest_pending=manifest_pending,
            failed_summary=failed,
            candidate_outputs=(summary_path, report_path),
            interrupted_summary_bytes=interrupted_summary,
            interrupted_manifest_bytes=interrupted_manifest,
        )
        raise
