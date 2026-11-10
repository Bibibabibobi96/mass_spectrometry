"""Named mass-filter reference policy; not general RF hardware restrictions."""
from __future__ import annotations
import math
from typing import Any
from msplatform.components.rf_multipole.family_contract import from_quadrupole_contract
from msplatform.components.rf_multipole import mass_filter_theory as _theory

FIELD_MODEL_ID = "quadrupole.ideal_linear.mathieu.v1"
VOLTAGE_CONVENTION_ID = "multipole.pair_about_common_mode.zero_to_peak.v1"
COORDINATE_CONVENTION_ID = "multipole.cartesian.z_axis.v1"

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
        for screen_name in ("simion_screen", "comsol_screen"):
            screen = mode.get(screen_name, {})
            if screen.get("status") != "pending_n100_revalidation":
                raise ValueError(f"{screen_name} must remain pending until an N=100 run passes")
            if screen.get("authority_run_id") is not None:
                raise ValueError(f"{screen_name} cannot cite a pre-N=100 authority run")

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

    parameters = _theory.mathieu_parameters(
        mass_to_charge_th=float(rf["tune_mass_Th"]),
        dc_amplitude_v_per_group=dc_amplitude,
        rf_amplitude_v_zero_to_peak_per_group=rf_amplitude,
        r0_mm=r0_mm,
        frequency_hz=float(rf["frequency_Hz"]),
    )
    passband = _theory.scanline_passband(dc_amplitude / rf_amplitude)
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


def theory_masses(
    baseline: dict[str, Any], mode: dict[str, Any]
) -> dict[str, float]:
    """Return ideal passband and calibration masses for the governed mode."""
    reference = validate_mass_filter_reference(baseline, mode)
    q_tune = float(reference["q_at_tune_mass"])
    tune_mass = float(mode["rf"]["tune_mass_Th"])
    passband = reference["ideal_scanline"]
    return {
        "low_mass_Th": tune_mass * q_tune / float(passband["q_out"]),
        "high_mass_Th": tune_mass * q_tune / float(passband["q_in"]),
        "calibration_mass_Th": _theory.mass_to_charge_th(
            float(passband["q_cal"]),
            float(mode["rf"]["amplitude_V_zero_to_peak_per_group"]),
            float(mode["rf"]["effective_radius_mm"]),
            float(mode["rf"]["frequency_Hz"]),
        ),
    }
