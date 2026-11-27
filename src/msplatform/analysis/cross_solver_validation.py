"""Compare a recorded OA cross-solver result with its canonical metrics."""

from __future__ import annotations

import math
from typing import Any


def _require_close(label: str, actual: float, expected: float) -> None:
    if not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-12):
        raise ValueError(f"{label} mismatch: {actual} != {expected}")


def validate_cross_solver_metrics(record: dict[str, Any], comparison: dict[str, Any]) -> None:
    """Validate the frozen v1–v5 metric representations without file I/O.

    The pre-existing tolerances apply only to recorded metric equality; this
    function does not qualify a solver, mesh, publication or instrument.
    """
    if comparison["status"] != "PASS":
        raise ValueError("Canonical comparison result did not pass")
    if record.get("schema_version", 0) >= 5:
        for side, solver in (("left", "comsol"), ("right", "simion")):
            if comparison[side]["metrics"] != record[solver]["metrics"]:
                raise ValueError(f"{solver} canonical metrics differ from Formal record")
        if comparison["comparison"] != record["comparison"]:
            raise ValueError("Canonical comparison block differs from Formal record")
        return

    for side, solver in (("left", "comsol"), ("right", "simion")):
        metrics = comparison[side]["metrics"]
        for key in (
            "mean_tof_us",
            "direct_fwhm_tof_ns",
            "direct_fwhm_mass_Da",
            "mass_resolution",
            "tof_skewness",
            "hwhm_asymmetry_right_over_left",
            "significant_kde_modes",
        ):
            _require_close(f"{solver}.{key}", metrics[key], record[solver][key])
        for key in (
            "impact_centroid_x_mm",
            "impact_centroid_y_mm",
            "impact_rms_radius_mm",
        ):
            _require_close(
                f"{solver}.{key}", metrics["detector"][key], record[solver][key]
            )

    canonical_comparison = comparison["comparison"]
    for key in (
        "mean_tof_difference_right_minus_left_ns",
        "standardized_kde_overlap",
        "standardized_ks_distance",
        "standardized_ks_pvalue",
        "paired_standardized_tof_correlation",
        "bootstrap_absolute_resolution_difference_pct_p2p5",
        "bootstrap_absolute_resolution_difference_pct_median",
        "bootstrap_absolute_resolution_difference_pct_p97p5",
    ):
        record_key = (
            "mean_tof_difference_simion_minus_comsol_ns"
            if key == "mean_tof_difference_right_minus_left_ns"
            else key
        )
        _require_close(
            f"comparison.{key}",
            canonical_comparison[key],
            record["comparison"][record_key],
        )
    detector_comparison = canonical_comparison["detector_landing"]
    for result_key, record_key in (
        ("centroid_distance_mm", "detector_centroid_distance_mm"),
        ("paired_mean_landing_distance_mm", "paired_mean_landing_distance_mm"),
        ("paired_rms_landing_distance_mm", "paired_rms_landing_distance_mm"),
        ("paired_max_landing_distance_mm", "paired_max_landing_distance_mm"),
    ):
        _require_close(
            f"comparison.detector_landing.{result_key}",
            detector_comparison[result_key],
            record["comparison"][record_key],
        )

    resolution_difference = 100.0 * (
        record["comsol"]["mass_resolution"] - record["simion"]["mass_resolution"]
    ) / record["simion"]["mass_resolution"]
    _require_close(
        "comparison.comsol_resolution_higher_than_simion_pct",
        resolution_difference,
        record["comparison"]["comsol_resolution_higher_than_simion_pct"],
    )
