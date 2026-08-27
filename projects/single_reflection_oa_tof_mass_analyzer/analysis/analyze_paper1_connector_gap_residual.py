"""Compare OA-pre-pulse axial residuals across connector gaps without detector data.

This Paper 1 diagnostic compares governed OA pre-pulse source states from the
same root mother cohort.  The two-arm interface supports an integration-fixed
checkpoint.  The triplet interface additionally makes the evidence mode
explicit, so a pulse-disabled screening table can never be mislabeled as a
pulse-on fixed checkpoint.  It uses deterministic particle-ID roles:
development fits a ``v_z(z)`` model, validation selects its degree, and only
IDs present in both locked-test sets estimate a paired residual change.  The
common-ID statistic is a phase-space diagnostic, never a peak-width or
transmission result; each arm's full mother-cohort loss census is retained.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from projects.single_reflection_oa_tof_mass_analyzer.analysis.paper1_focusability import (
    FrozenPrePulseSource,
    assign_detector_blind_cohorts,
    load_frozen_pre_pulse_source,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.paper1_stage_evidence import (
    StageEvidence,
    publish_stage_evidence,
)


_DEGREES = (1, 2, 3)
_ROLES = ("development", "validation", "optimization", "locked_test")
_TRIPLET_GAPS_MM = (0.0, 51.2, 102.4)
_CHECKPOINT_KINDS = {"integration_fixed_pulse", "pulse_disabled_time_series"}
_TIME_SERIES_EQUIVALENCE_PROTOCOL = "resolved_pulse_epoch_state_equivalence_v1"
_DEFAULT_COHORT_ROLE_UPPER_BOUNDS = (
    ("development", 0.50),
    ("validation", 0.70),
    ("optimization", 0.85),
    ("locked_test", 1.00),
)


@dataclass(frozen=True)
class GovernedSource:
    """A detector-blind state source and its full-population census."""

    source: FrozenPrePulseSource
    state_path: Path
    receipt_path: Path
    mother_count: int
    screened_count: int
    checkpoint_kind: str
    screened_id_sha256: str | None = None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("time-series receipt must be a JSON object")
    return value


def load_governed_source(
    *, state_path: Path, receipt_path: Path, mother_count: int,
    screened_count: int, sample_index: int,
) -> GovernedSource:
    """Load one pulse-disabled source after validating its state-table receipt."""

    if mother_count < 1 or not 1 <= screened_count <= mother_count:
        raise ValueError("mother and screened population counts are invalid")
    receipt = _load_json(receipt_path)
    if (
        receipt.get("role") != "rf_oatof_pre_pulse_time_series_screening_receipt"
        or receipt.get("status") != "success"
        or receipt.get("pulse_disabled") is not True
    ):
        raise ValueError("source receipt is not a successful pulse-disabled screen")
    states = receipt.get("outputs", {}).get("states", {})
    if states.get("sha256") != _sha256(state_path):
        raise ValueError("source receipt does not bind the state table")
    census = receipt.get("sample_census")
    if not isinstance(census, list) or not 1 <= sample_index <= len(census):
        raise ValueError("source receipt lacks the selected sample")
    selected = census[sample_index - 1]
    if selected.get("sample_index") != sample_index:
        raise ValueError("source receipt selected sample differs")
    alive = selected.get("alive_count")
    missing = selected.get("missing_count")
    if not isinstance(alive, int) or not isinstance(missing, int) or alive + missing != screened_count:
        raise ValueError("source receipt census does not close against screened count")
    source = load_frozen_pre_pulse_source(
        state_path, time_series_sample_index=sample_index
    )
    if source.particle_ids.size != alive:
        raise ValueError("selected state count differs from the receipt census")
    return GovernedSource(
        source, state_path, receipt_path, mother_count, screened_count,
        "pulse_disabled_time_series", None,
    )


def _manifest_output_record(manifest: dict[str, Any], name: str) -> dict[str, Any]:
    records = [
        item for item in manifest.get("outputs", [])
        if isinstance(item, dict) and Path(str(item.get("path", ""))).name == name
    ]
    if len(records) != 1:
        raise ValueError(f"run manifest lacks one {name} output record")
    return records[0]


def load_fixed_pulse_checkpoint_source(
    *, state_path: Path, summary_path: Path, run_manifest_path: Path,
    mother_count: int, screened_count: int,
) -> GovernedSource:
    """Load one direct integration-pulse checkpoint with manifest binding.

    This is intentionally separate from the legacy pulse-disabled time-series
    reader.  The fixed checkpoint is valid only when the successful run summary
    and manifest bind it to the resolved pulse epoch and complete handoff
    population.  It never chooses an RF sample index.
    """

    if mother_count < 1 or not 1 <= screened_count <= mother_count:
        raise ValueError("mother and screened population counts are invalid")
    manifest = _load_json(run_manifest_path)
    if (
        manifest.get("role") != "simulation_run_manifest"
        or manifest.get("status") != "success"
    ):
        raise ValueError("fixed-pulse run manifest is not successful")
    output = _manifest_output_record(manifest, "single_flight_particle_checkpoints.csv")
    if output.get("sha256") != _sha256(state_path):
        raise ValueError("fixed-pulse run manifest does not bind the checkpoint table")
    summary = _load_json(summary_path)
    if (
        summary.get("role") != "rf_oatof_simion_single_flight_summary"
        or summary.get("status") != "success"
    ):
        raise ValueError("fixed-pulse summary is not successful")
    try:
        pulse_time_us = float(summary["pulse_effective_time_us"])
        census = summary["census"]
        observed = summary["observed_cohort_authority"]
        released = observed["source_release"]
        checkpoint = observed["pre_pulse_state"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("fixed-pulse summary lacks governed checkpoint census") from exc
    released_ids = released.get("ordered_particle_ids") if isinstance(released, dict) else None
    if (
        not isinstance(released_ids, list)
        or released_ids != sorted(set(released_ids))
        or len(released_ids) != screened_count
        or census.get("launched") != screened_count
        or released.get("count") != screened_count
    ):
        raise ValueError("fixed-pulse source-release census differs from screened count")
    screened_id_sha256 = hashlib.sha256(
        json.dumps(released_ids, separators=(",", ":")).encode("utf-8")
    ).hexdigest().upper()
    if released.get("ordered_particle_id_sha256") != screened_id_sha256:
        raise ValueError("fixed-pulse source-release identity differs")
    source = load_frozen_pre_pulse_source(state_path)
    if (
        not np.isclose(source.instrument_time_us, pulse_time_us, rtol=0.0, atol=1e-9)
        or checkpoint.get("count") != int(source.particle_ids.size)
        or census.get("pre_pulse_state") != int(source.particle_ids.size)
    ):
        raise ValueError("fixed-pulse checkpoint differs from summary")
    return GovernedSource(
        source, state_path, run_manifest_path, mother_count, screened_count,
        "integration_fixed_pulse", screened_id_sha256,
    )


def _fit_polynomial(z_mm: np.ndarray, vz_m_per_s: np.ndarray, degree: int) -> tuple[np.ndarray, float, float]:
    if degree not in _DEGREES or z_mm.size <= degree + 1:
        raise ValueError("axial polynomial fit is underdetermined")
    center = float(np.mean(z_mm))
    scale = float(np.std(z_mm))
    if not np.isfinite(scale) or scale <= np.finfo(float).eps:
        raise ValueError("axial coordinate has zero scale")
    features = np.vander((z_mm - center) / scale, N=degree + 1, increasing=True)
    coefficients, _, rank, _ = np.linalg.lstsq(features, vz_m_per_s, rcond=None)
    if rank != features.shape[1]:
        raise ValueError("axial polynomial fit is rank deficient")
    return coefficients, center, scale


def _predict_polynomial(z_mm: np.ndarray, fit: tuple[np.ndarray, float, float]) -> np.ndarray:
    coefficients, center, scale = fit
    features = np.vander((z_mm - center) / scale, N=coefficients.size, increasing=True)
    return features @ coefficients


def _select_model(
    z_development: np.ndarray, vz_development: np.ndarray,
    z_validation: np.ndarray, vz_validation: np.ndarray,
) -> tuple[int, tuple[np.ndarray, float, float], dict[str, float]]:
    scores: dict[str, float] = {}
    fits: dict[int, tuple[np.ndarray, float, float]] = {}
    for degree in _DEGREES:
        fit = _fit_polynomial(z_development, vz_development, degree)
        fits[degree] = fit
        residual = vz_validation - _predict_polynomial(z_validation, fit)
        scores[str(degree)] = float(np.mean(residual * residual))
    selected = min(_DEGREES, key=lambda degree: (scores[str(degree)], degree))
    return selected, fits[selected], scores


def _roles_by_id(
    ids: Iterable[int], *, salt: str, role_upper_bounds: tuple[tuple[str, float], ...],
) -> dict[int, str]:
    return {
        item.particle_id: item.role
        for item in assign_detector_blind_cohorts(
            ids, salt=salt, role_upper_bounds=role_upper_bounds,
        )
    }


def _arm_model(
    source: FrozenPrePulseSource, *, salt: str,
    role_upper_bounds: tuple[tuple[str, float], ...] = _DEFAULT_COHORT_ROLE_UPPER_BOUNDS,
) -> tuple[dict[int, str], int, tuple[np.ndarray, float, float], dict[str, float]]:
    roles = _roles_by_id(source.particle_ids, salt=salt, role_upper_bounds=role_upper_bounds)
    z_mm = source.state[:, 2]
    vz_m_per_s = source.state[:, 5]
    masks = {role: np.asarray([roles[int(identifier)] == role for identifier in source.particle_ids]) for role in _ROLES}
    if masks["development"].sum() < 8 or masks["validation"].sum() < 4:
        raise ValueError("source lacks sufficient detector-blind model-selection rows")
    degree, fit, scores = _select_model(
        z_mm[masks["development"]], vz_m_per_s[masks["development"]],
        z_mm[masks["validation"]], vz_m_per_s[masks["validation"]],
    )
    return roles, degree, fit, scores


def _locked_residuals(
    source: FrozenPrePulseSource, roles: dict[int, str],
    fit: tuple[np.ndarray, float, float], ids: list[int],
) -> np.ndarray:
    by_id = {int(identifier): index for index, identifier in enumerate(source.particle_ids)}
    if any(roles[identifier] != "locked_test" or identifier not in by_id for identifier in ids):
        raise ValueError("paired comparison IDs must be common locked-test source IDs")
    indices = np.asarray([by_id[identifier] for identifier in ids], dtype=int)
    return source.state[indices, 5] - _predict_polynomial(source.state[indices, 2], fit)


def _bootstrap_mean_difference(values: np.ndarray, *, replicates: int, seed: int) -> dict[str, float]:
    if replicates < 1 or values.size < 1:
        raise ValueError("bootstrap requires positive replicates and paired values")
    generator = np.random.default_rng(seed)
    indices = generator.integers(0, values.size, size=(replicates, values.size))
    samples = np.mean(values[indices], axis=1)
    return {
        "point_estimate": float(np.mean(values)),
        "lower_95": float(np.quantile(samples, 0.025)),
        "upper_95": float(np.quantile(samples, 0.975)),
    }


def compare_connector_gap_sources(
    *, first: GovernedSource, second: GovernedSource, cohort_salt: str,
    bootstrap_replicates: int, bootstrap_seed: int,
    role_upper_bounds: tuple[tuple[str, float], ...] = _DEFAULT_COHORT_ROLE_UPPER_BOUNDS,
) -> dict[str, Any]:
    """Return paired locked-test axial residual diagnostics for two connector gaps."""

    if first.mother_count != second.mother_count:
        raise ValueError("connector-gap comparison requires one shared mother count")
    if first.checkpoint_kind != second.checkpoint_kind:
        raise ValueError("connector-gap comparison cannot mix pre-pulse source modes")
    if (
        first.screened_id_sha256 is not None
        and second.screened_id_sha256 is not None
        and first.screened_id_sha256 != second.screened_id_sha256
    ):
        raise ValueError("connector-gap arms do not share one screened particle-ID cohort")
    first_roles, first_degree, first_fit, first_scores = _arm_model(
        first.source, salt=cohort_salt, role_upper_bounds=role_upper_bounds,
    )
    second_roles, second_degree, second_fit, second_scores = _arm_model(
        second.source, salt=cohort_salt, role_upper_bounds=role_upper_bounds,
    )
    common_locked_ids = sorted(
        set(first_roles).intersection(second_roles)
        & {identifier for identifier, role in first_roles.items() if role == "locked_test"}
        & {identifier for identifier, role in second_roles.items() if role == "locked_test"}
    )
    if len(common_locked_ids) < 32:
        raise ValueError("fewer than 32 common locked-test IDs cannot support the diagnostic")
    first_residual = _locked_residuals(first.source, first_roles, first_fit, common_locked_ids)
    second_residual = _locked_residuals(second.source, second_roles, second_fit, common_locked_ids)
    squared_difference = second_residual * second_residual - first_residual * first_residual
    paired = _bootstrap_mean_difference(
        squared_difference, replicates=bootstrap_replicates, seed=bootstrap_seed
    )
    first_mse = float(np.mean(first_residual * first_residual))
    second_mse = float(np.mean(second_residual * second_residual))
    return {
        "schema_version": 1,
        "role": "oatof_paper1_connector_gap_pre_pulse_residual_comparison",
        "qualification": "DETECTOR_BLIND_SOURCE_ONLY",
        "claim_limit": "Paired OA-pre-pulse phase-space diagnostic only; no detector, peak-width, transmission, optimization, Candidate, or Formal claim.",
        "cohort": {"salt": cohort_salt, "role_upper_bounds": dict(role_upper_bounds), "mother_count": first.mother_count, "common_locked_test_count": len(common_locked_ids), "common_locked_test_id_sha256": hashlib.sha256(json.dumps(common_locked_ids, separators=(",", ":")).encode("utf-8")).hexdigest().upper()},
        "arms": [
            {"state_table": {"path": str(item.state_path.resolve()), "sha256": _sha256(item.state_path)}, "evidence_receipt": {"path": str(item.receipt_path.resolve()), "sha256": _sha256(item.receipt_path)}, "checkpoint": {"kind": item.checkpoint_kind, "instrument_time_us": item.source.instrument_time_us}, "census": {"mother_count": item.mother_count, "screened_count": item.screened_count, "screened_particle_id_sha256": item.screened_id_sha256, "observed_pre_pulse_count": int(item.source.particle_ids.size), "unobserved_or_lost_count": item.mother_count - int(item.source.particle_ids.size)}, "selected_polynomial_degree": degree, "validation_mse_m2_per_s2": scores}
            for item, degree, scores in ((first, first_degree, first_scores), (second, second_degree, second_scores))
        ],
        "paired_locked_axial_residual": {"first_rms_m_per_s": float(np.sqrt(first_mse)), "second_rms_m_per_s": float(np.sqrt(second_mse)), "second_minus_first_mse_m2_per_s2": paired, "relative_mse_change": float(second_mse / first_mse - 1.0) if first_mse > 0.0 else None},
        "claims_supported": [
            (
                "The two arms use PRE_PULSE_EQUIVALENT OA-pre-pulse time-series states and deterministic ID roles."
                if first.checkpoint_kind == "pulse_disabled_time_series"
                else "The two arms use integration-fixed OA-pre-pulse states and deterministic ID roles."
            ),
            "The reported residual difference is evaluated only on common locked-test source IDs while each arm retains its full mother-cohort loss census.",
        ],
        "claims_prohibited": ["A common-ID residual statistic proves a peak-width, resolution, transmission, or connector-gap optimum.", "Observed residual change has a detector-level or engineering interpretation without the subsequent locked particle campaign."],
    }


def _resolve_config_path(value: Any, *, config_path: Path, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"triplet {field} must be a nonempty path string")
    path = Path(value)
    return path if path.is_absolute() else (config_path.parent / path).resolve()


def _role_upper_bounds_from_request(request: dict[str, Any]) -> tuple[tuple[str, float], ...]:
    if request["schema_version"] == 1:
        return _DEFAULT_COHORT_ROLE_UPPER_BOUNDS
    partition = request.get("cohort_partition")
    required = {"role", "development_upper_fraction", "validation_upper_fraction", "optimization_upper_fraction", "locked_test_upper_fraction"}
    if not isinstance(partition, dict) or set(partition) != required or partition["role"] != "detector_blind_hash_partition":
        raise ValueError("C1-v2 cohort partition fields differ from the contract")
    names = (
        ("development", "development_upper_fraction"),
        ("validation", "validation_upper_fraction"),
        ("optimization", "optimization_upper_fraction"),
        ("locked_test", "locked_test_upper_fraction"),
    )
    bounds = tuple((role, float(partition[field])) for role, field in names if isinstance(partition[field], (int, float)))
    if len(bounds) != 4:
        raise ValueError("C1-v2 cohort partition bounds must be numeric")
    try:
        assign_detector_blind_cohorts((1,), salt="partition-validation", role_upper_bounds=bounds)
    except ValueError as exc:
        raise ValueError(f"invalid C1-v2 cohort partition: {exc}") from exc
    return bounds


def _triplet_request(config_path: Path) -> dict[str, Any]:
    request = _load_json(config_path)
    required_v1 = {
        "schema_version", "role", "cohort_salt", "bootstrap_replicates",
        "bootstrap_seed", "required_checkpoint_kind", "arms",
    }
    required_v2 = required_v1 | {"cohort_partition"}
    if set(request) not in (required_v1, required_v2):
        raise ValueError("triplet request fields differ from the C1 contract")
    if (
        request["schema_version"] not in (1, 2)
        or request["role"] != "oatof_paper1_c1_connector_gap_triplet_request"
        or not isinstance(request["cohort_salt"], str)
        or not request["cohort_salt"]
        or not isinstance(request["bootstrap_replicates"], int)
        or request["bootstrap_replicates"] < 1
        or not isinstance(request["bootstrap_seed"], int)
        or request["required_checkpoint_kind"] not in _CHECKPOINT_KINDS
        or not isinstance(request["arms"], list)
        or len(request["arms"]) != 3
    ):
        raise ValueError("triplet request has invalid C1 values")
    if request["schema_version"] == 1 and set(request) != required_v1:
        raise ValueError("C1-v1 triplet request cannot define a cohort partition")
    if request["schema_version"] == 2 and set(request) != required_v2:
        raise ValueError("C1-v2 triplet request requires one cohort partition")
    _role_upper_bounds_from_request(request)
    return request


def _time_series_identity(receipt_path: Path, schedule_path: Path) -> dict[str, Any]:
    receipt = _load_json(receipt_path)
    identities = receipt.get("identities")
    required = {
        "mother_particle_source_sha256",
        "ordered_particle_id_sha256",
        "source_profile_id",
        "layout_profile_id",
        "architecture_generation_id",
        "candidate_sha256",
        "time_integration_profile_id",
        "field_profile_id",
        "region_field_semantic_sha256",
        "frontend_grid_profile_id",
        "oatof_numerical_profile_id",
        "trajectory_quality_profile_id",
    }
    if not isinstance(identities, dict) or not set(identities).issuperset(required):
        raise ValueError("time-series receipt lacks C1 common-identity fields")
    schedule = _load_json(schedule_path)
    source_state_sha256 = schedule.get("source_state_sha256")
    if not isinstance(source_state_sha256, str) or not source_state_sha256:
        raise ValueError("resolved pulse schedule lacks source-state identity")
    return {
        **{key: identities[key] for key in sorted(required)},
        "resolved_source_state_sha256": source_state_sha256.upper(),
    }


def _time_series_equivalence(
    *, receipt_path: Path, schedule_path: Path, sample_index: int,
) -> dict[str, Any]:
    """Prove one pulse-disabled state is the state immediately before its resolved epoch."""

    receipt = _load_json(receipt_path)
    schedule = _load_json(schedule_path)
    if schedule.get("role") != "rf_oatof_resolved_single_flight_pulse_schedule":
        raise ValueError("mode-equivalence schedule role differs")
    if receipt.get("pulse_disabled") is not True:
        raise ValueError("mode-equivalence receipt is not pulse disabled")
    sample_times = receipt.get("sample_times_us")
    census = receipt.get("sample_census")
    grid = receipt.get("rf_time_grid")
    if (
        not isinstance(sample_times, list)
        or not isinstance(census, list)
        or not isinstance(grid, dict)
        or not 1 <= sample_index <= len(sample_times)
        or len(census) != len(sample_times)
    ):
        raise ValueError("mode-equivalence receipt lacks selected epoch data")
    selected = census[sample_index - 1]
    sample_time = sample_times[sample_index - 1]
    pulse_time = schedule.get("pulse_effective_time_us")
    values = (sample_time, selected.get("instrument_time_us"), grid.get("grid_origin_us"), pulse_time)
    if not all(isinstance(value, (int, float)) and np.isfinite(value) for value in values):
        raise ValueError("mode-equivalence epoch is not finite")
    if not all(np.isclose(float(value), float(pulse_time), rtol=0.0, atol=1e-9) for value in values[:-1]):
        raise ValueError("time-series selected state is not bound to the resolved pulse epoch")
    identities = receipt.get("identities")
    if not isinstance(identities, dict):
        raise ValueError("mode-equivalence receipt lacks frozen identities")
    if schedule.get("layout_profile_id") != identities.get("layout_profile_id"):
        raise ValueError("time-series layout differs from the resolved pulse schedule")
    if schedule.get("source_state_sha256") is None or grid.get("frequency_hz") is None or grid.get("rf_steps_per_period") is None:
        raise ValueError("mode-equivalence evidence lacks source or RF identity")
    return {
        "label": "PRE_PULSE_EQUIVALENT",
        "protocol": _TIME_SERIES_EQUIVALENCE_PROTOCOL,
        "resolved_pulse_schedule": {"path": str(schedule_path.resolve()), "sha256": _sha256(schedule_path)},
        "pulse_effective_time_us": float(pulse_time),
        "selected_sample_index": sample_index,
        "rf": {
            "frequency_hz": float(grid["frequency_hz"]),
            "rf_steps_per_period": int(grid["rf_steps_per_period"]),
            "waveform": grid.get("waveform"),
        },
    }


def _fixed_pulse_identity(run_manifest_path: Path) -> dict[str, str]:
    manifest = _load_json(run_manifest_path)
    inputs = manifest.get("inputs")
    required = (
        "mother_particle_source",
        "three_zone_t5_candidate",
        "resolved_source_contract",
        "resolved_region_field_contract",
        "resolved_single_flight_execution_profile",
    )
    if not isinstance(inputs, dict):
        raise ValueError("fixed-pulse run manifest lacks C1 common-identity inputs")
    identity: dict[str, str] = {}
    for name in required:
        record = inputs.get(name)
        value = record.get("sha256") if isinstance(record, dict) else None
        if not isinstance(value, str) or not value:
            raise ValueError(f"fixed-pulse run manifest lacks {name} identity")
        identity[name] = value.upper()
    return identity


def _load_triplet_arm(
    arm: Any, *, config_path: Path, required_kind: str,
) -> tuple[float, GovernedSource, dict[str, Any]]:
    if not isinstance(arm, dict):
        raise ValueError("triplet arm must be an object")
    common = {"gap_mm", "checkpoint_kind", "mother_count", "screened_count"}
    kind = arm.get("checkpoint_kind")
    if kind not in _CHECKPOINT_KINDS:
        raise ValueError("triplet arm checkpoint kind differs")
    if kind != required_kind:
        raise ValueError("triplet arms must use the required uniform checkpoint kind")
    if not common.issubset(arm):
        raise ValueError("triplet arm lacks common C1 fields")
    gap_mm = arm["gap_mm"]
    if not isinstance(gap_mm, (int, float)) or not np.isfinite(gap_mm):
        raise ValueError("triplet arm gap must be finite")
    mother_count = arm["mother_count"]
    screened_count = arm["screened_count"]
    if not isinstance(mother_count, int) or not isinstance(screened_count, int):
        raise ValueError("triplet arm population counts must be integers")
    state_path = _resolve_config_path(arm.get("state_table"), config_path=config_path, field="state_table")
    if kind == "integration_fixed_pulse":
        required = common | {"state_table", "summary", "run_manifest"}
        if set(arm) != required:
            raise ValueError("fixed-pulse triplet arm fields differ")
        source = load_fixed_pulse_checkpoint_source(
            state_path=state_path,
            summary_path=_resolve_config_path(arm["summary"], config_path=config_path, field="summary"),
            run_manifest_path=_resolve_config_path(arm["run_manifest"], config_path=config_path, field="run_manifest"),
            mother_count=mother_count,
            screened_count=screened_count,
        )
        return float(gap_mm), source, {"identity": _fixed_pulse_identity(
            _resolve_config_path(arm["run_manifest"], config_path=config_path, field="run_manifest")
        )}
    required = common | {
        "state_table", "time_series_receipt", "sample_index", "resolved_pulse_schedule",
        "equivalence_protocol",
    }
    if set(arm) != required:
        raise ValueError("time-series triplet arm fields differ")
    receipt_path = _resolve_config_path(
        arm["time_series_receipt"], config_path=config_path, field="time_series_receipt"
    )
    sample_index = arm["sample_index"]
    if not isinstance(sample_index, int):
        raise ValueError("time-series sample index must be an integer")
    if arm["equivalence_protocol"] != _TIME_SERIES_EQUIVALENCE_PROTOCOL:
        raise ValueError("time-series arm lacks the approved mode-equivalence protocol")
    schedule_path = _resolve_config_path(
        arm["resolved_pulse_schedule"], config_path=config_path, field="resolved_pulse_schedule"
    )
    source = load_governed_source(
        state_path=state_path,
        receipt_path=receipt_path,
        mother_count=mother_count,
        screened_count=screened_count,
        sample_index=sample_index,
    )
    return float(gap_mm), source, {
        "identity": _time_series_identity(receipt_path, schedule_path),
        "mode_equivalence": _time_series_equivalence(
            receipt_path=receipt_path, schedule_path=schedule_path, sample_index=sample_index,
        ),
    }


def _arm_record(gap_mm: float, source: GovernedSource, identity: dict[str, Any]) -> dict[str, Any]:
    mode_equivalence = identity.get("mode_equivalence")
    return {
        "gap_mm": gap_mm,
        "checkpoint_kind": source.checkpoint_kind,
        "source_mode": (
            "PRE_PULSE_EQUIVALENT_TIME_SERIES"
            if source.checkpoint_kind == "pulse_disabled_time_series"
            else "INTEGRATION_FIXED_PULSE"
        ),
        "state_table": {"path": str(source.state_path.resolve()), "sha256": _sha256(source.state_path)},
        "evidence_receipt": {"path": str(source.receipt_path.resolve()), "sha256": _sha256(source.receipt_path)},
        "census": {
            "mother_count": source.mother_count,
            "screened_count": source.screened_count,
            "observed_pre_pulse_count": int(source.source.particle_ids.size),
            "unobserved_or_lost_count": source.mother_count - int(source.source.particle_ids.size),
        },
        **identity,
        **({"mode_equivalence": mode_equivalence} if mode_equivalence is not None else {}),
    }


def assess_connector_gap_triplet(*, config_path: Path) -> StageEvidence:
    """Close C1 only when all three governed arms satisfy one frozen mode."""

    request = _triplet_request(config_path)
    role_upper_bounds = _role_upper_bounds_from_request(request)
    required_kind = request["required_checkpoint_kind"]
    inputs: dict[str, Any] = {"triplet_request": {"path": str(config_path.resolve()), "sha256": _sha256(config_path)}}
    failures: list[str] = []
    loaded: list[tuple[float, GovernedSource, dict[str, Any]]] = []
    for index, arm in enumerate(request["arms"], start=1):
        try:
            loaded.append(_load_triplet_arm(arm, config_path=config_path, required_kind=required_kind))
        except ValueError as exc:
            failures.append(f"arm{index}: {exc}")
    if len(loaded) == 3:
        loaded.sort(key=lambda item: item[0])
        if tuple(item[0] for item in loaded) != _TRIPLET_GAPS_MM:
            failures.append("arms must be exactly the 0, 51.2, and 102.4 mm C1 sequence")
        if len({item[1].mother_count for item in loaded}) != 1 or loaded[0][1].mother_count != 5000:
            failures.append("all C1 arms must retain the same N=5000 mother cohort")
        identities = [item[2]["identity"] for item in loaded]
        if any(identity != identities[0] for identity in identities[1:]):
            failures.append("triplet arms do not share the frozen source, geometry, candidate, and numerical identity")
    arm_records = [_arm_record(*item) for item in loaded]
    comparisons: list[dict[str, Any]] = []
    if not failures and len(loaded) == 3:
        for first, second in zip(loaded, loaded[1:]):
            try:
                comparison = compare_connector_gap_sources(
                    first=first[1], second=second[1], cohort_salt=request["cohort_salt"],
                    bootstrap_replicates=request["bootstrap_replicates"], bootstrap_seed=request["bootstrap_seed"],
                    role_upper_bounds=role_upper_bounds,
                )
                comparisons.append({"from_gap_mm": first[0], "to_gap_mm": second[0], "result": comparison})
            except ValueError as exc:
                failures.append(f"{first[0]:g}-to-{second[0]:g} mm comparison: {exc}")
    conclusion = "PASS_CONTINUE" if not failures else "INCONCLUSIVE_REVISE"
    metrics = {
        "required_checkpoint_kind": required_kind,
        "cohort_partition": {"role_upper_bounds": dict(role_upper_bounds)},
        "arms": arm_records,
        "adjacent_locked_residual_comparisons": comparisons,
        "all_full_mother_denominators_retained": all(
            record["census"]["mother_count"] == 5000 for record in arm_records
        ),
    }
    return StageEvidence(
        stage_id="C1_CONNECTOR_GAP_TRIPLET",
        conclusion=conclusion,
        claim_limit=(
            "Detector-blind S1 connector-gap source residual and full-mother loss census only; "
            "no detector, peak-width, resolution, optimizer, Candidate, or Formal claim."
        ),
        inputs=inputs,
        metrics=metrics,
        claims_supported=(
            [
                "The three governed arms share the frozen N=5000 source identity and one explicit checkpoint mode.",
                "Adjacent gap residual comparisons use deterministic locked IDs while all loss rates retain the complete mother denominator.",
                *(
                    ["All three inputs are PRE_PULSE_EQUIVALENT time-series states bound to their own resolved pulse epochs."]
                    if required_kind == "pulse_disabled_time_series" else []
                ),
            ] if conclusion == "PASS_CONTINUE" else []
        ),
        claims_prohibited=(
            "A common-ID residual comparison proves a peak-width, resolution, transmission, or connector-gap optimum.",
            "A PRE_PULSE_EQUIVALENT time-series source is called an integration-fixed pulse-on checkpoint.",
            "The result supports J2/J3, Candidate, Formal, or engineering-performance claims.",
        ),
        failures=failures,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--triplet-request", type=Path,
        help="frozen C1 0/51.2/102.4 mm request; publishes the required stage package",
    )
    parser.add_argument(
        "--stage-evidence-destination", type=Path,
        help="new artifact directory for the five required stage-evidence documents",
    )
    for prefix in ("first", "second"):
        parser.add_argument(f"--{prefix}-state-table", type=Path)
        parser.add_argument(f"--{prefix}-summary", type=Path)
        parser.add_argument(f"--{prefix}-run-manifest", type=Path)
        parser.add_argument(f"--{prefix}-mother-count", type=int)
        parser.add_argument(f"--{prefix}-screened-count", type=int)
    parser.add_argument("--cohort-salt")
    parser.add_argument("--bootstrap-replicates", type=int, default=1000)
    parser.add_argument("--bootstrap-seed", type=int, default=20260825)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    pair_values = [
        args.first_state_table, args.first_summary, args.first_run_manifest,
        args.first_mother_count, args.first_screened_count, args.second_state_table,
        args.second_summary, args.second_run_manifest, args.second_mother_count,
        args.second_screened_count, args.cohort_salt,
    ]
    if args.triplet_request is not None:
        if args.stage_evidence_destination is None or any(value is not None for value in pair_values):
            parser.error("--triplet-request requires only --stage-evidence-destination and --output")
        evidence = assess_connector_gap_triplet(config_path=args.triplet_request)
        publish_stage_evidence(args.stage_evidence_destination, evidence)
        result = {
            "schema_version": 1,
            "role": "oatof_paper1_c1_connector_gap_triplet_assessment",
            "stage_evidence_destination": str(args.stage_evidence_destination.resolve()),
            "stage_evidence": {
                "stage_id": evidence.stage_id,
                "conclusion": evidence.conclusion,
                "claim_limit": evidence.claim_limit,
                "inputs": evidence.inputs,
                "metrics": evidence.metrics,
                "claims_supported": list(evidence.claims_supported),
                "claims_prohibited": list(evidence.claims_prohibited),
                "failures": list(evidence.failures),
            },
        }
    else:
        if args.stage_evidence_destination is not None or any(value is None for value in pair_values):
            parser.error("two-arm comparison requires every --first/--second field and --cohort-salt")
        first = load_fixed_pulse_checkpoint_source(state_path=args.first_state_table, summary_path=args.first_summary, run_manifest_path=args.first_run_manifest, mother_count=args.first_mother_count, screened_count=args.first_screened_count)
        second = load_fixed_pulse_checkpoint_source(state_path=args.second_state_table, summary_path=args.second_summary, run_manifest_path=args.second_run_manifest, mother_count=args.second_mother_count, screened_count=args.second_screened_count)
        result = compare_connector_gap_sources(first=first, second=second, cohort_salt=args.cohort_salt, bootstrap_replicates=args.bootstrap_replicates, bootstrap_seed=args.bootstrap_seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
