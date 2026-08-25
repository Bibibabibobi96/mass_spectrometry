"""Compare OA-pre-pulse axial residuals across connector gaps without detector data.

This Paper 1 diagnostic consumes two governed OA ``pre_pulse_state`` checkpoint
tables from the *same* root mother cohort.  The checkpoint time is the
integration-resolved ``pulse_effective_time_us``; it is not selected from a
time series.  It uses deterministic particle-ID roles: development fits a
``v_z(z)`` model, validation selects its degree, and only IDs present in both
locked-test sets estimate the paired residual change.  The common-ID statistic
is a phase-space diagnostic, never a peak-width or transmission result; each
arm's full mother-cohort loss census is retained.
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


_DEGREES = (1, 2, 3)
_ROLES = ("development", "validation", "optimization", "locked_test")


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


def _roles_by_id(ids: Iterable[int], *, salt: str) -> dict[int, str]:
    return {item.particle_id: item.role for item in assign_detector_blind_cohorts(ids, salt=salt)}


def _arm_model(source: FrozenPrePulseSource, *, salt: str) -> tuple[dict[int, str], int, tuple[np.ndarray, float, float], dict[str, float]]:
    roles = _roles_by_id(source.particle_ids, salt=salt)
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
) -> dict[str, Any]:
    """Return paired locked-test axial residual diagnostics for two connector gaps."""

    if first.mother_count != second.mother_count:
        raise ValueError("connector-gap comparison requires one shared mother count")
    if (
        first.screened_id_sha256 is not None
        and second.screened_id_sha256 is not None
        and first.screened_id_sha256 != second.screened_id_sha256
    ):
        raise ValueError("connector-gap arms do not share one screened particle-ID cohort")
    first_roles, first_degree, first_fit, first_scores = _arm_model(first.source, salt=cohort_salt)
    second_roles, second_degree, second_fit, second_scores = _arm_model(second.source, salt=cohort_salt)
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
        "cohort": {"salt": cohort_salt, "mother_count": first.mother_count, "common_locked_test_count": len(common_locked_ids), "common_locked_test_id_sha256": hashlib.sha256(json.dumps(common_locked_ids, separators=(",", ":")).encode("utf-8")).hexdigest().upper()},
        "arms": [
            {"state_table": {"path": str(item.state_path.resolve()), "sha256": _sha256(item.state_path)}, "evidence_receipt": {"path": str(item.receipt_path.resolve()), "sha256": _sha256(item.receipt_path)}, "checkpoint": {"kind": item.checkpoint_kind, "instrument_time_us": item.source.instrument_time_us}, "census": {"mother_count": item.mother_count, "screened_count": item.screened_count, "screened_particle_id_sha256": item.screened_id_sha256, "observed_pre_pulse_count": int(item.source.particle_ids.size), "unobserved_or_lost_count": item.mother_count - int(item.source.particle_ids.size)}, "selected_polynomial_degree": degree, "validation_mse_m2_per_s2": scores}
            for item, degree, scores in ((first, first_degree, first_scores), (second, second_degree, second_scores))
        ],
        "paired_locked_axial_residual": {"first_rms_m_per_s": float(np.sqrt(first_mse)), "second_rms_m_per_s": float(np.sqrt(second_mse)), "second_minus_first_mse_m2_per_s2": paired, "relative_mse_change": float(second_mse / first_mse - 1.0) if first_mse > 0.0 else None},
        "claims_supported": ["The two arms use integration-fixed OA-pre-pulse states and deterministic ID roles.", "The reported residual difference is evaluated only on common locked-test source IDs while each arm retains its full mother-cohort loss census."],
        "claims_prohibited": ["A common-ID residual statistic proves a peak-width, resolution, transmission, or connector-gap optimum.", "Observed residual change has a detector-level or engineering interpretation without the subsequent locked particle campaign."],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for prefix in ("first", "second"):
        parser.add_argument(f"--{prefix}-state-table", type=Path, required=True)
        parser.add_argument(f"--{prefix}-summary", type=Path, required=True)
        parser.add_argument(f"--{prefix}-run-manifest", type=Path, required=True)
        parser.add_argument(f"--{prefix}-mother-count", type=int, required=True)
        parser.add_argument(f"--{prefix}-screened-count", type=int, required=True)
    parser.add_argument("--cohort-salt", required=True)
    parser.add_argument("--bootstrap-replicates", type=int, default=1000)
    parser.add_argument("--bootstrap-seed", type=int, default=20260825)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    first = load_fixed_pulse_checkpoint_source(state_path=args.first_state_table, summary_path=args.first_summary, run_manifest_path=args.first_run_manifest, mother_count=args.first_mother_count, screened_count=args.first_screened_count)
    second = load_fixed_pulse_checkpoint_source(state_path=args.second_state_table, summary_path=args.second_summary, run_manifest_path=args.second_run_manifest, mother_count=args.second_mother_count, screened_count=args.second_screened_count)
    result = compare_connector_gap_sources(first=first, second=second, cohort_salt=args.cohort_salt, bootstrap_replicates=args.bootstrap_replicates, bootstrap_seed=args.bootstrap_seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
