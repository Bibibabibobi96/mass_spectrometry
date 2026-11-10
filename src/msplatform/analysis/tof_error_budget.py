"""Plan TOF error budgets from explicit resolution requirements, without a solver.

This is a planning calculation, not a peak measurement or qualification gate.
The Gaussian estimates follow FWHM = sqrt(8 ln 2) sigma and variance addition;
they do not replace the repository's direct KDE-FWHM measurement.
"""

from __future__ import annotations

import argparse
import json
import math
from numbers import Real
from typing import Any, Sequence


GAUSSIAN_FWHM_FACTOR = math.sqrt(8.0 * math.log(2.0))


def _finite_number(value: float, name: str, *, allow_zero: bool = False) -> float:
    """Reject nonnumeric, nonfinite and out-of-range scalar inputs."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a real number")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(number) or number < 0 or (number == 0 and not allow_zero):
        domain = "nonnegative" if allow_zero else "positive"
        raise ValueError(f"{name} must be finite and {domain}")
    return number


def calculate_tof_error_budget(
    flight_time_s: float,
    reference_resolution: float,
    *,
    minimum_resolution: float,
    mass_bias_limit_ppm: float | None = None,
) -> dict[str, Any]:
    """Return versioned planning budgets; all returned times are in seconds.

    ``reference_resolution`` describes the peak before adding numerical error;
    ``minimum_resolution`` is the lowest acceptable resolving power, using
    R = T / (2 FWHM) with the same fixed flight time T. Gaussian budgets are
    standard deviations (zero-mean RMS), not maximum individual timing errors.
    A stricter target than the reference returns null noise budgets, not zero.

    Optional mass bias assumes a fixed external calibration m proportional to
    t squared. Its symmetric time bound protects both signs of a common shift;
    it does not allocate peak broadening. ppm must be in [0, 1e6).
    Invalid inputs or nonrepresentable derived values raise ValueError.
    No files, measurements or solver settings are changed.
    """
    flight_time_s = _finite_number(flight_time_s, "flight_time_s")
    reference_resolution = _finite_number(reference_resolution, "reference_resolution")
    minimum_resolution = _finite_number(minimum_resolution, "minimum_resolution")
    if mass_bias_limit_ppm is not None:
        mass_bias_limit_ppm = _finite_number(
            mass_bias_limit_ppm, "mass_bias_limit_ppm", allow_zero=True
        )
        if mass_bias_limit_ppm >= 1e6:
            raise ValueError("mass_bias_limit_ppm must be less than 1e6")

    reference_width = (flight_time_s / reference_resolution) * 0.5
    maximum_width = (flight_time_s / minimum_resolution) * 0.5
    fractional_headroom = (reference_resolution - minimum_resolution) / minimum_resolution
    # Equivalent to maximum_width - reference_width, avoiding close subtraction.
    width_margin = reference_width * fractional_headroom
    reference_sigma = reference_width / GAUSSIAN_FWHM_FACTOR
    reference_meets_target = reference_resolution >= minimum_resolution
    independent_sigma = correlated_sigma = None
    if reference_meets_target:
        h = fractional_headroom
        independent_sigma = reference_sigma * math.sqrt(h * (2.0 + h))
        correlated_sigma = reference_sigma * h

    bias_limit = None
    if mass_bias_limit_ppm is not None:
        fraction = mass_bias_limit_ppm * 1e-6
        # Rationalized sqrt(1 + fraction) - 1 preserves small nonzero budgets.
        bias_limit = flight_time_s * (fraction / (math.sqrt(1.0 + fraction) + 1.0))

    derived = {
        "reference_fwhm_s": reference_width,
        "maximum_fwhm_s": maximum_width,
        "remaining_fwhm_margin_s": width_margin,
        "reference_sigma_s": reference_sigma,
        "fractional_width_headroom": fractional_headroom,
        "independent_zero_mean_sigma_limit_s": independent_sigma,
        "worst_positive_correlation_sigma_limit_s": correlated_sigma,
        "maximum_absolute_bias_s": bias_limit,
    }
    for name, value in derived.items():
        if value is not None and not math.isfinite(value):
            raise ValueError(f"derived {name} is not finite")
    if min(reference_width, maximum_width, reference_sigma) <= 0:
        raise ValueError("derived reference/limit widths are below float representability")

    return {
        "schema_version": 1,
        "role": "tof_error_budget",
        "qualification": False,
        "flight_time_s": flight_time_s,
        "reference_resolution": reference_resolution,
        "minimum_resolution": minimum_resolution,
        "reference_meets_target": reference_meets_target,
        "reference_fwhm_s": reference_width,
        "maximum_fwhm_s": maximum_width,
        "remaining_fwhm_margin_s": width_margin,
        "gaussian_planning": {
            "reference_sigma_s": reference_sigma,
            "independent_zero_mean_sigma_limit_s": independent_sigma,
            "worst_positive_correlation_sigma_limit_s": correlated_sigma,
        },
        "common_bias": {
            "mass_bias_limit_ppm": mass_bias_limit_ppm,
            "maximum_absolute_bias_s": bias_limit,
        },
        "assumptions": [
            "Resolution uses T/(2 FWHM) at fixed T; the reference excludes added error.",
            "Gaussian planning only: a Gaussian reference peak and zero-mean timing error.",
            "Independent limit assumes independent Gaussian noise and variance addition.",
            "Positive-correlation limit assumes affine Gaussian broadening at correlation +1.",
            "Limits are standard deviations/RMS, not per-particle maximum-error limits.",
            "No dt, rtol, mesh, non-Gaussian KDE-FWHM or physical-qualification guarantee.",
            "A common additive time shift does not broaden a peak.",
            "Optional bias bound assumes fixed external m proportional to t squared; "
            "both signs are bounded and no recalibration is assumed.",
        ],
    }


def _render_markdown(result: dict[str, Any]) -> str:
    """Render calculated values only, converting seconds to us or ps for display."""
    gaussian = result["gaussian_planning"]
    bias = result["common_bias"]
    rows = [
        ("Flight time T", result["flight_time_s"], 1e6, "us"),
        ("Reference resolution R_ref", result["reference_resolution"], 1, "dimensionless"),
        ("Minimum resolution R_min", result["minimum_resolution"], 1, "dimensionless"),
        ("Reference FWHM", result["reference_fwhm_s"], 1e12, "ps"),
        ("Maximum FWHM", result["maximum_fwhm_s"], 1e12, "ps"),
        ("Remaining FWHM margin", result["remaining_fwhm_margin_s"], 1e12, "ps"),
        ("Independent Gaussian sigma budget", gaussian["independent_zero_mean_sigma_limit_s"], 1e12, "ps"),
        ("Positive-correlated Gaussian sigma budget", gaussian["worst_positive_correlation_sigma_limit_s"], 1e12, "ps"),
        ("Specified mass-bias limit", bias["mass_bias_limit_ppm"], 1, "ppm"),
        ("Maximum absolute common bias", bias["maximum_absolute_bias_s"], 1e12, "ps"),
    ]
    lines = ["**Planning only; not qualification.**", "",
             f"Reference meets target: {'yes' if result['reference_meets_target'] else 'no'}.",
             "", "| Quantity | Value | Unit |", "|---|---:|---|"]
    for label, value, factor, unit in rows:
        display = "Not allocated / not applicable"
        if value is not None:
            converted = value * factor
            if not math.isfinite(converted):
                raise ValueError(f"display unit conversion for {label} is not finite")
            display = format(converted, ".12g")
        lines.append(f"| {label} | {display} | {unit} |")
    lines.extend(["", "**RMS budgets are not per-particle maximum errors, dt or rtol.**", ""])
    lines.extend(f"- {assumption}" for assumption in result["assumptions"])
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Print JSON or Markdown for microsecond CLI inputs; invalid requests exit 2."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flight-time-us", type=float, required=True)
    parser.add_argument("--reference-resolution", type=float, required=True)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--minimum-resolution", type=float)
    target.add_argument(
        "--max-resolution-loss-pct", type=float,
        help="Allowed decrease from reference resolving power, in [0, 100).",
    )
    parser.add_argument("--mass-bias-ppm", type=float)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args(argv)
    try:
        reference = _finite_number(args.reference_resolution, "reference_resolution")
        minimum = args.minimum_resolution
        if args.max_resolution_loss_pct is not None:
            loss = _finite_number(
                args.max_resolution_loss_pct, "max_resolution_loss_pct", allow_zero=True
            )
            if loss >= 100:
                raise ValueError("max_resolution_loss_pct must be less than 100")
            minimum = reference * (1.0 - loss / 100.0)
        result = calculate_tof_error_budget(
            _finite_number(args.flight_time_us, "flight_time_us") * 1e-6,
            reference,
            minimum_resolution=minimum,
            mass_bias_limit_ppm=args.mass_bias_ppm,
        )
        rendered = (_render_markdown(result) if args.format == "markdown"
                    else json.dumps(result, indent=2, allow_nan=False))
    except ValueError as exc:
        parser.error(str(exc))
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
