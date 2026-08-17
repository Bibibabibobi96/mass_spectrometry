"""Numeric mechanics for the solver-free three-zone ideal-theory campaign.

Rows never select among root branches: exactly one clustered root must pass the
frozen physics and post-root numerical gates before outer-row ranking may begin.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from projects.single_reflection_oa_tof_mass_analyzer.analysis.peak_metrics import (
    compute_peak_metrics,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.three_zone_ideal_root_solver import (
    JacobianAudit,
    JacobianLimits,
    JacobianSettings,
    RootBounds,
    RootCandidate,
    RootCollection,
    RootSearchSettings,
    RootSeed,
    TwoZoneRootBounds,
    TwoZoneRootSearchSettings,
    TwoZoneRootSeed,
    audit_scaled_jacobian,
    audit_two_zone_jacobian,
    collect_three_zone_roots,
    collect_two_zone_roots,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.three_zone_ideal_theory import (
    AffineSource,
    InnerSolution,
    OuterGeometry,
    PhysicsGateLimits,
    ReflectronGeometry,
    build_exact_cohort,
    derive_three_zone_state,
)


RANKING_TUPLE = (
    "contrast_tier_index",
    "boundary_limited",
    "target_gate_failed",
    "sigma_2p2_population_ns",
    "fwhm_2p2_ns",
    "sigma_1p0_population_ns",
    "jacobian_condition",
    "d1_mm",
    "l23_mm",
    "delta_v1_v",
    "lambda",
)


@dataclass(frozen=True)
class NumericStageOutcome:
    """JSON-ready result and receipt propagation for one numeric stage."""

    status: str
    conclusion: str
    next_stage_authorized: bool
    results: dict[str, Any]
    completed_rows: int
    failed_rows: int
    selected_outer_points: list[dict[str, float]]
    frozen_primary: dict[str, float] | None
    best_feasible_two_zone: dict[str, float] | None


@dataclass(frozen=True)
class _RowEvaluation:
    record: dict[str, Any]
    outer: dict[str, float]
    inner: InnerSolution | None
    metrics: dict[str, Any] | None
    contrast: float
    boundary_limited: bool
    jacobian_condition: float
    target_gate_failed: bool

    @property
    def eligible(self) -> bool:
        return self.record["row_status"] == "accepted_unique_root"


def _source(campaign: Mapping[str, Any]) -> AffineSource:
    frozen = campaign["frozen_source"]
    if int(frozen["charge_sign"]) != 1:
        raise ValueError("v1 theory execution requires positive unit charge")
    return AffineSource.from_velocity(
        mass_to_charge_th=float(frozen["mass_to_charge_th"]),
        center_x_mm=float(frozen["center_x_mm"]),
        center_velocity_m_per_s=float(frozen["center_velocity_m_per_s"]),
        velocity_slope_m_per_s_per_mm=float(
            frozen["velocity_slope_m_per_s_per_mm"]
        ),
    )


def _reflectron(campaign: Mapping[str, Any]) -> ReflectronGeometry:
    return ReflectronGeometry(**campaign["reflectron_geometry"])


def _outer(campaign: Mapping[str, Any], values: Mapping[str, Any]) -> OuterGeometry:
    return OuterGeometry(
        zone1_length_mm=float(values["d1_mm"]),
        downstream_length_mm=float(values["l23_mm"]),
        split_fraction=float(values["lambda"]),
        zone1_voltage_drop_v=float(values["delta_v1_v"]),
        nominal_energy_per_charge_v=float(
            campaign["frozen_source"]["nominal_energy_per_charge_v"]
        ),
    )


def _outer_dict(values: Mapping[str, Any]) -> dict[str, float]:
    return {
        "d1_mm": float(values["d1_mm"]),
        "l23_mm": float(values["l23_mm"]),
        "lambda": float(values["lambda"]),
        "delta_v1_v": float(values["delta_v1_v"]),
    }


def _physics_limits(campaign: Mapping[str, Any]) -> PhysicsGateLimits:
    return PhysicsGateLimits(**campaign["physics_limits"])


def _jacobian_limits(campaign: Mapping[str, Any]) -> JacobianLimits:
    root = campaign["root_policy"]
    composite = root["post_root_composite_audit"]
    gates = campaign["scientific_gates"]
    return JacobianLimits(
        root_residual_absolute_max=float(
            gates["maximum_scaled_derivative_residual"]
        ),
        minimum_reciprocal_condition=float(root["minimum_reciprocal_condition"]),
        maximum_condition_number=float(gates["maximum_scaled_jacobian_condition"]),
        maximum_jacobian_stability_relative_error=float(
            composite["maximum_cross_step_relative_change"]
        ),
        minimum_gamma3_uncertainty_multiple=float(
            root["minimum_gamma3_uncertainty_multiple"]
        ),
    )


def _jacobian_settings(campaign: Mapping[str, Any], step: float) -> JacobianSettings:
    return JacobianSettings(
        eta_scale=math.log(10.0),
        step_u=step,
        step_f=step,
        step_eta_hat=step,
        stability_step_multiplier=2.0,
        rank_relative_tolerance=float(
            campaign["root_policy"]["rank_relative_tolerance"]
        ),
    )


def _root_settings(
    campaign: Mapping[str, Any], *, three_zone: bool
) -> RootSearchSettings | TwoZoneRootSearchSettings:
    root = campaign["root_policy"]
    bounds = root["scaled_bounds"]
    common = {
        "convergence_tolerance": float(root["newton_convergence_tolerance"]),
        "maximum_iterations": int(root["maximum_iterations"]),
        "maximum_backtracks": int(root["maximum_backtracks"]),
        "cluster_distance": float(root["root_cluster_scaled_distance"]),
        "jacobian": _jacobian_settings(
            campaign, float(root["newton_central_difference_step"])
        ),
        "limits": _jacobian_limits(campaign),
    }
    two_seeds = tuple(
        TwoZoneRootSeed(float(seed[0]), float(seed[1]))
        for seed in root["two_zone_seeds"]
    )
    if not three_zone:
        return TwoZoneRootSearchSettings(
            seeds=two_seeds,
            bounds=TwoZoneRootBounds(
                float(bounds["u"]["minimum"]),
                float(bounds["u"]["maximum"]),
                float(bounds["f"]["minimum"]),
                float(bounds["f"]["maximum"]),
            ),
            **common,
        )
    seeds = tuple(
        RootSeed(seed.u, seed.f, float(eta_hat))
        for eta_hat in root["eta_hat_seeds"]
        for seed in two_seeds
    )
    return RootSearchSettings(
        seeds=seeds,
        bounds=RootBounds(
            float(bounds["u"]["minimum"]),
            float(bounds["u"]["maximum"]),
            float(bounds["f"]["minimum"]),
            float(bounds["f"]["maximum"]),
            float(bounds["eta_hat"]["minimum"]),
            float(bounds["eta_hat"]["maximum"]),
        ),
        **common,
    )


def _collect(
    campaign: Mapping[str, Any], outer: OuterGeometry, *, three_zone: bool
) -> RootCollection:
    sampling = campaign["sampling_policy"]
    if 2.2 not in [float(value) for value in sampling["source_full_widths_mm"]]:
        raise ValueError("numeric campaign must include the 2.2 mm primary width")
    common = {
        "width_mm": 2.2,
        "cohort_sample_count": int(sampling["primary_sample_count"]),
        "physics_limits": _physics_limits(campaign),
    }
    settings = _root_settings(campaign, three_zone=three_zone)
    if three_zone:
        if not isinstance(settings, RootSearchSettings):
            raise AssertionError("three-zone root settings type differs")
        return collect_three_zone_roots(
            _source(campaign), outer, _reflectron(campaign), settings=settings, **common
        )
    if not isinstance(settings, TwoZoneRootSearchSettings):
        raise AssertionError("two-zone root settings type differs")
    return collect_two_zone_roots(
        _source(campaign), outer, _reflectron(campaign), settings=settings, **common
    )


def _audit_summary(audit: JacobianAudit) -> dict[str, Any]:
    return {
        "root_residual_infinity_norm": audit.residuals.infinity_norm,
        "numerical_rank": audit.numerical_rank,
        "condition_number": audit.condition_number,
        "reciprocal_condition": audit.reciprocal_condition,
        "jacobian_stability_relative_error": (
            audit.jacobian_stability_relative_error
        ),
        "gamma3_scaled": audit.gamma3_scaled,
        "gamma3_step_uncertainty": audit.gamma3_step_uncertainty,
        "passed": audit.passed,
    }


def _post_root_audits(
    campaign: Mapping[str, Any],
    outer: OuterGeometry,
    candidate: RootCandidate,
    *,
    three_zone: bool,
) -> tuple[bool, float, dict[str, Any]]:
    composite = campaign["root_policy"]["post_root_composite_audit"]
    declared = tuple(float(value) for value in composite["central_difference_steps_h"])
    if declared != (0.00005, 0.0001, 0.0002):
        raise ValueError("post_root_audit_steps differ from frozen v1 identity")
    source = _source(campaign)
    reflectron = _reflectron(campaign)
    limits = _jacobian_limits(campaign)
    audits: list[JacobianAudit] = []
    for step in (0.00005, 0.0001):
        settings = _jacobian_settings(campaign, step)
        audit = (
            audit_scaled_jacobian(
                source,
                outer,
                reflectron,
                candidate.inner,
                width_mm=2.2,
                settings=settings,
                limits=limits,
            )
            if three_zone
            else audit_two_zone_jacobian(
                source,
                outer,
                reflectron,
                candidate.inner,
                width_mm=2.2,
                settings=settings,
                limits=limits,
            )
        )
        audits.append(audit)
    jacobian_variation = max(
        audit.jacobian_stability_relative_error for audit in audits
    )
    gamma_variations: list[float] = []
    if three_zone:
        for audit in audits:
            if audit.gamma3_scaled is None or audit.gamma3_step_uncertainty is None:
                gamma_variations.append(math.inf)
            else:
                gamma_variations.append(
                    audit.gamma3_step_uncertainty
                    / max(abs(audit.gamma3_scaled), np.finfo(float).tiny)
                )
    gamma_variation = max(gamma_variations, default=0.0)
    limit = float(composite["maximum_cross_step_relative_change"])
    passed = (
        candidate.evaluation.gates.passed
        and all(audit.passed for audit in audits)
        and jacobian_variation <= limit
        and gamma_variation <= limit
    )
    condition = max(audit.condition_number for audit in audits)
    return passed, condition, {
        "audit_h_5e_5": _audit_summary(audits[0]),
        "audit_h_1e_4": _audit_summary(audits[1]),
        "maximum_jacobian_relative_variation": jacobian_variation,
        "maximum_gamma3_relative_variation": gamma_variation,
        "stability_limit": limit,
        "physics_gates_passed": candidate.evaluation.gates.passed,
        "physics_failed_names": list(candidate.evaluation.gates.failed_names),
        "workflow_post_root_passed": passed,
    }


def _candidate_metrics(
    campaign: Mapping[str, Any],
    outer: OuterGeometry,
    candidate: RootCandidate,
) -> dict[str, Any]:
    source = _source(campaign)
    reflectron = _reflectron(campaign)
    state = derive_three_zone_state(source, outer, candidate.inner.eta)
    count = int(campaign["sampling_policy"]["primary_sample_count"])
    result: dict[str, Any] = {"sample_count": count}
    for width, label in ((2.2, "2p2"), (1.0, "1p0")):
        cohort = build_exact_cohort(
            source,
            state,
            reflectron,
            candidate.inner,
            width_mm=width,
            sample_count=count,
        )
        peak, _ = compute_peak_metrics(
            cohort.tof_us,
            float(campaign["frozen_source"]["mass_to_charge_th"]),
        )
        result[f"sigma_{label}_population_ns"] = cohort.population_sigma_ns
        result[f"sigma_{label}_sample_ns"] = cohort.sample_sigma_ns
        result[f"fwhm_{label}_ns"] = float(peak["direct_fwhm_tof_ns"])
        result[f"modes_{label}"] = int(peak["significant_kde_modes"])
        result[f"mean_tof_{label}_us"] = float(peak["mean_tof_us"])
    return result


def _sampling_convergence(
    campaign: Mapping[str, Any], row: _RowEvaluation
) -> dict[str, Any]:
    if row.inner is None:
        raise ValueError("sampling convergence requires a selected inner root")
    sampling = campaign["sampling_policy"]
    counts = tuple(int(value) for value in sampling["population_sample_counts"])
    if counts != (501, 1001, 2001):
        raise ValueError("population sample counts differ from frozen v1 identity")
    source = _source(campaign)
    reflectron = _reflectron(campaign)
    outer = _outer(campaign, row.outer)
    state = derive_three_zone_state(source, outer, row.inner.eta)
    widths: dict[str, Any] = {}
    overall_passed = True
    for width, label in ((2.2, "2p2"), (1.0, "1p0")):
        per_count: dict[str, Any] = {}
        sigmas: list[float] = []
        modes: list[int] = []
        for count in counts:
            cohort = build_exact_cohort(
                source,
                state,
                reflectron,
                row.inner,
                width_mm=width,
                sample_count=count,
            )
            peak, _ = compute_peak_metrics(
                cohort.tof_us,
                float(campaign["frozen_source"]["mass_to_charge_th"]),
            )
            sigma = cohort.population_sigma_ns
            mode_count = int(peak["significant_kde_modes"])
            sigmas.append(sigma)
            modes.append(mode_count)
            per_count[str(count)] = {
                "population_sigma_ns": sigma,
                "significant_kde_modes": mode_count,
                "direct_fwhm_tof_ns_non_gating": float(
                    peak["direct_fwhm_tof_ns"]
                ),
            }
        reference_sigma = sigmas[-1]
        maximum_relative_difference = max(
            abs(value / reference_sigma - 1.0) for value in sigmas
        )
        sigma_passed = maximum_relative_difference <= float(
            sampling["population_sigma_relative_convergence"]
        )
        modes_stable = len(set(modes)) == 1
        modes_passed = (
            modes_stable
            if sampling["mode_count_cross_sample_stability_required"]
            else True
        )
        width_passed = sigma_passed and modes_passed
        overall_passed = overall_passed and width_passed
        widths[label] = {
            "per_sample_count": per_count,
            "sigma_reference_sample_count": counts[-1],
            "sigma_relative_difference_definition": (
                "max_N(abs(sigma_N/sigma_2001-1))"
            ),
            "maximum_sigma_relative_difference": maximum_relative_difference,
            "sigma_convergence_passed": sigma_passed,
            "mode_count_stable": modes_stable,
            "mode_stability_passed": modes_passed,
            "fwhm_cross_sample_gating": False,
            "passed": width_passed,
        }
    return {"widths": widths, "passed": overall_passed}


def _is_boundary(
    campaign: Mapping[str, Any], outer: Mapping[str, float], *, three_zone: bool
) -> bool:
    domain = campaign["theory_domain"]
    axes = ("d1_mm", "l23_mm", "delta_v1_v")
    if three_zone:
        axes += ("lambda",)
    return any(
        math.isclose(
            outer[name], float(domain[name][edge]), rel_tol=0.0, abs_tol=1.0e-12
        )
        for name in axes
        for edge in ("minimum", "maximum")
    )


def _attempt_census(collection: RootCollection) -> dict[str, int]:
    return dict(sorted(Counter(item.reason for item in collection.attempts).items()))


def _branch_reference_coordinates(
    campaign: Mapping[str, Any],
) -> tuple[float, float, float]:
    policy = campaign["root_policy"]
    if policy["branch_distance_coordinates"] != ["u", "f", "eta_hat"]:
        raise ValueError("branch distance coordinates differ from frozen v1 identity")
    if policy["branch_distance_metric"] != "scaled_euclidean":
        raise ValueError("branch distance metric differs from frozen v1 identity")
    fixture_id = policy["three_zone_branch_reference_fixture_id"]
    fixture = next(
        (
            value
            for value in campaign["fixtures"].values()
            if value["fixture_id"] == fixture_id
        ),
        None,
    )
    if fixture is None or "inner" not in fixture:
        raise ValueError("three-zone branch reference fixture is unavailable")
    source = _source(campaign)
    center_energy = (
        float(campaign["frozen_source"]["nominal_energy_per_charge_v"])
        + source.chi_center_sqrt_v**2
    )
    inner = fixture["inner"]
    return (
        float(inner["u_r1_v"]) / center_energy,
        float(inner["f_r2_v_per_mm"])
        * _reflectron(campaign).stage2_length_mm
        / center_energy,
        float(inner["eta"]) / math.log(10.0),
    )


def _branch_selection(
    campaign: Mapping[str, Any],
    accepted: Sequence[tuple[RootCandidate, float, dict[str, Any], int]],
    *,
    three_zone: bool,
) -> tuple[
    tuple[RootCandidate, float, dict[str, Any], int] | None,
    dict[str, Any],
]:
    reference = _branch_reference_coordinates(campaign) if three_zone else None
    summaries = []
    distances: list[tuple[float, int]] = []
    for accepted_index, (candidate, condition, audit, cluster_index) in enumerate(
        accepted
    ):
        distance = (
            float(np.linalg.norm(np.asarray(candidate.coordinates) - reference))
            if reference is not None
            else None
        )
        if distance is not None:
            distances.append((distance, accepted_index))
        summaries.append(
            {
                "accepted_index": accepted_index,
                "cluster_index": cluster_index,
                "coordinates": list(candidate.coordinates),
                "distance_to_branch_reference": distance,
                "inner": {
                    "eta": candidate.inner.eta,
                    "u_r1_v": candidate.inner.stage1_voltage_drop_v,
                    "f_r2_v_per_mm": candidate.inner.stage2_field_v_per_mm,
                },
                "jacobian_condition": condition,
                "post_root_audit": audit,
            }
        )
    chosen_index: int | None = None
    nearest: float | None = None
    second: float | None = None
    margin: float | None = None
    tie = False
    if len(accepted) == 1:
        chosen_index = 0
        nearest = distances[0][0] if distances else None
    elif len(accepted) > 1 and three_zone:
        ordered = sorted(distances)
        nearest, chosen_index = ordered[0]
        second = ordered[1][0]
        margin = second - nearest
        tie = second <= math.nextafter(nearest, math.inf)
        if tie:
            chosen_index = None
    selected = None if chosen_index is None else accepted[chosen_index]
    audit = {
        "policy": (
            "scaled_parameter_distance_unique_nearest"
            if three_zone
            else "unique_accepted_root_only"
        ),
        "performance_used": False,
        "reference_fixture_id": (
            campaign["root_policy"]["three_zone_branch_reference_fixture_id"]
            if three_zone
            else None
        ),
        "reference_coordinates": list(reference) if reference is not None else None,
        "accepted_root_summaries": summaries,
        "chosen_accepted_index": chosen_index,
        "nearest_distance": nearest,
        "second_nearest_distance": second,
        "nearest_distance_margin": margin,
        "machine_safe_tie": tie,
        "tie_rule": "second_distance <= nextafter(nearest_distance, +inf)",
    }
    return selected, audit


def _evaluate_row(
    campaign: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    three_zone: bool,
) -> _RowEvaluation:
    outer_values = _outer_dict(row["outer"])
    outer = _outer(campaign, outer_values)
    collection = _collect(campaign, outer, three_zone=three_zone)
    accepted: list[tuple[RootCandidate, float, dict[str, Any], int]] = []
    rejected: list[dict[str, Any]] = []
    for cluster_index, candidate in enumerate(collection.candidates):
        passed, condition, audit = _post_root_audits(
            campaign, outer, candidate, three_zone=three_zone
        )
        if passed:
            accepted.append((candidate, condition, audit, cluster_index))
        else:
            rejected.append(audit)
    record = {
        "row_id": row["row_id"],
        "sequence": int(row["sequence"]),
        "arm_role": row["arm_role"],
        "outer": outer_values,
        "attempt_count": len(collection.attempts),
        "attempt_reason_census": _attempt_census(collection),
        "clustered_root_count": len(collection.candidates),
        "workflow_accepted_root_count": len(accepted),
    }
    boundary = _is_boundary(campaign, outer_values, three_zone=three_zone)
    selected, branch_audit = _branch_selection(
        campaign, accepted, three_zone=three_zone
    )
    record["branch_selection_audit"] = branch_audit
    if selected is None:
        record["row_status"] = (
            "ambiguous_multiple_accepted_roots"
            if len(accepted) > 1
            else "no_accepted_root"
        )
        record["rejected_candidate_audits"] = rejected
        return _RowEvaluation(
            record, outer_values, None, None, math.inf, boundary, math.inf, True
        )
    candidate, condition, audit, _ = selected
    metrics = _candidate_metrics(campaign, outer, candidate)
    state = candidate.evaluation.state
    contrast = max(
        state.field_ratio_2_over_3, 1.0 / state.field_ratio_2_over_3
    )
    record.update(
        {
            "row_status": "accepted_unique_root",
            "inner": {
                "eta": candidate.inner.eta,
                "u_r1_v": candidate.inner.stage1_voltage_drop_v,
                "f_r2_v_per_mm": candidate.inner.stage2_field_v_per_mm,
            },
            "metrics": metrics,
            "accelerator_field_contrast": contrast,
            "boundary_limited": boundary,
            "jacobian_condition": condition,
            "post_root_audit": audit,
        }
    )
    return _RowEvaluation(
        record,
        outer_values,
        candidate.inner,
        metrics,
        contrast,
        boundary,
        condition,
        True,
    )


def _performance_gate(
    candidate: Mapping[str, Any],
    benchmark: Mapping[str, Any],
    limits: Mapping[str, Any],
) -> dict[str, Any]:
    sigma_reduction = 1.0 - float(candidate["sigma_2p2_population_ns"]) / float(
        benchmark["sigma_2p2_population_ns"]
    )
    fwhm_reduction = 1.0 - float(candidate["fwhm_2p2_ns"]) / float(
        benchmark["fwhm_2p2_ns"]
    )
    one_mm_degradation = float(candidate["sigma_1p0_population_ns"]) / float(
        benchmark["sigma_1p0_population_ns"]
    ) - 1.0
    checks = {
        "sigma_2p2_passed": sigma_reduction
        >= float(limits["minimum_2p2mm_population_sigma_reduction"]),
        "fwhm_2p2_passed": fwhm_reduction
        >= float(limits["minimum_2p2mm_direct_fwhm_reduction"]),
        "sigma_1p0_passed": one_mm_degradation
        <= float(limits["maximum_1p0mm_population_sigma_degradation"]),
        "modes_2p2_passed": int(candidate["modes_2p2"])
        <= int(benchmark["modes_2p2"]),
        "modes_1p0_passed": int(candidate["modes_1p0"])
        <= int(benchmark["modes_1p0"]),
    }
    return {
        "passed": all(checks.values()),
        "sigma_2p2_reduction": sigma_reduction,
        "fwhm_2p2_reduction": fwhm_reduction,
        "sigma_1p0_degradation": one_mm_degradation,
        **checks,
    }


def _ranking_config(campaign: Mapping[str, Any]) -> tuple[float, ...]:
    design = campaign["stage_design"]["T4b"]
    tiers = tuple(float(value) for value in design["contrast_tier_upper_bounds"])
    if tiers != (3.0, 4.0, 6.0, 10.0):
        raise ValueError("contrast tier bounds differ from frozen v1 identity")
    if tuple(design["ranking_tuple"]) != RANKING_TUPLE:
        raise ValueError("ranking tuple differs from frozen v1 identity")
    return tiers


def _rank_key(campaign: Mapping[str, Any], row: _RowEvaluation) -> tuple[Any, ...]:
    if row.metrics is None:
        raise ValueError("cannot rank a row without exact metrics")
    tiers = _ranking_config(campaign)
    tier_index = next(
        (index for index, limit in enumerate(tiers) if row.contrast <= limit),
        len(tiers),
    )
    return (
        tier_index,
        row.boundary_limited,
        row.target_gate_failed,
        float(row.metrics["sigma_2p2_population_ns"]),
        float(row.metrics["fwhm_2p2_ns"]),
        float(row.metrics["sigma_1p0_population_ns"]),
        row.jacobian_condition,
        row.outer["d1_mm"],
        row.outer["l23_mm"],
        row.outer["delta_v1_v"],
        row.outer["lambda"],
    )


def _rank_rows(
    campaign: Mapping[str, Any],
    rows: Sequence[_RowEvaluation],
    benchmark: Mapping[str, Any],
    limits: Mapping[str, Any],
) -> list[_RowEvaluation]:
    prepared: list[_RowEvaluation] = []
    for row in rows:
        if not row.eligible or row.metrics is None:
            continue
        gate = _performance_gate(row.metrics, benchmark, limits)
        row.record["target_gate"] = gate
        prepared.append(
            _RowEvaluation(
                row.record,
                row.outer,
                row.inner,
                row.metrics,
                row.contrast,
                row.boundary_limited,
                row.jacobian_condition,
                not bool(gate["passed"]),
            )
        )
    return sorted(prepared, key=lambda row: _rank_key(campaign, row))


def _evaluate_outer(
    campaign: Mapping[str, Any],
    values: Mapping[str, Any],
    *,
    three_zone: bool,
    row_id: str,
) -> _RowEvaluation:
    row = {
        "row_id": row_id,
        "sequence": 0,
        "arm_role": row_id,
        "outer": _outer_dict(values),
    }
    return _evaluate_row(campaign, row, three_zone=three_zone)


def _propagated_benchmark(
    campaign: Mapping[str, Any], predecessor: Mapping[str, Any] | None
) -> _RowEvaluation | None:
    if predecessor is None or predecessor.get("best_feasible_two_zone") is None:
        return None
    return _evaluate_outer(
        campaign,
        predecessor["best_feasible_two_zone"],
        three_zone=False,
        row_id="propagated_best_feasible_two_zone",
    )


def _evaluate_plan_rows(
    campaign: Mapping[str, Any],
    plan: Mapping[str, Any],
    three_zone_roles: set[str],
) -> list[_RowEvaluation]:
    return [
        _evaluate_row(
            campaign,
            row,
            three_zone=row["arm_role"] in three_zone_roles,
        )
        for row in plan["rows"]
    ]


def _outcome(
    campaign: Mapping[str, Any],
    plan: Mapping[str, Any],
    status: str,
    conclusion: str,
    rows: Sequence[_RowEvaluation],
    *,
    ranked: Sequence[_RowEvaluation] = (),
    frozen_primary: Mapping[str, Any] | None = None,
    best_two_zone: Mapping[str, Any] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> NumericStageOutcome:
    selected = [dict(row.outer) for row in ranked[:8]]
    results: dict[str, Any] = {
        "rows": [row.record for row in rows],
        "accepted_unique_root_rows": sum(row.eligible for row in rows),
        "ambiguous_root_rows": sum(
            row.record["row_status"] == "ambiguous_multiple_accepted_roots"
            for row in rows
        ),
        "no_accepted_root_rows": sum(
            row.record["row_status"] == "no_accepted_root" for row in rows
        ),
        "ranking_tuple": list(RANKING_TUPLE),
        "selected_outer_points": selected,
    }
    if extra:
        results.update(extra)
    stage = next(
        item for item in campaign["stages"] if item["stage_id"] == plan["stage_id"]
    )
    authorized = bool(stage["transitions"][conclusion]) and status == "success"
    return NumericStageOutcome(
        status=status,
        conclusion=conclusion,
        next_stage_authorized=authorized,
        results=results,
        completed_rows=len(plan["rows"]),
        failed_rows=sum(not row.eligible for row in rows),
        selected_outer_points=selected,
        frozen_primary=(
            None if frozen_primary is None else _outer_dict(frozen_primary)
        ),
        best_feasible_two_zone=(
            None if best_two_zone is None else _outer_dict(best_two_zone)
        ),
    )


def _execute_t2(
    campaign: Mapping[str, Any], plan: Mapping[str, Any]
) -> NumericStageOutcome:
    rows = _evaluate_plan_rows(campaign, plan, set())
    baseline = next(
        (row for row in rows if row.record["arm_role"] == "current_exact_baseline"),
        None,
    )
    eligible = [
        row
        for row in rows
        if row.record["arm_role"] == "two_zone_benchmark" and row.eligible
    ]
    if baseline is None or not baseline.eligible or baseline.metrics is None or not eligible:
        return _outcome(
            campaign,
            plan,
            "failed",
            "TWO_ZONE_BENCHMARK_INCOMPLETE",
            rows,
        )
    limits = campaign["scientific_gates"]["two_zone_sufficiency_relative_to_current"]
    ranked = _rank_rows(campaign, eligible, baseline.metrics, limits)
    best = ranked[0]
    conclusion = (
        "TWO_ZONE_TARGET_MET_IN_FROZEN_DOMAIN_BRANCH"
        if not best.target_gate_failed
        else "TWO_ZONE_TARGET_NOT_MET_IN_FROZEN_DOMAIN_BRANCH"
    )
    return _outcome(
        campaign,
        plan,
        "success",
        conclusion,
        rows,
        ranked=ranked,
        best_two_zone=best.outer,
        extra={
            "current_baseline": baseline.record,
            "best_two_zone_row_id": best.record["row_id"],
            "best_two_zone_target_gate": best.record["target_gate"],
        },
    )


def _execute_t3(
    campaign: Mapping[str, Any],
    plan: Mapping[str, Any],
    predecessor: Mapping[str, Any] | None,
) -> NumericStageOutcome:
    rows = _evaluate_plan_rows(campaign, plan, {"three_zone_screen"})
    benchmark = _propagated_benchmark(campaign, predecessor)
    three_rows = [
        row for row in rows if row.record["arm_role"] == "three_zone_screen"
    ]
    best_outer = None if predecessor is None else predecessor.get("best_feasible_two_zone")
    if benchmark is None or not benchmark.eligible or benchmark.metrics is None:
        return _outcome(
            campaign,
            plan,
            "failed",
            "SPARSE_SCREEN_INCOMPLETE",
            rows,
            best_two_zone=best_outer,
        )
    limits = campaign["scientific_gates"][
        "three_zone_performance_relative_to_best_two_zone"
    ]
    ranked = _rank_rows(campaign, three_rows, benchmark.metrics, limits)
    if ranked:
        conclusion = (
            "SPARSE_THIRD_DIRECTION_AND_FINITE_WIDTH_SIGNAL_SUPPORTED"
            if not ranked[0].target_gate_failed
            else "SPARSE_NO_FINITE_WIDTH_SIGNAL_OVER_BEST_TWO_ZONE"
        )
        status = "success"
    elif any(row.record["clustered_root_count"] > 0 for row in three_rows):
        conclusion = "THIRD_DIRECTION_DEGENERATE_OR_ILL_CONDITIONED"
        status = "success"
    else:
        conclusion = "SPARSE_SCREEN_INCOMPLETE"
        status = "failed"
    return _outcome(
        campaign,
        plan,
        status,
        conclusion,
        rows,
        ranked=ranked,
        best_two_zone=best_outer,
        extra={"propagated_best_two_zone": benchmark.record},
    )


def _execute_discovery(
    campaign: Mapping[str, Any],
    plan: Mapping[str, Any],
    predecessor: Mapping[str, Any] | None,
) -> NumericStageOutcome:
    stage_id = str(plan["stage_id"])
    if stage_id == "T4a":
        design = campaign["stage_design"]["T4a"]
        if design.get("include_predecessor_selected_points_in_ranking") is not True:
            raise ValueError("T4a predecessor ranking inclusion must be true")
        if predecessor is None or not predecessor.get("selected_outer_points"):
            raise ValueError("T4a requires predecessor-selected outer points")
    rows = _evaluate_plan_rows(campaign, plan, {"three_zone_discovery"})
    supplemental: list[_RowEvaluation] = []
    if stage_id == "T4a":
        supplemental = [
            _evaluate_outer(
                campaign,
                point,
                three_zone=True,
                row_id=f"t4a_predecessor_selected_{index:02d}",
            )
            for index, point in enumerate(
                predecessor["selected_outer_points"], 1
            )
        ]
    benchmark = _propagated_benchmark(campaign, predecessor)
    best_outer = None if predecessor is None else predecessor.get("best_feasible_two_zone")
    if benchmark is None or not benchmark.eligible or benchmark.metrics is None:
        incomplete = {
            "T4a": "COARSE_SEARCH_INCOMPLETE",
            "T4b": "REFINEMENT_INCOMPLETE",
            "T4c": "FULL_DOMAIN_INCOMPLETE",
        }[stage_id]
        return _outcome(
            campaign,
            plan,
            "failed",
            incomplete,
            rows,
            best_two_zone=best_outer,
        )
    limits = campaign["scientific_gates"][
        "three_zone_performance_relative_to_best_two_zone"
    ]
    ranked = _rank_rows(campaign, [*rows, *supplemental], benchmark.metrics, limits)
    if stage_id == "T4a":
        conclusion = (
            "COARSE_THREE_ZONE_CANDIDATES_IDENTIFIED"
            if ranked
            else "COARSE_NO_VIABLE_CANDIDATE"
        )
    elif stage_id == "T4b":
        if not ranked:
            conclusion = "REFINEMENT_INCOMPLETE"
        elif not ranked[0].target_gate_failed:
            conclusion = "FINITE_WIDTH_TARGET_CANDIDATE_FOUND"
        elif ranked[0].boundary_limited:
            conclusion = "REFINEMENT_BOUNDARY_OR_COVERAGE_LIMITED"
        else:
            conclusion = "FINITE_WIDTH_IMPROVEMENT_FOUND_BELOW_TARGET"
    elif not ranked:
        conclusion = "FULL_DOMAIN_INCOMPLETE"
    elif not ranked[0].target_gate_failed:
        conclusion = "FULL_DOMAIN_TARGET_CANDIDATE_FOUND"
    else:
        conclusion = "FULL_DOMAIN_NO_TARGET_CANDIDATE"
    status = "failed" if conclusion.endswith("INCOMPLETE") else "success"
    frozen = ranked[0].outer if stage_id == "T4c" and ranked else None
    return _outcome(
        campaign,
        plan,
        status,
        conclusion,
        rows,
        ranked=ranked,
        frozen_primary=frozen,
        best_two_zone=best_outer,
        extra={
            "propagated_best_two_zone": benchmark.record,
            "supplemental_predecessor_selected_rows": [
                row.record for row in supplemental
            ],
            "supplemental_rows_in_planned_census": False,
        },
    )


def _deferred_t5(
    plan: Mapping[str, Any],
    predecessor: Mapping[str, Any],
    rows: Sequence[_RowEvaluation] = (),
) -> NumericStageOutcome:
    return NumericStageOutcome(
        status="success",
        conclusion="PRIMARY_CONFIRMATION_DEFERRED_TO_SOLVER",
        next_stage_authorized=False,
        results={
            "rows": [row.record for row in rows],
            "reason": "frozen primary or unique ideal root unavailable",
        },
        completed_rows=len(plan["rows"]),
        failed_rows=0,
        selected_outer_points=list(predecessor.get("selected_outer_points", [])),
        frozen_primary=predecessor.get("frozen_primary"),
        best_feasible_two_zone=predecessor.get("best_feasible_two_zone"),
    )


def _execute_t5(
    campaign: Mapping[str, Any],
    plan: Mapping[str, Any],
    predecessor: Mapping[str, Any] | None,
) -> NumericStageOutcome:
    if predecessor is None:
        raise ValueError("T5 requires a predecessor receipt")
    primary_outer = predecessor.get("frozen_primary")
    best_outer = predecessor.get("best_feasible_two_zone")
    if primary_outer is None or best_outer is None:
        return _deferred_t5(plan, predecessor)
    primary = _evaluate_outer(
        campaign, primary_outer, three_zone=True, row_id="frozen_primary"
    )
    best = _evaluate_outer(
        campaign, best_outer, three_zone=False, row_id="best_feasible_two_zone"
    )
    same_outer = _evaluate_outer(
        campaign,
        primary_outer,
        three_zone=False,
        row_id="same_outer_two_zone_control",
    )
    current = _evaluate_outer(
        campaign,
        campaign["fixtures"]["current_exact_baseline"]["outer"],
        three_zone=False,
        row_id="current_exact_baseline",
    )
    rows = [primary, best, same_outer, current]
    if not primary.eligible or not best.eligible or primary.metrics is None or best.metrics is None:
        return _deferred_t5(plan, predecessor, rows)
    limits = campaign["scientific_gates"][
        "three_zone_performance_relative_to_best_two_zone"
    ]
    gate = _performance_gate(primary.metrics, best.metrics, limits)
    sampling_audits = {
        row.record["row_id"]: _sampling_convergence(campaign, row)
        for row in rows
        if row.eligible
    }
    required_sampling_passed = all(
        sampling_audits[row_id]["passed"]
        for row_id in ("frozen_primary", "best_feasible_two_zone")
    )
    if gate["passed"] and required_sampling_passed:
        conclusion = "PRIMARY_CONFIRMATION_PASSED_OVER_BEST_TWO_ZONE"
    elif (
        gate["passed"]
        or gate["sigma_2p2_reduction"] > 0.0
        or gate["fwhm_2p2_reduction"] > 0.0
    ):
        conclusion = "PRIMARY_THEORY_ONLY_SUPPORTED"
    else:
        conclusion = "PRIMARY_CONFIRMATION_FAILED"
    return NumericStageOutcome(
        status="success",
        conclusion=conclusion,
        next_stage_authorized=False,
        results={
            "rows": [row.record for row in rows],
            "primary_vs_best_two_zone": gate,
            "sampling_convergence": sampling_audits,
            "required_sampling_convergence_passed": required_sampling_passed,
            "same_outer_control_available": same_outer.eligible,
            "current_baseline_available": current.eligible,
        },
        completed_rows=len(plan["rows"]),
        failed_rows=0,
        selected_outer_points=[_outer_dict(primary_outer)],
        frozen_primary=_outer_dict(primary_outer),
        best_feasible_two_zone=_outer_dict(best_outer),
    )


def execute_numeric_stage(
    campaign: Mapping[str, Any],
    plan: Mapping[str, Any],
    predecessor: Mapping[str, Any] | None,
) -> NumericStageOutcome:
    """Execute one T2/T3/T4/T5 stage using existing theory and metrics cores."""

    _ranking_config(campaign)
    stage_id = str(plan["stage_id"])
    if stage_id == "T2":
        outcome = _execute_t2(campaign, plan)
    elif stage_id == "T3":
        outcome = _execute_t3(campaign, plan, predecessor)
    elif stage_id in {"T4a", "T4b", "T4c"}:
        outcome = _execute_discovery(campaign, plan, predecessor)
    elif stage_id == "T5":
        outcome = _execute_t5(campaign, plan, predecessor)
    else:
        raise ValueError(f"{stage_id} is not a numeric theory stage")
    declared = next(
        item for item in campaign["stages"] if item["stage_id"] == stage_id
    )["conclusions"]
    if outcome.conclusion not in declared:
        raise ValueError("numeric stage emitted an undeclared conclusion")
    return outcome
