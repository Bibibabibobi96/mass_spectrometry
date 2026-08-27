"""Versioned plan and automatic conclusions for ideal axial source comparisons.

This is an exploratory, solver-free experiment, not the historical three-zone
design-search funnel. Negative scientific results do not stop independent scans.
"""

from __future__ import annotations

from itertools import product
from typing import Any

import numpy as np

from common.contracts.particle_count_policy import (
    load_particle_count_policy,
    validate_positive_particle_count,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_source_comparison import (
    NumericalSourceSpec,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.three_zone_ideal_theory import (
    OuterGeometry,
    ReflectronGeometry,
)


def _keys(value: dict[str, Any], expected: str, label: str) -> None:
    if not isinstance(value, dict) or set(value) != set(expected.split()):
        raise ValueError(f"{label}: missing or unknown fields; expected {expected}")


def _numbers(values: list[Any], label: str, *, positive: bool = False) -> None:
    if not values or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in values):
        raise ValueError(f"{label}: requires numeric values")
    if not np.all(np.isfinite(values)) or min(values) < 0 or (positive and min(values) == 0):
        raise ValueError(f"{label}: requires finite {'positive' if positive else 'nonnegative'} values")


def validate_experiment(config: dict[str, Any]) -> None:
    """Reject missing/unknown fields and invalid domains before any calculation."""
    _keys(config, "schema_version role source outer reflectron focus_drift_mm three_zone_eta sampling residual_scan width_scan analysis_contract scope", "experiment")
    if config["schema_version"] != 1 or config["role"] != "ideal_source_comparison":
        raise ValueError("unsupported ideal-source experiment schema or role")
    for key, cls in (("source", NumericalSourceSpec), ("outer", OuterGeometry), ("reflectron", ReflectronGeometry)):
        _keys(config[key], " ".join(cls.__dataclass_fields__), key)
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in config[key].values()):
            raise ValueError(f"{key}: physical parameters must be numbers, not booleans or strings")
        cls(**config[key])
    _numbers([config["focus_drift_mm"]], "focus_drift_mm")
    eta = config["three_zone_eta"]
    if isinstance(eta, bool) or not isinstance(eta, (float, int)) or not np.isfinite(eta) or eta == 0:
        raise ValueError("three_zone_eta must be finite and nonzero; zero is the two-zone control")
    _keys(config["sampling"], "particle_count replicate_count", "sampling")
    load_particle_count_policy()
    validate_positive_particle_count(config["sampling"]["particle_count"])
    validate_positive_particle_count(config["sampling"]["replicate_count"])
    if config["sampling"]["particle_count"] < 3:
        raise ValueError("direct peak metrics require at least three particles")
    _keys(config["residual_scan"], "full_width_mm residual_sigma_m_per_s minimum_low_residual_gain_percent maximum_high_residual_gain_percent", "residual_scan")
    _keys(config["width_scan"], "full_widths_mm residual_sigma_m_per_s minimum_resolution minimum_model_arrival_fraction", "width_scan")
    for section in ("residual_scan", "width_scan"):
        values = config[section]["residual_sigma_m_per_s"]
        _numbers(values, section)
        if values != sorted(set(values)):
            raise ValueError(f"{section}: residual sigmas must be strictly increasing")
    if len(config["residual_scan"]["residual_sigma_m_per_s"]) < 2:
        raise ValueError("residual scan needs distinct low and high residuals")
    widths = config["width_scan"]["full_widths_mm"]
    _numbers(widths + [config["residual_scan"]["full_width_mm"]], "width", positive=True)
    if widths != sorted(set(widths)):
        raise ValueError("source widths must be strictly increasing")
    _numbers([config["width_scan"]["minimum_resolution"]], "minimum_resolution", positive=True)
    _numbers([config["residual_scan"][k] for k in ("minimum_low_residual_gain_percent", "maximum_high_residual_gain_percent")], "gain thresholds")
    fraction = config["width_scan"]["minimum_model_arrival_fraction"]
    _numbers([fraction], "minimum_model_arrival_fraction", positive=True)
    if fraction > 1:
        raise ValueError("minimum_model_arrival_fraction cannot exceed one")
    if config["analysis_contract"] != "config/analysis_contract.json":
        raise ValueError("use the project's canonical analysis contract")
    if not isinstance(config["scope"], str) or not config["scope"].strip():
        raise ValueError("scope must describe the experiment boundary")


def build_case_plan(config: dict[str, Any], seed: int) -> list[dict[str, Any]]:
    """Return residual-first cases; every comparison uses the same IDs and draws."""
    validate_experiment(config)
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    cases: list[dict[str, Any]] = []
    for stage in ("residual_scan", "width_scan"):
        widths = [config[stage]["full_width_mm"]] if stage == "residual_scan" else config[stage]["full_widths_mm"]
        for sigma, width, replicate in product(config[stage]["residual_sigma_m_per_s"], widths, range(config["sampling"]["replicate_count"])):
            cases.append({"case_id": f"{stage}__{len(cases) + 1:04d}", "stage": stage,
                          "residual_sigma_m_per_s": sigma, "full_width_mm": width,
                          "seed": seed + replicate, "replicate": replicate})
    return cases


def summarize_stage(stage: str, records: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    """Separate executable success from support for the predeclared hypothesis.

Replicate ranges are not confidence intervals. Acceptance is the contiguous
tested width range from the smallest width, not a global or interpolated limit.
"""
    if not records:
        raise ValueError("cannot conclude a stage with no cases")
    if stage not in {"residual_scan", "width_scan"}:
        raise ValueError(f"unknown experiment stage: {stage}")
    widths = [config[stage]["full_width_mm"]] if stage == "residual_scan" else config[stage]["full_widths_mm"]
    expected = set(product(config[stage]["residual_sigma_m_per_s"], widths, range(config["sampling"]["replicate_count"])))
    actual = [(r["case"]["residual_sigma_m_per_s"], r["case"]["full_width_mm"], r["case"]["replicate"]) for r in records]
    if set(actual) != expected or len(actual) != len(expected) or any(r["case"]["stage"] != stage for r in records):
        raise ValueError("incomplete or duplicate stage cases; no scientific conclusion")
    if stage == "residual_scan":
        sigmas = config[stage]["residual_sigma_m_per_s"]
        groups = []
        for sigma in sigmas:
            subset = [r for r in records if r["case"]["residual_sigma_m_per_s"] == sigma]
            gains = [r["resolution_gain_percent"] for r in subset]
            eligible = all(r["comparison_eligible"] for r in subset)
            valid = [g for g in gains if g is not None]
            groups.append({"residual_sigma_m_per_s": sigma, "eligible": eligible,
                           "gain_percent_min": min(valid) if valid else None,
                           "gain_percent_max": max(valid) if valid else None})
        endpoints = (groups[0], groups[-1])
        eligible = all(g["eligible"] for g in endpoints)
        low_passed = eligible and endpoints[0]["gain_percent_min"] >= config[stage]["minimum_low_residual_gain_percent"]
        high_passed = eligible and endpoints[1]["gain_percent_max"] <= config[stage]["maximum_high_residual_gain_percent"]
        supported = low_passed and high_passed
        decision = "SUPPORTED" if supported else "NOT_SUPPORTED" if eligible else "INCONCLUSIVE"
        reasons = []
        if not eligible:
            reasons.append("ENDPOINT_INCOMPLETE_COHORT_OR_UNDEFINED_PEAK")
        elif not low_passed:
            reasons.append("LOW_RESIDUAL_GAIN_BELOW_DECLARED_TARGET")
        if eligible and not high_passed:
            reasons.append("GAIN_REMAINS_ABOVE_THRESHOLD_AT_MAXIMUM_TESTED_RESIDUAL")
        return {"stage": stage, "execution_status": "success", "scientific_status": decision,
                "reason": "; ".join(reasons) if reasons else "Both declared endpoint gain thresholds passed across every seed.",
                "low_residual_gain_supported": bool(low_passed),
                "high_residual_limited_gain_supported": bool(high_passed),
                "endpoint_gain_attenuation_supported": bool(eligible and endpoints[0]["gain_percent_min"] > endpoints[1]["gain_percent_max"]),
                "groups": groups, "uncertainty": "range across source seeds, not a confidence interval"}
    acceptance = []
    for sigma in config[stage]["residual_sigma_m_per_s"]:
        for arm in ("two_zone_matched", "three_zone_matched"):
            widths = []
            prefix_open = True
            last_pass = None
            first_fail = None
            first_unknown = None
            for width in config[stage]["full_widths_mm"]:
                subset = [r["arms"][arm] for r in records if r["case"]["residual_sigma_m_per_s"] == sigma and r["case"]["full_width_mm"] == width]
                unknown = any(r["resolution"] is None or r.get("classification_counts", {}).get("reflectron_stage1_turn_model_unsupported", 0) > 0 for r in subset)
                passed = not unknown and all(r["resolution"] >= config[stage]["minimum_resolution"] and r["model_arrival_fraction"] >= config[stage]["minimum_model_arrival_fraction"] for r in subset)
                widths.append({"full_width_mm": width, "accepted_all_seeds": passed,
                               "status": "INCONCLUSIVE" if unknown else "PASS" if passed else "FAIL",
                               "reason": "undefined peak or unsupported event topology" if unknown else "resolution and model reachability thresholds"})
                if prefix_open and passed:
                    last_pass = width
                elif prefix_open:
                    if unknown:
                        first_unknown = width
                    else:
                        first_fail = width
                    prefix_open = False
            acceptance.append({"residual_sigma_m_per_s": sigma, "arm": arm,
                               "contiguous_tested_accepted_width_mm": last_pass,
                               "first_failing_width_mm": first_fail,
                               "first_inconclusive_width_mm": first_unknown,
                               "upper_limit_bracketed": last_pass is not None and first_fail is not None,
                               "widths": widths})
    uncertain = any(any(w["status"] == "INCONCLUSIVE" for w in row["widths"]) for row in acceptance)
    return {"stage": stage, "execution_status": "success", "scientific_status": "INCONCLUSIVE" if uncertain else "CHARACTERIZED",
            "reason": "Acceptance reported separately for each residual; pass requires R and full-mother model arrival fraction in every seed. No global optimum or physical aperture acceptance claim.",
            "acceptance": acceptance, "uncertainty": "all declared seeds; no interpolated boundary"}
