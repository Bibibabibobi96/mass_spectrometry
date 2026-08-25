"""Publish detector-blind C1 diagnostics for one frozen OA pre-pulse source."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from projects.single_reflection_oa_tof_mass_analyzer.analysis.paper1_focusability import (
    assess_source_condition,
    assign_detector_blind_cohorts,
    load_frozen_pre_pulse_source,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("source receipt must be a JSON object")
    return value


def _verify_time_series_receipt(
    receipt_path: Path, state_path: Path, *, sample_index: int,
    mother_count: int, screened_count: int,
) -> dict[str, Any]:
    receipt = _json(receipt_path)
    if receipt.get("role") != "rf_oatof_pre_pulse_time_series_screening_receipt":
        raise ValueError("source receipt role is not a governed pre-pulse time-series receipt")
    if receipt.get("status") != "success" or receipt.get("pulse_disabled") is not True:
        raise ValueError("source receipt is not a successful pulse-disabled screening")
    if (
        screened_count < 1
        or screened_count > mother_count
        or receipt.get("particle_count") != screened_count
    ):
        raise ValueError("source receipt screened-population count differs")
    states = receipt.get("outputs", {}).get("states", {})
    if states.get("sha256") != _sha256(state_path):
        raise ValueError("source receipt state-table SHA-256 differs")
    census = receipt.get("sample_census")
    if not isinstance(census, list) or not (1 <= sample_index <= len(census)):
        raise ValueError("source receipt lacks the requested anchor sample")
    selected = census[sample_index - 1]
    if selected.get("sample_index") != sample_index:
        raise ValueError("source receipt sample index differs")
    alive = selected.get("alive_count")
    missing = selected.get("missing_count")
    if (
        not isinstance(alive, int)
        or not isinstance(missing, int)
        or alive + missing != screened_count
    ):
        raise ValueError("source receipt anchor census does not preserve screened population")
    return {"anchor_census": selected, "receipt_sha256": _sha256(receipt_path)}


def analyze_source(
    *, state_path: Path, source_id: str, cohort_salt: str,
    time_series_sample_index: int | None, mother_particle_count: int,
    source_receipt: Path | None, time_series_population_count: int | None,
    bootstrap_replicates: int, bootstrap_seed: int,
) -> dict[str, Any]:
    """Return source-only C1 diagnostics without detector or design information."""
    if mother_particle_count < 1:
        raise ValueError("mother particle count must be positive")
    receipt: dict[str, Any] | None = None
    if source_receipt is not None:
        if time_series_sample_index is None:
            raise ValueError("a governed time-series receipt requires an anchor sample")
        screened_count = (
            mother_particle_count
            if time_series_population_count is None
            else time_series_population_count
        )
        receipt = _verify_time_series_receipt(
            source_receipt, state_path, sample_index=time_series_sample_index,
            mother_count=mother_particle_count, screened_count=screened_count,
        )
    source = load_frozen_pre_pulse_source(
        state_path, time_series_sample_index=time_series_sample_index
    )
    if source.particle_ids.size > mother_particle_count:
        raise ValueError("observed source state exceeds the frozen mother cohort")
    cohort = assign_detector_blind_cohorts(source.particle_ids, salt=cohort_salt)
    roles = np.asarray([item.role for item in cohort], dtype=object)
    counts = {role: int(np.sum(roles == role)) for role in ("development", "validation", "optimization", "locked_test")}
    development = roles == "development"
    validation = roles == "validation"
    if int(np.sum(development)) < 32 or int(np.sum(validation)) < 8:
        raise ValueError("C1 detector-blind development/validation cohorts are too small")
    # z is the declared conditional coordinate.  The full canonical six-vector
    # remains the response; no detector arrival, candidate, or control value is read.
    state_names = source.state_names
    assessment = assess_source_condition(
        development_condition=source.state[development, 2:3],
        development_state=source.state[development],
        validation_condition=source.state[validation, 2:3],
        validation_state=source.state[validation],
        condition_names=("z_mm",), state_names=state_names,
        pulse_eligible_fraction=float(source.particle_ids.size / mother_particle_count),
        bootstrap_replicates=bootstrap_replicates, bootstrap_seed=bootstrap_seed,
    )
    model = assessment.selected_model
    return {
        "schema_version": 1,
        "role": "oatof_paper1_c1_source_assessment",
        "qualification": "DETECTOR_BLIND_SOURCE_ONLY",
        "source_id": source_id,
        "state_table": {"path": str(state_path.resolve()), "sha256": _sha256(state_path)},
        "anchor": {"instrument_time_us": source.instrument_time_us, "time_series_sample_index": time_series_sample_index},
        "mother_cohort": {"count": mother_particle_count, "screened_count": (mother_particle_count if source_receipt is None or time_series_population_count is None else time_series_population_count), "observed_pre_pulse_count": int(source.particle_ids.size), "unobserved_or_lost_count": mother_particle_count - int(source.particle_ids.size)},
        "cohort": {"salt": cohort_salt, "counts": counts, "model_selection_roles": ["development", "validation"], "prohibited_from_model_selection": ["optimization", "locked_test"]},
        "selected_model": {"degree": model.degree, "effective_sample_count": model.effective_sample_count, "tail_fraction": model.tail_fraction, "residual_rms": model.residual_rms.tolist(), "pulse_eligible_fraction": model.pulse_eligible_fraction, "transverse_emittance_x_mm_m_per_s": model.transverse_emittance_x_mm_m_per_s, "transverse_emittance_y_mm_m_per_s": model.transverse_emittance_y_mm_m_per_s},
        "covariance_bins": [{"lower_condition": item.lower_condition, "upper_condition": item.upper_condition, "sample_count": item.sample_count, "covariance": item.covariance.tolist()} for item in assessment.covariance_bins],
        "residual_modes": {"variance": assessment.residual_mode_variance.tolist(), "bootstrap_alignment_lower_95": assessment.residual_mode_bootstrap_alignment.tolist()},
        "time_series_receipt": receipt,
        "claims_prohibited": ["detector performance", "resolution", "candidate optimization", "locked-test model selection", "Formal claim"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-table", type=Path, required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--cohort-salt", required=True)
    parser.add_argument("--mother-particle-count", type=int, required=True)
    parser.add_argument("--time-series-sample-index", type=int)
    parser.add_argument("--time-series-receipt", type=Path)
    parser.add_argument("--time-series-population-count", type=int)
    parser.add_argument("--bootstrap-replicates", type=int, default=200)
    parser.add_argument("--bootstrap-seed", type=int, default=20260825)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze_source(
        state_path=args.state_table, source_id=args.source_id,
        cohort_salt=args.cohort_salt,
        time_series_sample_index=args.time_series_sample_index,
        mother_particle_count=args.mother_particle_count,
        source_receipt=args.time_series_receipt,
        time_series_population_count=args.time_series_population_count,
        bootstrap_replicates=args.bootstrap_replicates,
        bootstrap_seed=args.bootstrap_seed,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
