"""Analyze preregistered ZERO-MATCH stage-A evidence without running a solver."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import load_json, validate_schema
from common.contracts.verify_run_manifest import record_path
from common.multipole.compile_design_request import canonical_sha256
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.analyze_stage_field_2x2 import (
    _bound_output_record,
    _verify_success_v2_manifest,
)
from common.analysis.peak_metrics import (
    compute_peak_metrics,
)


WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
INTEGRATION_SCHEMA_DIR = Path(__file__).resolve().parents[1] / "config" / "schemas"
EVENTS = (
    "accelerator_focus_forward",
    "reflectron_entrance_forward",
    "detector_crossing",
)
REQUIRED_STATE_COLUMNS = {
    "particle_id",
    "instrument_time_us",
    "mass_amu",
    "charge_state",
    "position_x_mm",
    "position_y_mm",
    "position_z_mm",
    "velocity_x_m_s",
    "velocity_y_m_s",
    "velocity_z_m_s",
    "kinetic_energy_eV",
}
REQUIRED_CHECKPOINT_COLUMNS = {
    "particle_id",
    "event",
    "instrument_time_us",
    "pulse_effective_elapsed_us",
}


def _bound_file(root: Path, record: Mapping[str, Any], label: str) -> Path:
    """Resolve and verify a campaign-bound file record."""

    resolved_root = root.resolve()
    path = (resolved_root / str(record["path"])).resolve()
    if not path.is_relative_to(resolved_root):
        raise ValueError(f"{label} escapes the declared workspace root: {path}")
    if not path.is_file():
        raise ValueError(f"{label} is missing: {path}")
    if path.stat().st_size != int(record["bytes"]):
        raise ValueError(f"{label} byte count differs: {path}")
    if file_sha256(path) != str(record["sha256"]).upper():
        raise ValueError(f"{label} SHA-256 differs: {path}")
    return path


def _require_workspace_path(path: Path, root: Path, label: str) -> Path:
    """Require a manifest-resolved path to remain inside the workspace."""

    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"{label} escapes the declared workspace root: {resolved}")
    return resolved


def _require_named_record(
    manifest: Mapping[str, Any],
    manifest_path: Path,
    category: str,
    name: str,
    expected_path: Path,
    expected_record: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Require one named verified manifest record to match the campaign record."""

    container = manifest.get(category)
    if not isinstance(container, Mapping) or name not in container:
        raise ValueError(f"manifest lacks {category}.{name}")
    record = container[name]
    if record_path(record, base_dir=manifest_path.parent) != expected_path.resolve():
        raise ValueError(f"manifest {category}.{name} path differs")
    if int(record.get("bytes", -1)) != int(expected_record["bytes"]):
        raise ValueError(f"manifest {category}.{name} byte count differs")
    if str(record.get("sha256", "")).upper() != str(expected_record["sha256"]).upper():
        raise ValueError(f"manifest {category}.{name} SHA-256 differs")
    return record


def _integration_summary(
    manifest: Mapping[str, Any], manifest_path: Path, workspace_root: Path
) -> Mapping[str, Any]:
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list) or len(outputs) != 1:
        raise ValueError("integration evidence manifest must bind exactly one summary output")
    summary_path = _require_workspace_path(
        record_path(outputs[0], base_dir=manifest_path.parent),
        workspace_root,
        "integration summary",
    )
    return load_json(summary_path)


def _transport_summary(
    manifest: Mapping[str, Any], manifest_path: Path, workspace_root: Path
) -> Mapping[str, Any]:
    """Load the unique manifest-bound transport summary."""

    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        raise ValueError("transport evidence manifest lacks outputs")
    records = [
        record for record in outputs
        if Path(str(record.get("path", ""))).name.casefold() == "summary.json"
    ]
    if len(records) != 1:
        raise ValueError("transport evidence manifest must bind exactly one summary.json")
    path = _require_workspace_path(
        record_path(records[0], base_dir=manifest_path.parent),
        workspace_root,
        "transport summary",
    )
    return load_json(path)


def _transport_run_config(
    manifest: Mapping[str, Any], manifest_path: Path, workspace_root: Path
) -> Mapping[str, Any]:
    """Load the already manifest-verified transport run config."""

    record = manifest.get("run_config")
    if not isinstance(record, Mapping):
        raise ValueError("transport evidence manifest lacks run_config")
    path = _require_workspace_path(
        record_path(record, base_dir=manifest_path.parent),
        workspace_root,
        "transport run config",
    )
    return load_json(path)


def _strict_integer_particle_ids(values: Any, label: str) -> np.ndarray:
    """Reject fractional/nonfinite particle IDs instead of truncating them."""

    numeric = pd.to_numeric(values, errors="raise").to_numpy(dtype=float)
    if (
        numeric.ndim != 1
        or not np.all(np.isfinite(numeric))
        or np.any(np.abs(numeric) > np.iinfo(np.int64).max)
        or not np.array_equal(numeric, np.rint(numeric))
    ):
        raise ValueError(f"{label} must contain exact finite integer particle IDs")
    return np.rint(numeric).astype(np.int64)


def _require_finite_error_within_tolerance(
    validation: Mapping[str, Any], observed_key: str, tolerance_key: str, label: str
) -> None:
    """Fail closed on nonfinite or invalid source-release error bounds."""

    observed = float(validation.get(observed_key, float("nan")))
    tolerance = float(validation.get(tolerance_key, float("nan")))
    if (
        not math.isfinite(observed)
        or not math.isfinite(tolerance)
        or observed < 0.0
        or tolerance < 0.0
        or observed > tolerance
    ):
        raise ValueError(f"{label} transport source-release tolerance differs")


def _load_evidence_run(
    root: Path,
    label: str,
    contract: Mapping[str, Any],
    expected_count: int,
    clock_tolerance_us: float,
    source_physics: Mapping[str, Any],
    transport_identity: Mapping[str, Any],
) -> dict[str, Any]:
    """Load one manifest-bound ZERO-MATCH source and checkpoint population."""

    integration_manifest_path = _bound_file(
        root, contract["integration_manifest"], f"{label} integration manifest"
    )
    transport_manifest_path = _bound_file(
        root, contract["transport_manifest"], f"{label} transport manifest"
    )
    integration_manifest = _verify_success_v2_manifest(integration_manifest_path)
    transport_manifest = _verify_success_v2_manifest(transport_manifest_path)
    if integration_manifest.get("run_id") != contract["expected_integration_run_id"]:
        raise ValueError(f"{label} integration run identity differs")
    if transport_manifest.get("run_id") != contract["expected_transport_run_id"]:
        raise ValueError(f"{label} transport run identity differs")
    linked_transport = integration_manifest.get("inputs", {}).get(
        "single_flight_transport_manifest"
    )
    if not isinstance(linked_transport, Mapping):
        raise ValueError(f"{label} integration manifest lacks transport link")
    if (
        record_path(linked_transport, base_dir=integration_manifest_path.parent)
        != transport_manifest_path
    ):
        raise ValueError(f"{label} integration-to-transport path differs")
    if str(linked_transport.get("sha256", "")).upper() != file_sha256(
        transport_manifest_path
    ):
        raise ValueError(f"{label} integration-to-transport SHA-256 differs")
    integration_summary = _integration_summary(
        integration_manifest, integration_manifest_path, root
    )
    if (
        integration_summary.get("status") != "success"
        or integration_summary.get("experiment_id") != contract["expected_experiment_id"]
        or integration_summary.get("particle_count") != expected_count
    ):
        raise ValueError(f"{label} integration summary identity differs")
    integration_census = integration_summary.get("census")
    if not isinstance(integration_census, Mapping) or any(
        int(integration_census.get(event, -1)) != expected_count
        for event in ("source_release", *EVENTS)
    ):
        raise ValueError(f"{label} integration summary census differs")

    transport_summary = _transport_summary(
        transport_manifest, transport_manifest_path, root
    )
    transport_census = transport_summary.get("census")
    source_validation = transport_summary.get(
        "pre_pulse_restart_source_release_validation"
    )
    if (
        transport_summary.get("role") != "rf_oatof_simion_single_flight_summary"
        or transport_summary.get("status") != "success"
        or transport_summary.get("resolution_time_basis")
        != "detector_time_minus_pulse_effective_time"
        or not isinstance(transport_census, Mapping)
        or any(
            int(transport_census.get(event, -1)) != expected_count
            for event in ("source_release", "pre_pulse_state", *EVENTS)
        )
        or not isinstance(source_validation, Mapping)
        or source_validation.get("status") != "PASS"
        or source_validation.get("checkpoint") != "source_release"
        or int(source_validation.get("particle_count", -1)) != expected_count
        or source_validation.get("ordered_particle_ids_exact") is not True
    ):
        raise ValueError(f"{label} transport summary source-release/census differs")
    for observed_key, tolerance_key in (
        ("maximum_position_rowwise_abs_error_mm", "position_rowwise_abs_tolerance_mm"),
        ("maximum_velocity_rowwise_abs_error_m_per_s", "velocity_rowwise_abs_tolerance_m_per_s"),
        ("maximum_clock_abs_error_us", "clock_abs_tolerance_us"),
        ("maximum_energy_abs_error_eV", "energy_abs_tolerance_eV"),
    ):
        _require_finite_error_within_tolerance(
            source_validation, observed_key, tolerance_key, label
        )

    transport_config = _transport_run_config(
        transport_manifest, transport_manifest_path, root
    )
    parameters = transport_config.get("parameters")
    if not isinstance(parameters, Mapping) or any(
        parameters.get(key) != expected_value
        for key, expected_value in transport_identity.items()
    ):
        raise ValueError(f"{label} transport field/layout/grid/numerics identity differs")

    paths = {
        key: _bound_file(root, contract[key], f"{label} {key}")
        for key in (
            "checkpoint_output",
            "initial_global_state_input",
            "mother_particle_source_input",
            "source_materialization_receipt_input",
        )
    }
    _bound_output_record(
        transport_manifest,
        transport_manifest_path,
        paths["checkpoint_output"],
    )
    for config_key, manifest_name in (
        ("initial_global_state_input", "initial_global_state"),
        ("mother_particle_source_input", "mother_particle_source"),
        (
            "source_materialization_receipt_input",
            "mother_particle_source_materialization_receipt",
        ),
    ):
        _require_named_record(
            transport_manifest,
            transport_manifest_path,
            "inputs",
            manifest_name,
            paths[config_key],
            contract[config_key],
        )

    receipt = load_json(paths["source_materialization_receipt_input"])
    expected_physics = source_physics
    receipt_physics = receipt.get("physics")
    pulse_target = receipt.get("pulse_target_state")
    if (
        receipt.get("role") != "rf_oatof_single_flight_source_materialization_receipt"
        or receipt.get("profile_id") != contract["expected_source_profile_id"]
        or receipt.get("source_profile_id") != contract["expected_source_profile_id"]
        or receipt.get("particle_count") != expected_count
        or float(receipt.get("source_full_width_mm", -1.0))
        != float(contract["source_full_width_mm"])
        or not isinstance(receipt_physics, Mapping)
        or any(
            receipt_physics.get(key) != expected_physics[key]
            for key in (
                "mass_amu", "charge_state", "kinetic_energy_eV",
                "mean_velocity_z_m_per_s", "velocity_z_slope_m_per_s_per_mm",
            )
        )
        or not isinstance(pulse_target, Mapping)
        or str(pulse_target.get("sha256", "")).upper()
        != str(contract["mother_particle_source_input"]["sha256"]).upper()
        or int(pulse_target.get("particle_count", -1)) != expected_count
        or pulse_target.get("source_state_epoch") != expected_physics["source_state_epoch"]
        or pulse_target.get("coordinate_frame") != expected_physics["coordinate_frame"]
        or pulse_target.get("clock_basis") != expected_physics["clock_basis"]
        or pulse_target.get("clock_authority") != "resolved_single_flight_pulse_schedule"
        or str(pulse_target.get("ordered_particle_id_sha256", "")).upper()
        != canonical_sha256(list(range(1, expected_count + 1)))
    ):
        raise ValueError(f"{label} source materialization identity differs")

    state = pd.read_csv(paths["initial_global_state_input"])
    checkpoints = pd.read_csv(paths["checkpoint_output"])
    if not REQUIRED_STATE_COLUMNS.issubset(state.columns):
        raise ValueError(f"{label} initial state lacks required columns")
    if not REQUIRED_CHECKPOINT_COLUMNS.issubset(checkpoints.columns):
        raise ValueError(f"{label} checkpoints lack required columns")
    state["particle_id"] = _strict_integer_particle_ids(
        state["particle_id"], f"{label} initial state"
    )
    checkpoints["particle_id"] = _strict_integer_particle_ids(
        checkpoints["particle_id"], f"{label} checkpoints"
    )
    expected_ids = np.arange(1, expected_count + 1, dtype=int)
    if (
        len(state) != expected_count
        or state["particle_id"].duplicated().any()
        or not np.array_equal(np.sort(state["particle_id"].to_numpy()), expected_ids)
    ):
        raise ValueError(f"{label} initial state must contain IDs 1..{expected_count}")
    state = state.sort_values("particle_id").reset_index(drop=True)
    numeric_state = state[sorted(REQUIRED_STATE_COLUMNS - {"particle_id"})].to_numpy(
        dtype=float
    )
    if not np.all(np.isfinite(numeric_state)):
        raise ValueError(f"{label} initial state contains nonfinite values")
    center_z = float(receipt["resolved_target_center_mm"][2])
    expected_width = float(contract["source_full_width_mm"])
    observed_width = float(state["position_z_mm"].max() - state["position_z_mm"].min())
    if not np.isclose(observed_width, expected_width, rtol=0.0, atol=1.0e-9):
        raise ValueError(f"{label} source z width differs")
    if not np.isclose(
        0.5 * (state["position_z_mm"].min() + state["position_z_mm"].max()),
        center_z,
        rtol=0.0,
        atol=1.0e-9,
    ):
        raise ValueError(f"{label} source z center differs")
    if np.max(np.abs(state["velocity_z_m_s"].to_numpy(dtype=float))) > 1.0e-6:
        raise ValueError(f"{label} is not a true-zero-vz source")
    if (
        not np.all(state["mass_amu"].to_numpy(dtype=float) == expected_physics["mass_amu"])
        or not np.all(
            state["charge_state"].to_numpy(dtype=float) == expected_physics["charge_state"]
        )
        or np.max(
            np.abs(
                state["kinetic_energy_eV"].to_numpy(dtype=float)
                - float(expected_physics["kinetic_energy_eV"])
            )
        ) > float(source_validation["energy_abs_tolerance_eV"])
    ):
        raise ValueError(f"{label} pulse-target particle physics differs")

    birth = state.set_index("particle_id")["instrument_time_us"].astype(float)
    times: dict[str, np.ndarray] = {}
    for event in EVENTS:
        rows = checkpoints.loc[
            checkpoints["event"].eq(event),
            ["particle_id", "instrument_time_us", "pulse_effective_elapsed_us"],
        ].copy()
        if (
            len(rows) != expected_count
            or rows["particle_id"].duplicated().any()
            or not np.array_equal(np.sort(rows["particle_id"].to_numpy()), expected_ids)
        ):
            raise ValueError(f"{label} event {event} must contain IDs 1..{expected_count}")
        rows = rows.sort_values("particle_id").set_index("particle_id")
        elapsed = rows["instrument_time_us"].astype(float) - birth
        recorded_elapsed = rows["pulse_effective_elapsed_us"].astype(float)
        if (
            not np.all(np.isfinite(elapsed))
            or not np.all(np.isfinite(recorded_elapsed))
            or np.max(np.abs(elapsed.to_numpy() - recorded_elapsed.to_numpy()))
            > clock_tolerance_us
        ):
            raise ValueError(f"{label} event {event} clock authority differs")
        times[event] = elapsed.to_numpy(dtype=float)
    return {
        "label": label,
        "state": state,
        "times_us": times,
        "source_center_z_mm": center_z,
        "source_full_width_mm": expected_width,
        "validation_receipts": {
            "source_release_status": source_validation["status"],
            "source_release_particle_count": int(source_validation["particle_count"]),
            "ordered_particle_ids_exact": source_validation["ordered_particle_ids_exact"],
            "checkpoint_census": {
                event: int(transport_census[event])
                for event in ("source_release", "pre_pulse_state", *EVENTS)
            },
            "pulse_target_state_sha256": pulse_target["sha256"],
            "source_physics": dict(expected_physics),
            "transport_identity": dict(transport_identity),
        },
        "provenance": {
            "integration_run_id": integration_manifest["run_id"],
            "integration_manifest": dict(contract["integration_manifest"]),
            "transport_run_id": transport_manifest["run_id"],
            "transport_manifest": dict(contract["transport_manifest"]),
            "checkpoint_output": dict(contract["checkpoint_output"]),
            "initial_global_state_input": dict(contract["initial_global_state_input"]),
            "mother_particle_source_input": dict(contract["mother_particle_source_input"]),
            "source_materialization_receipt_input": dict(
                contract["source_materialization_receipt_input"]
            ),
        },
    }


def _metric_summary(times_us: np.ndarray, mass_amu: float) -> dict[str, float | int]:
    peak, _ = compute_peak_metrics(times_us, mass_amu)
    return {
        "particle_count": int(len(times_us)),
        "mean_tof_us": float(np.mean(times_us)),
        "population_sigma_tof_ns": float(np.std(times_us, ddof=0) * 1.0e3),
        "central_80_percent_width_ns": float(
            (np.quantile(times_us, 0.9) - np.quantile(times_us, 0.1)) * 1.0e3
        ),
        "full_span_tof_ns": float(np.ptp(times_us) * 1.0e3),
        "significant_kde_modes": int(peak["significant_kde_modes"]),
    }


def cross_validated_global_polynomials(
    particle_ids: np.ndarray,
    source_offset_mm: np.ndarray,
    times_us: np.ndarray,
    fold_count: int,
    model_degrees: Sequence[int],
) -> dict[str, Any]:
    """Fit global polynomial reconstructions with strict particle-ID folds."""

    if not (
        len(particle_ids) == len(source_offset_mm) == len(times_us)
        and len(particle_ids) >= 20
    ):
        raise ValueError("polynomial inputs must have one nontrivial common population")
    raw_particle_ids = np.asarray(particle_ids)
    numeric_particle_ids = np.asarray(raw_particle_ids, dtype=float)
    if (
        numeric_particle_ids.ndim != 1
        or not np.all(np.isfinite(numeric_particle_ids))
        or not np.array_equal(numeric_particle_ids, np.rint(numeric_particle_ids))
    ):
        raise ValueError("polynomial particle IDs must be exact integers")
    particle_ids = np.rint(numeric_particle_ids).astype(np.int64)
    if len(set(particle_ids.tolist())) != len(particle_ids):
        raise ValueError("polynomial particle IDs must be unique")
    degrees = tuple(int(value) for value in model_degrees)
    if not degrees or 1 not in degrees or len(set(degrees)) != len(degrees):
        raise ValueError("global reconstruction requires unique degrees including M1")
    scale = float(np.max(np.abs(source_offset_mm)))
    if not np.isfinite(scale) or scale <= 0.0:
        raise ValueError("source offset scale must be finite and positive")
    coordinate = source_offset_mm / scale
    target_ns = times_us * 1.0e3
    models: dict[int, dict[str, Any]] = {}
    for degree in degrees:
        prediction = np.full(len(target_ns), np.nan)
        fold_rows = []
        for fold in range(fold_count):
            validation = particle_ids % fold_count == fold
            training = ~validation
            if np.count_nonzero(validation) == 0 or np.count_nonzero(training) <= degree:
                raise ValueError("particle-ID fold has insufficient rows")
            design = np.polynomial.polynomial.polyvander(coordinate, degree)
            coefficients = np.linalg.lstsq(
                design[training], target_ns[training], rcond=None
            )[0]
            predicted = design[validation] @ coefficients
            prediction[validation] = predicted
            residual = target_ns[validation] - predicted
            centered = target_ns[validation] - np.mean(target_ns[validation])
            sse = float(np.sum(residual**2))
            sst = float(np.sum(centered**2))
            fold_rows.append(
                {
                    "fold": fold,
                    "validation_count": int(np.count_nonzero(validation)),
                    "validation_particle_ids_sha256": canonical_sha256(
                        particle_ids[validation].astype(int).tolist()
                    ),
                    "coefficient_ns_per_normalized_coordinate_power": coefficients.tolist(),
                    "validation_sse_ns2": sse,
                    "validation_r_squared": 1.0 - sse / sst,
                    "validation_rmse_ns": float(np.sqrt(np.mean(residual**2))),
                }
            )
        if np.any(~np.isfinite(prediction)):
            raise ValueError("cross-validation did not predict every particle exactly once")
        residual = target_ns - prediction
        models[int(degree)] = {
            "degree": int(degree),
            "interpretation": "global_reconstruction_not_local_taylor_derivative",
            "folds": fold_rows,
            "out_of_fold_sse_ns2": float(np.sum(residual**2)),
            "out_of_fold_rmse_ns": float(np.sqrt(np.mean(residual**2))),
            "out_of_fold_residual_variance_ns2": float(np.var(residual, ddof=0)),
            "out_of_fold_prediction_sha256": canonical_sha256(prediction.tolist()),
        }
    m1 = models[1]
    target_variance = float(np.var(target_ns, ddof=0))
    nonlinear_fraction = m1["out_of_fold_residual_variance_ns2"] / target_variance
    result = {
        "coordinate": "source_position_z_mm_minus_materialized_source_center_scaled_by_half_span",
        "fold_assignment": "particle_id_modulo_5",
        "interpretation_limit": (
            "M1-M4 are global nonlinear reconstruction models; polynomial degree is not "
            "a local Taylor derivative order or a component attribution"
        ),
        "models": [models[degree] for degree in degrees],
        "nonlinear_variance_fraction_after_global_m1": nonlinear_fraction,
    }
    if 4 in models:
        m4 = models[4]
        result["m2_to_m4_captured_fraction_of_global_m1_sse"] = (
            1.0 - m4["out_of_fold_sse_ns2"] / m1["out_of_fold_sse_ns2"]
        )
        result["m4_better_than_m1_in_every_fold"] = all(
            m4_fold["validation_sse_ns2"] < m1_fold["validation_sse_ns2"]
            for m1_fold, m4_fold in zip(m1["folds"], m4["folds"], strict=True)
        )
    return result


def compute_stage_a_report(
    campaign_path: Path,
    *,
    workspace_root: Path = WORKSPACE_ROOT,
) -> dict[str, Any]:
    """Compute the pre-analysis-declared provisional ZERO-MATCH M1 screen."""

    resolved_workspace = workspace_root.resolve()
    resolved_campaign = campaign_path.resolve()
    if not resolved_campaign.is_relative_to(resolved_workspace):
        raise ValueError("stage-A campaign path escapes the declared workspace root")
    campaign = load_json(resolved_campaign)
    validate_schema(
        campaign,
        INTEGRATION_SCHEMA_DIR / "rf_oatof_zero_match_higher_order_stage_a_campaign.schema.json",
    )
    if tuple(campaign["checkpoint_events"]) != EVENTS:
        raise ValueError("campaign checkpoint order differs from the analysis API")
    count = int(campaign["particle_count"])
    tolerance = float(campaign["clock"]["elapsed_crosscheck_abs_tolerance_us"])
    runs = {
        label: _load_evidence_run(
            workspace_root,
            label,
            contract,
            count,
            tolerance,
            campaign["source_physics"],
            campaign["transport_identity"],
        )
        for label, contract in campaign["evidence_runs"].items()
    }
    full = runs["full_2p2mm"]
    contained = runs["contained_1mm"]
    full_state = full["state"]
    particle_ids = full_state["particle_id"].to_numpy(dtype=int)
    source_offset = (
        full_state["position_z_mm"].to_numpy(dtype=float)
        - float(full["source_center_z_mm"])
    )
    half_window = float(campaign["nested_window"]["full_width_mm"]) / 2.0
    nested = np.abs(source_offset) <= half_window + 1.0e-12
    if np.count_nonzero(nested) < 20 or np.count_nonzero(nested) >= count:
        raise ValueError("nested 1 mm source-coordinate window is invalid")

    metrics: dict[str, Any] = {}
    for event in EVENTS:
        metrics[event] = {
            "provisional_contained_1mm_run": _metric_summary(
                contained["times_us"][event], float(campaign["mass_amu"])
            ),
            "full_2p2mm_run": _metric_summary(
                full["times_us"][event], float(campaign["mass_amu"])
            ),
            "nested_1mm_window_from_full_2p2mm_run": _metric_summary(
                full["times_us"][event][nested], float(campaign["mass_amu"])
            ),
        }

    models = {
        event: cross_validated_global_polynomials(
            particle_ids,
            source_offset,
            full["times_us"][event],
            int(campaign["fold_policy"]["fold_count"]),
            tuple(int(value) for value in campaign["fold_policy"]["model_degrees"]),
        )
        for event in EVENTS
    }
    detector = models["detector_crossing"]
    stop_rule = campaign["stop_rule"]
    m1_fraction = float(
        detector["nonlinear_variance_fraction_after_global_m1"]
    )
    threshold_reference = stop_rule["threshold_reference"]
    threshold_prefix = "acceptance_thresholds."
    if not threshold_reference.startswith(threshold_prefix):
        raise ValueError("stage-A stop-rule threshold authority differs")
    threshold_key = threshold_reference.removeprefix(threshold_prefix)
    thresholds = campaign["acceptance_thresholds"]
    if threshold_key not in thresholds:
        raise ValueError("stage-A stop-rule threshold reference is unresolved")
    minimum = float(thresholds[threshold_key])
    stop_applied = m1_fraction < minimum
    status = (
        stop_rule["failure_status"]
        if stop_applied
        else "PROVISIONAL_M1_SCREEN_PASSED_CONTINUATION_REQUIRED"
    )
    allowed_claim = (
        stop_rule["allowed_claim"]
        if stop_applied
        else "GLOBAL_M1_RESIDUAL_THRESHOLD_PASSED_CONTINUATION_REQUIRED"
    )
    followup_status = (
        "NOT_EXECUTED_STOP_RULE" if stop_applied else "NOT_EXECUTED_NOT_AUTHORIZED"
    )
    return {
        "schema_version": 1,
        "role": "rf_oatof_zero_match_higher_order_stage_a_report",
        "status": status,
        "analysis_declaration": campaign["analysis_declaration"],
        "completion": "PARTIAL_NOT_COMPLETE_STAGE_A",
        "evidence_level": "PROVISIONAL",
        "solver_execution_performed": False,
        "campaign": {
            "path": str(resolved_campaign),
            "sha256": file_sha256(resolved_campaign),
        },
        "clock": dict(campaign["clock"]),
        "population_contract": {
            "full_particle_ids": "1..1000",
            "postselection_used": False,
            "nested_window_selection": "source_position_only_detector_blind",
            "nested_window_particle_count": int(np.count_nonzero(nested)),
            "nested_window_particle_ids_sha256": canonical_sha256(
                particle_ids[nested].tolist()
            ),
        },
        "evidence": {
            label: {
                "provenance": run["provenance"],
                "validation_receipts": run["validation_receipts"],
            }
            for label, run in runs.items()
        },
        "checkpoint_metrics": metrics,
        "full_2p2mm_global_reconstruction": models,
        "analysis_execution": {
            "global_m1_screen": "EXECUTED_PRIMARY_STOP_DECISION",
            "global_m2_to_m4_reconstruction": (
                "EXECUTED_EXPLORATORY_NOT_USED_FOR_STOP_DECISION"
            ),
            **{
                analysis: "NOT_EXECUTED_PARTIAL_STAGE_A"
                for analysis in campaign["declared_but_unexecuted_analyses"]
            },
        },
        "stop_gated_followup": {
            followup: followup_status for followup in campaign["stop_gated_followup"]
        },
        "preregistered_assessment": {
            "screen_metric": stop_rule["screen_metric"],
            "observed_global_m1_residual_variance_fraction": m1_fraction,
            "threshold_reference": threshold_reference,
            "minimum": minimum,
            "stop_rule_applied": stop_applied,
            "allowed_claim": allowed_claim,
            "exploratory_m2_to_m4_results": {
                "m2_to_m4_captured_fraction_of_global_m1_sse": detector[
                    "m2_to_m4_captured_fraction_of_global_m1_sse"
                ],
                "m4_better_than_m1_in_every_fold": detector[
                    "m4_better_than_m1_in_every_fold"
                ],
                "disposition": "EXECUTED_EXPLORATORY_NOT_USED_FOR_STOP_DECISION",
            },
            "complete_stage_a_claim": "withheld_partial_stop_rule_or_continuation_required",
            "higher_order_negation_claim": "withheld_global_m1_screen_cannot_negate_local_higher_order_behavior",
            "taylor_order_claim": "withheld_global_polynomial_degree_is_not_local_taylor_order",
            "component_attribution_claim": "withheld_stage_a_does_not_change_fields",
            "pure_cubic_reference": {
                "model": "uniform_symmetric_z_with_pure_z_cubed_timing_map",
                "global_m1_residual_variance_fraction": 0.16,
                "interpretation": (
                    "A pure cubic timing map can score only 0.16 on this global-M1 "
                    "metric because M1 absorbs its linear projection; failure of the "
                    "0.70 screen therefore does not exclude local cubic behavior."
                ),
            },
        },
        "claim_limit": campaign["claim_limit"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    report = compute_stage_a_report(arguments.campaign)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"ZERO_MATCH_HIGHER_ORDER_STAGE_A={report['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
