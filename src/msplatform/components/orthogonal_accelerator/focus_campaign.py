"""Pure validation of the declared legacy closed two-zone focus campaign."""
from __future__ import annotations
import math
from typing import Any, Mapping
from msplatform.ion_release.release import validate_release_spec
from msplatform.components.orthogonal_accelerator.two_zone_geometry import validate_geometry_profile

class ComponentFocusError(ValueError):
    """Raised when component focus evidence is incomplete or inconsistent."""

def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ComponentFocusError(f"{label} must be finite")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ComponentFocusError(f"{label} must be finite") from error
    if not math.isfinite(result):
        raise ComponentFocusError(f"{label} must be finite")
    return result

def validate_campaign(value: dict[str, Any], *, geometry_profile: Mapping[str, float | int]) -> dict[str, Any]:
    required = {"schema_version", "role", "geometry_profile_id", "release_spec", "operating_point", "numerics", "acceptance", "simion_projection"}
    if not isinstance(value, dict) or set(value) != required or value["schema_version"] != 1 or value["role"] != "orthogonal_accelerator_component_focus_campaign":
        raise ComponentFocusError("component-focus campaign fields or identity are invalid")
    try:
        validate_release_spec(value["release_spec"])
    except ValueError as error:
        raise ComponentFocusError(f"component-focus release specification is invalid: {error}") from error
    point, numerics, acceptance, projection = (value["operating_point"], value["numerics"], value["acceptance"], value["simion_projection"])
    if not isinstance(point, dict) or set(point) != {"acceleration_direction", "focus_plane_offset_from_exit_mm", "electrode_voltages_v", "instance_center_y_mm", "finite_3d_gain_correction_v"}:
        raise ComponentFocusError("component-focus operating point is invalid")
    if (point["acceleration_direction"] != "-z"
            or _finite(point["focus_plane_offset_from_exit_mm"], "focus plane") > 0.0
            or not math.isfinite(_finite(point["instance_center_y_mm"], "instance center y"))
            or not math.isfinite(_finite(point["finite_3d_gain_correction_v"], "finite-3D gain correction"))):
        raise ComponentFocusError("component-focus must declare an exit or downstream -z focus plane")
    profile = validate_geometry_profile(geometry_profile)
    electrode_count = 4 + int(profile["ring_count"])
    voltages = point["electrode_voltages_v"]
    if not isinstance(voltages, list) or len(voltages) != electrode_count:
        raise ComponentFocusError(
            f"component-focus must declare all {electrode_count} profile electrodes"
        )
    for voltage in voltages:
        _finite(voltage, "operating-point voltage")
    if not isinstance(numerics, dict) or set(numerics) != {"trajectory_quality", "maximum_step_us"} or min(_finite(numerics[key], f"numerics.{key}") for key in numerics) <= 0.0:
        raise ComponentFocusError("component-focus numerical settings are invalid")
    if not isinstance(acceptance, dict) or set(acceptance) != {"required_transport_fraction", "maximum_focus_peak_to_peak_time_ns", "time_spread_exceedance", "focus_plane_tolerance_mm", "maximum_exit_slow_energy_error_per_charge_v", "maximum_exit_axial_energy_error_per_charge_v", "maximum_exit_transverse_energy_error_per_charge_v", "maximum_exit_transverse_velocity_bias_mm_per_us"}:
        raise ComponentFocusError("component-focus acceptance settings are invalid")
    required_transport = _finite(acceptance["required_transport_fraction"], "required transport fraction")
    if (required_transport != 1.0
            or acceptance["time_spread_exceedance"] != "warning"
            or min(_finite(acceptance[key], key) for key in ("maximum_focus_peak_to_peak_time_ns", "focus_plane_tolerance_mm", "maximum_exit_slow_energy_error_per_charge_v", "maximum_exit_axial_energy_error_per_charge_v", "maximum_exit_transverse_energy_error_per_charge_v", "maximum_exit_transverse_velocity_bias_mm_per_us")) <= 0.0):
        raise ComponentFocusError("component-focus acceptance settings are invalid")
    if (not isinstance(projection, dict) or set(projection) != {"source_frame", "workbench_mapping", "local_pa_span_mm", "iob_origin_rule", "local_exit_z_mm", "focus_plane_padding_mm", "positive_z_enclosure_padding_mm", "semantics"}
            or projection["workbench_mapping"] != "identity_xyz_with_local_exit_z_translation_v1"
            or projection["iob_origin_rule"] != "x_mirror_plane__negative_half_y__local_z_zero_v1"
            or projection["source_frame"] != value["release_spec"]["frame_id"]
            or not isinstance(projection["local_pa_span_mm"], list) or len(projection["local_pa_span_mm"]) != 3
            or min(_finite(item, "projection PA span") for item in projection["local_pa_span_mm"]) <= 0.0
            or _finite(projection["local_exit_z_mm"], "projection local exit") < 0.0
            or min(_finite(projection[key], key) for key in ("focus_plane_padding_mm", "positive_z_enclosure_padding_mm")) <= 0.0):
        raise ComponentFocusError("component-focus SIMION projection contract is invalid")
    return value
