"""Detector-complete paired N=100 screening promotion gate.

The gate accepts one row per fixed screening particle.  Resolution statistics
are recomputed from every detected row; callers cannot submit a trimmed peak
sample or omit loss rows.
"""

from __future__ import annotations

from hashlib import sha256
import json
from numbers import Integral
from typing import Mapping, Sequence

import numpy as np

from common.analysis.peak_metrics import (
    compute_peak_metrics,
)


RECEIPT_ROLE = "rf_oatof_paired_n100_screening_promotion"


def _failure(code: str, detail: str, *, arm: str | None = None) -> dict[str, str]:
    result = {"code": code, "detail": detail}
    if arm is not None:
        result["arm"] = arm
    return result


def _portable_id(value: object) -> int | str | None:
    if isinstance(value, Integral) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, str) and value:
        return value
    return None


def _ids_digest(ids: Sequence[int | str]) -> str:
    canonical = json.dumps(list(ids), separators=(",", ":"), ensure_ascii=True)
    return sha256(canonical.encode("utf-8")).hexdigest()


def _arm_census(
    arm: Mapping[str, object],
    expected_count: int,
    label: str,
    nominal_mass_da: float,
) -> tuple[dict[str, object], tuple[int | str, ...] | None, list[dict[str, str]]]:
    failures: list[dict[str, str]] = []
    arm_id = arm.get("arm_id")
    if not isinstance(arm_id, str) or not arm_id:
        arm_id = label
        failures.append(_failure("arm_id_missing", "arm_id must be a nonempty string", arm=label))

    raw_ids = arm.get("particle_ids")
    raw_hits = arm.get("hit_status")
    raw_tof = arm.get("pulse_effective_tof_ns")
    raw_eligible = arm.get("pulse_eligible_status")
    if isinstance(raw_ids, (str, bytes)):
        failures.append(
            _failure("particle_ids_missing", "particle_ids must contain the complete N=100 cohort", arm=label)
        )
        return {"arm_id": arm_id}, None, failures
    try:
        raw_id_array = np.asarray(raw_ids, dtype=object)
    except (TypeError, ValueError):
        raw_id_array = np.asarray([], dtype=object)
    if raw_id_array.ndim != 1:
        failures.append(
            _failure(
                "particle_ids_missing",
                "particle_ids must be a one-dimensional complete N=100 cohort",
                arm=label,
            )
        )
        return {"arm_id": arm_id}, None, failures
    ids_list = [_portable_id(value) for value in raw_id_array.tolist()]
    if any(value is None for value in ids_list):
        failures.append(_failure("particle_id_invalid", "particle IDs must be nonempty strings or integers", arm=label))
        return {"arm_id": arm_id}, None, failures
    ids = tuple(ids_list)  # type: ignore[arg-type]
    if len(ids) != expected_count:
        failures.append(
            _failure(
                "population_count_not_n100",
                f"arm contains {len(ids)} rows; the governed screening cohort contains {expected_count}",
                arm=label,
            )
        )
    if len(set(ids)) != len(ids):
        failures.append(_failure("duplicate_particle_ids", "particle IDs must be unique", arm=label))

    try:
        hits = np.asarray(raw_hits)
        tof = np.asarray(raw_tof, dtype=float)
        eligible = np.asarray(raw_eligible)
    except (TypeError, ValueError):
        failures.append(_failure("arm_arrays_invalid", "hit status and TOF arrays must be numeric vectors", arm=label))
        return {"arm_id": arm_id, "population_count": len(ids)}, ids, failures
    if hits.shape != (len(ids),) or tof.shape != (len(ids),) or eligible.shape != (len(ids),):
        failures.append(
            _failure(
                "arm_row_count_mismatch",
                "particle_ids, hit_status, and pulse_effective_tof_ns must have identical row counts",
                arm=label,
            )
        )
        return {"arm_id": arm_id, "population_count": len(ids)}, ids, failures
    if not np.all(np.isin(hits, [False, True, 0, 1])):
        failures.append(_failure("hit_status_not_binary", "hit_status must be binary for every particle", arm=label))
        return {"arm_id": arm_id, "population_count": len(ids)}, ids, failures
    if not np.all(np.isin(eligible, [False, True, 0, 1])):
        failures.append(
            _failure(
                "pulse_eligible_status_not_binary", "pulse eligibility must be binary for every particle", arm=label
            )
        )
        return {"arm_id": arm_id, "population_count": len(ids)}, ids, failures
    hit_mask = hits.astype(bool)
    eligible_mask = eligible.astype(bool)
    missing_hit = hit_mask & ~np.isfinite(tof)
    labelled_miss = ~hit_mask & ~np.isnan(tof)
    if np.any(missing_hit):
        failures.append(
            _failure(
                "detected_particle_missing_tof",
                f"{int(np.count_nonzero(missing_hit))} detected rows lack a finite TOF; hit tails cannot be deleted",
                arm=label,
            )
        )
    if np.any(labelled_miss):
        failures.append(
            _failure(
                "nonhit_particle_has_tof",
                f"{int(np.count_nonzero(labelled_miss))} non-hit rows have a TOF; non-hits must remain explicit NaN rows",
                arm=label,
            )
        )
    detected_tof = tof[eligible_mask & hit_mask & np.isfinite(tof)]
    if np.any(detected_tof <= 0.0):
        failures.append(
            _failure("nonpositive_pulse_effective_tof", "detected pulse-effective TOFs must be positive", arm=label)
        )

    result: dict[str, object] = {
        "arm_id": arm_id,
        "population_count": len(ids),
        "hit_count": int(np.count_nonzero(hit_mask)),
        "nonhit_count": int(np.count_nonzero(~hit_mask)),
        "finite_tof_count": int(np.count_nonzero(np.isfinite(tof))),
        "pulse_eligible_count": int(np.count_nonzero(eligible_mask)),
        "pulse_eligible_hit_count": int(np.count_nonzero(eligible_mask & hit_mask)),
        "pulse_ineligible_hit_count": int(np.count_nonzero(~eligible_mask & hit_mask)),
        "pulse_eligible_id_sha256_ordered": _ids_digest(
            tuple(sorted(particle_id for particle_id, keep in zip(ids, eligible_mask, strict=True) if keep))
        ),
        "particle_id_sha256_ordered": _ids_digest(ids),
        "tail_filter_applied": False,
        "nonhit_rows_retained": True,
    }
    blocking_codes = {
        "population_count_not_n100",
        "duplicate_particle_ids",
        "detected_particle_missing_tof",
        "nonhit_particle_has_tof",
        "nonpositive_pulse_effective_tof",
    }
    if any(item["code"] in blocking_codes for item in failures):
        return result, ids, failures
    if detected_tof.size < 3:
        failures.append(
            _failure(
                "insufficient_detected_particles", "peak metrics require at least three detected particles", arm=label
            )
        )
        return result, ids, failures
    try:
        peak, _ = compute_peak_metrics(detected_tof / 1000.0, nominal_mass_da)
    except ValueError as exc:
        failures.append(_failure("peak_metric_failure", str(exc), arm=label))
        return result, ids, failures
    result["peak"] = {
        "sample_sigma_tof_ns": float(np.std(detected_tof, ddof=1)),
        "direct_fwhm_tof_ns": float(peak["direct_fwhm_tof_ns"]),
        "significant_kde_modes": int(peak["significant_kde_modes"]),
        "detected_particles_used": int(detected_tof.size),
    }
    return result, ids, failures


def evaluate_campaign_n100_paired_promotion(
    campaign: Mapping[str, object],
    baseline_arm: Mapping[str, object],
    candidate_arm: Mapping[str, object],
    *,
    nominal_mass_da: float = 100.0,
) -> dict[str, object]:
    """Evaluate the governed paired screening gate and return a JSON receipt."""
    failures: list[dict[str, str]] = []
    try:
        if (
            int(campaign.get("schema_version", 0)) < 3
            or campaign.get("role") != "rf_multipole_oatof_experiment_campaign"
            or not isinstance(campaign.get("campaign_id"), str)
        ):
            raise ValueError("campaign is not the pulse-resolution optimization contract")
        contract = campaign["pulse_resolution_optimization"]
        population = contract["population_contract"]
        promotion = contract["screening_promotion"]
        expected_count = int(population["screening_prefix_count"])
        fwhm_minimum = float(promotion["direct_fwhm_relative_improvement_minimum"])
        sigma_minimum = float(promotion["sigma_relative_improvement_minimum"])
        if (
            expected_count != 100
            or promotion.get("unimodal_required") is not True
            or promotion.get("both_improvements_required") is not True
            or not np.isclose(fwhm_minimum, 0.15, rtol=0.0, atol=1.0e-15)
            or not np.isclose(sigma_minimum, 0.15, rtol=0.0, atol=1.0e-15)
        ):
            raise ValueError("campaign N=100 paired promotion thresholds differ")
    except (KeyError, TypeError, ValueError) as exc:
        failures.append(_failure("campaign_contract_invalid", str(exc)))
        expected_count, fwhm_minimum, sigma_minimum = 100, 0.15, 0.15

    mass = float(nominal_mass_da)
    if not np.isfinite(mass) or mass <= 0.0:
        failures.append(_failure("nominal_mass_invalid", "nominal_mass_da must be positive and finite"))
        mass = 100.0
    baseline, baseline_ids, baseline_failures = _arm_census(baseline_arm, expected_count, "baseline", mass)
    candidate, candidate_ids, candidate_failures = _arm_census(candidate_arm, expected_count, "candidate", mass)
    failures.extend(baseline_failures)
    failures.extend(candidate_failures)
    paired = baseline_ids is not None and candidate_ids is not None and set(baseline_ids) == set(candidate_ids)
    if not paired:
        failures.append(
            _failure("cohort_id_mismatch", "baseline and candidate must contain exactly the same fixed particle IDs")
        )
    eligible_paired = baseline.get("pulse_eligible_id_sha256_ordered") is not None and baseline.get(
        "pulse_eligible_id_sha256_ordered"
    ) == candidate.get("pulse_eligible_id_sha256_ordered")
    if not eligible_paired:
        failures.append(
            _failure(
                "pulse_eligible_cohort_mismatch",
                "baseline and candidate must contain the same pulse-eligible particle IDs",
            )
        )

    improvements: dict[str, float | None] = {
        "direct_fwhm_relative": None,
        "sample_sigma_relative": None,
    }
    if "peak" in baseline and "peak" in candidate:
        baseline_peak = baseline["peak"]
        candidate_peak = candidate["peak"]
        for arm_label, peak in (("baseline", baseline_peak), ("candidate", candidate_peak)):
            if peak["significant_kde_modes"] != 1:
                failures.append(
                    _failure(
                        f"{arm_label}_not_single_mode",
                        f"canonical KDE reports {peak['significant_kde_modes']} significant modes",
                        arm=arm_label,
                    )
                )
        baseline_fwhm = float(baseline_peak["direct_fwhm_tof_ns"])
        candidate_fwhm = float(candidate_peak["direct_fwhm_tof_ns"])
        baseline_sigma = float(baseline_peak["sample_sigma_tof_ns"])
        candidate_sigma = float(candidate_peak["sample_sigma_tof_ns"])
        improvements = {
            "direct_fwhm_relative": (baseline_fwhm - candidate_fwhm) / baseline_fwhm,
            "sample_sigma_relative": (baseline_sigma - candidate_sigma) / baseline_sigma,
        }
        if improvements["direct_fwhm_relative"] + 1.0e-15 < fwhm_minimum:
            failures.append(
                _failure(
                    "direct_fwhm_improvement_below_minimum",
                    f"relative improvement {improvements['direct_fwhm_relative']:.12g} is below {fwhm_minimum:.12g}",
                )
            )
        if improvements["sample_sigma_relative"] + 1.0e-15 < sigma_minimum:
            failures.append(
                _failure(
                    "sample_sigma_improvement_below_minimum",
                    f"relative improvement {improvements['sample_sigma_relative']:.12g} is below {sigma_minimum:.12g}",
                )
            )

    receipt: dict[str, object] = {
        "schema_version": 1,
        "role": RECEIPT_ROLE,
        "campaign_id": campaign.get("campaign_id"),
        "decision": "promote" if not failures else "reject",
        "promoted": not failures,
        "criteria": {
            "screening_population_count": expected_count,
            "same_fixed_particle_ids_required": True,
            "single_mode_required_for_both_arms": True,
            "direct_fwhm_relative_improvement_minimum": fwhm_minimum,
            "sample_sigma_relative_improvement_minimum": sigma_minimum,
            "both_improvements_required": True,
            "tail_filter_allowed": False,
            "nonhit_row_omission_allowed": False,
            "peak_population_basis": "fixed_detector_blind_pulse_eligible_cohort",
        },
        "pairing": {
            "same_fixed_particle_ids": paired,
            "same_pulse_eligible_particle_ids": eligible_paired,
            "population_count": len(set(baseline_ids or ()) & set(candidate_ids or ())),
            "eligible_paired_count": (
                int(baseline.get("pulse_eligible_count", 0)) if eligible_paired else 0
            ),
        },
        "baseline": baseline,
        "candidate": candidate,
        "improvements": improvements,
        "failure_reasons": failures,
        "calculation_contract": {
            "time_basis": "detector_time_minus_pulse_effective_time",
            "peak_metric": "canonical_direct_kde_over_detected_rows_in_fixed_pulse_eligible_cohort",
            "sigma_definition": "sample_standard_deviation_ddof_1_over_detected_rows_in_fixed_pulse_eligible_cohort",
            "pulse_eligible_selection_uses_detector_outcome": False,
        },
    }
    canonical = json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    receipt["receipt_sha256"] = sha256(canonical.encode("utf-8")).hexdigest()
    return receipt
