"""Solver-independent L0 reference calculations for an ideal quadrupole.

The voltage convention follows ``docs/multipoles``: ``U`` and ``V`` are the
DC and RF amplitudes of one rod group about the common-mode axis voltage, and
``V`` is zero-to-peak.  The opposite rod group receives the negative of those
differential components.  A common-mode offset does not enter the ideal
transverse Mathieu parameters.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from scipy.constants import atomic_mass, elementary_charge
from scipy.optimize import brentq
from scipy.special import mathieu_a, mathieu_b

from common.multipole.family_contract import from_quadrupole_contract


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = PROJECT_ROOT / "config" / "baseline.json"
DEFAULT_MODE = PROJECT_ROOT / "config" / "modes" / "mass_filter_reference.json"

FIELD_MODEL_ID = "quadrupole.ideal_linear.mathieu.v1"
VOLTAGE_CONVENTION_ID = "multipole.pair_about_common_mode.zero_to_peak.v1"
COORDINATE_CONVENTION_ID = "multipole.cartesian.z_axis.v1"


def _positive(name: str, value: float) -> float:
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return value


def mathieu_parameters(
    mass_to_charge_th: float,
    dc_amplitude_v_per_group: float,
    rf_amplitude_v_zero_to_peak_per_group: float,
    r0_mm: float,
    frequency_hz: float,
) -> dict[str, float]:
    """Return positive-magnitude ``a`` and ``q`` for the documented convention."""
    mu = _positive("mass_to_charge_th", mass_to_charge_th)
    r0_m = _positive("r0_mm", r0_mm) * 1e-3
    frequency = _positive("frequency_hz", frequency_hz)
    rf_amplitude = _positive(
        "rf_amplitude_v_zero_to_peak_per_group",
        rf_amplitude_v_zero_to_peak_per_group,
    )
    dc_amplitude = float(dc_amplitude_v_per_group)
    if not math.isfinite(dc_amplitude) or dc_amplitude < 0:
        raise ValueError("dc_amplitude_v_per_group must be finite and non-negative")

    omega = 2.0 * math.pi * frequency
    mass_per_charge_kg_per_e = mu * atomic_mass
    denominator = mass_per_charge_kg_per_e * r0_m**2 * omega**2
    return {
        "a": 8.0 * elementary_charge * dc_amplitude / denominator,
        "q": 4.0 * elementary_charge * rf_amplitude / denominator,
    }


def mass_to_charge_th(
    q_cal: float,
    rf_amplitude_v_zero_to_peak_per_group: float,
    r0_mm: float,
    frequency_hz: float,
) -> float:
    """Return the mass-to-charge scale in Th for a positive ``q`` magnitude."""
    q_value = _positive("q_cal", q_cal)
    r0_m = _positive("r0_mm", r0_mm) * 1e-3
    frequency = _positive("frequency_hz", frequency_hz)
    rf_amplitude = _positive(
        "rf_amplitude_v_zero_to_peak_per_group",
        rf_amplitude_v_zero_to_peak_per_group,
    )
    omega = 2.0 * math.pi * frequency
    return (
        4.0
        * elementary_charge
        * rf_amplitude
        / (q_value * atomic_mass * r0_m**2 * omega**2)
    )


def first_stability_apex() -> dict[str, float]:
    """Return the first-region intersection of ``-a0(q)`` and ``b1(q)``."""
    q_apex = brentq(lambda q: -mathieu_a(0, q) - mathieu_b(1, q), 0.6, 0.8)
    return {"a": float(-mathieu_a(0, q_apex)), "q": float(q_apex)}


def rf_only_cutoff() -> float:
    """Return the positive first-region cutoff on the ``a=0`` axis."""
    return float(brentq(lambda q: mathieu_b(1, q), 0.8, 1.0))


def scanline_passband(u_over_v: float) -> dict[str, float]:
    """Return ideal first-region intersections for a fixed ``U/V`` line."""
    ratio = _positive("u_over_v", u_over_v)
    apex = first_stability_apex()
    apex_ratio = apex["a"] / (2.0 * apex["q"])
    if ratio >= apex_ratio:
        raise ValueError(f"u_over_v must be below the first-region apex ratio {apex_ratio:.12g}")

    slope = 2.0 * ratio
    q_in = brentq(lambda q: -mathieu_a(0, q) - slope * q, 1e-12, apex["q"])
    q_out = brentq(lambda q: mathieu_b(1, q) - slope * q, apex["q"], rf_only_cutoff())
    resolving_power = (q_in + q_out) / (2.0 * (q_out - q_in))
    q_cal = 2.0 * q_in * q_out / (q_in + q_out)
    return {
        "u_over_v": ratio,
        "q_in": float(q_in),
        "q_out": float(q_out),
        "q_cal": float(q_cal),
        "resolving_power_stability": float(resolving_power),
    }


def validate_mass_filter_reference(baseline: dict[str, Any], mode: dict[str, Any]) -> dict[str, Any]:
    """Validate the frozen mass-filter reference without claiming numerical qualification."""
    operating = from_quadrupole_contract(baseline, mode)
    if mode.get("schema_version") != 3:
        raise ValueError("mass-filter reference schema_version must be 3")
    if mode.get("mode") != "mass_filter_reference":
        raise ValueError("mode must be mass_filter_reference")
    allowed_statuses = {
        "simion_functional_scan_pass",
        "dual_solver_functional_scan_pass",
        "n100_dual_solver_revalidation_pending",
    }
    if mode.get("status") not in allowed_statuses:
        raise ValueError("mass-filter reference must record an approved functional status")
    if mode["status"] == "dual_solver_functional_scan_pass":
        comsol_screen = mode.get("comsol_screen", {})
        if comsol_screen.get("status") != "pass" or not comsol_screen.get("authority_run_id"):
            raise ValueError("dual-solver status requires a passing COMSOL authority run")
    if mode["status"] == "n100_dual_solver_revalidation_pending":
        for screen_name in ("solver_screen", "comsol_screen"):
            screen = mode.get(screen_name, {})
            if screen.get("status") != "pending_n100_revalidation":
                raise ValueError(f"{screen_name} must remain pending until an N=100 run passes")
            if screen.get("authority_run_id") is not None:
                raise ValueError(f"{screen_name} cannot cite a pre-N=100 authority run")
            if int(screen.get("particles_per_mass", 0)) != 100:
                raise ValueError(f"{screen_name} must require 100 particles per mass")

    theory = mode.get("theory_contract", {})
    expected_contract = {
        "model_level": "L0",
        "field_model_id": FIELD_MODEL_ID,
        "coordinate_convention_id": COORDINATE_CONVENTION_ID,
        "voltage_convention_id": VOLTAGE_CONVENTION_ID,
    }
    for key, expected in expected_contract.items():
        if theory.get(key) != expected:
            raise ValueError(f"theory_contract.{key} must be {expected!r}")

    voltage = theory.get("voltage", {})
    required_voltage_metadata = {
        "reference": "one_rod_group_about_axis_common_mode",
        "amplitude_type": "zero_to_peak",
        "polarity_groups": ["axis_offset_plus_W", "axis_offset_minus_W"],
        "waveform": "sinusoidal",
    }
    for key, expected in required_voltage_metadata.items():
        if voltage.get(key) != expected:
            raise ValueError(f"theory_contract.voltage.{key} must be {expected!r}")

    rf = mode["rf"]
    common_mode_offset = float(rf["axis_common_mode_offset_V"])
    if not math.isfinite(common_mode_offset):
        raise ValueError("axis_common_mode_offset_V must be finite")
    r0_mm = operating.geometry.r0_mm
    if not math.isclose(float(rf["effective_radius_mm"]), r0_mm, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("mass-filter effective radius must equal baseline field_radius_r0")

    rf_amplitude = operating.voltage.rf_amplitude_v_per_group
    dc_amplitude = operating.voltage.dc_amplitude_v_per_group
    expected_dc = rf_amplitude * float(rf["percent_tune"]) / 100.0 * float(rf["apex_U_over_V_reference"])
    if not math.isclose(dc_amplitude, expected_dc, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError("mass-filter DC amplitude does not match the frozen SIMION tune rule")

    parameters = mathieu_parameters(
        mass_to_charge_th=float(rf["tune_mass_Th"]),
        dc_amplitude_v_per_group=dc_amplitude,
        rf_amplitude_v_zero_to_peak_per_group=rf_amplitude,
        r0_mm=r0_mm,
        frequency_hz=float(rf["frequency_Hz"]),
    )
    passband = scanline_passband(dc_amplitude / rf_amplitude)
    return {
        "status": "PASS",
        "mode_status": mode["status"],
        "a_at_tune_mass": parameters["a"],
        "q_at_tune_mass": parameters["q"],
        "u_over_v": dc_amplitude / rf_amplitude,
        "axis_common_mode_offset_V": common_mode_offset,
        "dc_differential_V": 2.0 * dc_amplitude,
        "rf_differential_V_zero_to_peak": 2.0 * rf_amplitude,
        "rf_differential_V_peak_to_peak": 4.0 * rf_amplitude,
        "ideal_scanline": passband,
        "scope": "L0 ideal-field contract validation only; no solver or mass-response qualification",
    }


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--mode", type=Path, default=DEFAULT_MODE)
    parser.add_argument("--check-mode", action="store_true")
    args = parser.parse_args()
    if not args.check_mode:
        parser.error("--check-mode is required")
    result = validate_mass_filter_reference(_load(args.baseline), _load(args.mode))
    print(json.dumps(result, indent=2, sort_keys=True))
    print("QUADRUPOLE_L0_REFERENCE=PASS")


if __name__ == "__main__":
    main()
