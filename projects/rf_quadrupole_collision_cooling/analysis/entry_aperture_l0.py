"""Solver-independent L0 bounds for the RF-to-oaTOF entry aperture.

This module does not choose an aperture.  It derives upper bounds that must be
frozen before any geometry candidate is generated.  The circular-tube result
is an ideal Laplace-mode reference and still requires a three-dimensional
field and high-voltage validation for the real side port.
"""

from __future__ import annotations

import argparse
import math
from typing import Any


J0_FIRST_ZERO = 2.404825557695773


def _positive_finite(value: float, label: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{label} must be positive and finite")
    return result


def gap_semi_height_ceiling_mm(
    repeller_z_mm: float,
    grid1_z_mm: float,
    entry_center_z_mm: float,
    axial_clearance_mm: float = 0.0,
) -> float:
    """Return the usable aperture semi-height between the first two electrodes.

    The aperture lies in the y-z plane.  Its z semi-axis must fit between the
    repeller and grid1 after reserving the stated clearance from each electrode.
    """

    repeller = float(repeller_z_mm)
    grid1 = float(grid1_z_mm)
    center = float(entry_center_z_mm)
    clearance = float(axial_clearance_mm)
    if not all(math.isfinite(value) for value in (repeller, grid1, center, clearance)):
        raise ValueError("gap geometry and clearance must be finite")
    if grid1 <= repeller:
        raise ValueError("grid1 must lie above the repeller")
    if not repeller < center < grid1:
        raise ValueError("entry center must lie strictly inside the first accelerator gap")
    if clearance < 0.0:
        raise ValueError("axial clearance must be non-negative")
    ceiling = min(center - repeller, grid1 - center) - clearance
    if ceiling <= 0.0:
        raise ValueError("axial clearance leaves no positive aperture semi-height")
    return ceiling


def grounded_circular_tube_radius_ceiling_mm(
    effective_length_mm: float,
    maximum_relative_leakage: float,
    mode_root: float = J0_FIRST_ZERO,
) -> float:
    """Return the ideal circular grounded-tube radius ceiling.

    L0 assumes the dominant normalized electrostatic mode decays as
    exp(-chi_01 L_eff/a).  Requiring that factor not to exceed epsilon gives
    a <= chi_01 L_eff / ln(1/epsilon).  This is not a replacement for the real
    three-dimensional aperture/fringe-field solution.
    """

    length = _positive_finite(effective_length_mm, "effective tube length")
    root = _positive_finite(mode_root, "mode root")
    leakage = float(maximum_relative_leakage)
    if not math.isfinite(leakage) or not 0.0 < leakage < 1.0:
        raise ValueError("maximum relative leakage must lie strictly between zero and one")
    return root * length / math.log(1.0 / leakage)


def coupled_longitudinal_full_width_ceiling_mm(
    *,
    nominal_energy_per_charge_v: float,
    field1_v_per_mm: float,
    reflectron_stage1_voltage_drop_v: float,
    reflectron_stage2_field_v_per_mm: float,
    reflectron_stage2_length_mm: float,
    stage2_margin_fraction: float,
    stage2_margin_absolute_mm: float = 0.0,
    intrinsic_energy_half_range_v: float = 0.0,
) -> float:
    """Return the source-correlated axial full-width ceiling of the fixed design.

    The current coupled oaTOF design requires the available stage-2 length to
    cover the high-energy penetration depth plus its frozen margin.  Solving
    that inequality for the spatially correlated source width gives this L0
    ceiling.  A directly admitting entry aperture must not expose a larger
    axial full height unless a validated transfer map proves a tighter capture
    stop downstream.
    """

    nominal = _positive_finite(nominal_energy_per_charge_v, "nominal energy")
    field1 = _positive_finite(field1_v_per_mm, "accelerator field 1")
    stage1_voltage = _positive_finite(
        reflectron_stage1_voltage_drop_v, "reflectron stage-1 voltage drop"
    )
    field2 = _positive_finite(reflectron_stage2_field_v_per_mm, "reflectron field 2")
    length2 = _positive_finite(reflectron_stage2_length_mm, "reflectron stage-2 length")
    margin_fraction = float(stage2_margin_fraction)
    margin_absolute = float(stage2_margin_absolute_mm)
    intrinsic = float(intrinsic_energy_half_range_v)
    if not all(math.isfinite(value) for value in (
        margin_fraction, margin_absolute, intrinsic
    )):
        raise ValueError("margin and intrinsic energy inputs must be finite")
    if margin_fraction < 0.0 or margin_absolute < 0.0 or intrinsic < 0.0:
        raise ValueError("margin and intrinsic energy inputs must be non-negative")
    if margin_absolute >= length2:
        raise ValueError("absolute stage-2 margin must be smaller than stage-2 length")
    maximum_energy = (
        stage1_voltage
        + field2 * (length2 - margin_absolute) / (1.0 + margin_fraction)
    )
    spatial_half_range = maximum_energy - nominal - intrinsic
    if spatial_half_range <= 0.0:
        raise ValueError("fixed reflectron leaves no positive spatial-energy envelope")
    return 2.0 * spatial_half_range / field1


def validate_feasible_axial_aperture(
    *,
    design_full_height_mm: float,
    required_full_height_mm: float,
    theoretical_full_height_bounds_mm: list[float],
    safety_factor: float,
) -> float:
    """Fail closed unless a proposed aperture lies inside its frozen interval."""

    design = _positive_finite(design_full_height_mm, "design full height")
    required = _positive_finite(required_full_height_mm, "required full height")
    if not theoretical_full_height_bounds_mm:
        raise ValueError("at least one theoretical upper bound is required")
    bounds = [
        _positive_finite(value, "theoretical full-height bound")
        for value in theoretical_full_height_bounds_mm
    ]
    factor = float(safety_factor)
    if not math.isfinite(factor) or not 0.0 < factor < 1.0:
        raise ValueError("safety factor must lie strictly between zero and one")
    safe_upper = factor * min(bounds)
    if required > design:
        raise ValueError("design aperture is smaller than the required beam envelope")
    if not design < safe_upper:
        raise ValueError("design aperture must be strictly below the safety-factored theory ceiling")
    return safe_upper


def evaluate_entry_aperture_l0(
    *,
    repeller_z_mm: float,
    grid1_z_mm: float,
    entry_center_z_mm: float,
    axial_clearance_mm: float | None = None,
    effective_tube_length_mm: float | None = None,
    maximum_relative_leakage: float | None = None,
) -> dict[str, Any]:
    """Evaluate known bounds without inventing unresolved design inputs."""

    absolute_gap = gap_semi_height_ceiling_mm(
        repeller_z_mm, grid1_z_mm, entry_center_z_mm, 0.0
    )
    gap_with_clearance = None
    if axial_clearance_mm is not None:
        gap_with_clearance = gap_semi_height_ceiling_mm(
            repeller_z_mm,
            grid1_z_mm,
            entry_center_z_mm,
            axial_clearance_mm,
        )

    tube_ceiling = None
    if (effective_tube_length_mm is None) != (maximum_relative_leakage is None):
        raise ValueError("tube length and leakage tolerance must be supplied together")
    if effective_tube_length_mm is not None and maximum_relative_leakage is not None:
        tube_ceiling = grounded_circular_tube_radius_ceiling_mm(
            effective_tube_length_mm, maximum_relative_leakage
        )

    active_bounds = [value for value in (gap_with_clearance, tube_ceiling) if value is not None]
    return {
        "absolute_gap_semi_height_ceiling_mm": absolute_gap,
        "gap_semi_height_ceiling_with_clearance_mm": gap_with_clearance,
        "ideal_grounded_tube_radius_ceiling_mm": tube_ceiling,
        "combined_l0_upper_bound_mm": min(active_bounds) if active_bounds else None,
        "final_design_value_available": bool(active_bounds) and axial_clearance_mm is not None
        and tube_ceiling is not None,
    }


def self_check() -> None:
    result = evaluate_entry_aperture_l0(
        repeller_z_mm=-19.92918680341103,
        grid1_z_mm=-16.92918680341103,
        entry_center_z_mm=-18.42918680341103,
    )
    if not math.isclose(
        result["absolute_gap_semi_height_ceiling_mm"], 1.5, rel_tol=0.0, abs_tol=1e-12
    ):
        raise RuntimeError("oaTOF first-gap L0 vector changed")
    tube = grounded_circular_tube_radius_ceiling_mm(4.0, math.exp(-J0_FIRST_ZERO * 2.0))
    if not math.isclose(tube, 2.0, rel_tol=0.0, abs_tol=1e-12):
        raise RuntimeError("grounded-tube attenuation vector changed")
    longitudinal = coupled_longitudinal_full_width_ceiling_mm(
        nominal_energy_per_charge_v=2000.0,
        field1_v_per_mm=160.0,
        reflectron_stage1_voltage_drop_v=1628.8001,
        reflectron_stage2_field_v_per_mm=(2531.1999 - 1628.8001) / 96.1563,
        reflectron_stage2_length_mm=96.1563,
        stage2_margin_fraction=1.0,
    )
    if not math.isclose(longitudinal, 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise RuntimeError("coupled-longitudinal aperture vector changed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", required=True)
    parser.parse_args()
    self_check()
    print("ENTRY_APERTURE_L0=PASS DESIGN_VALUE_AVAILABLE=false")


if __name__ == "__main__":
    main()
