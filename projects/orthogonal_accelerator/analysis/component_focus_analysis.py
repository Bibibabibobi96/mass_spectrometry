"""Validate independent accelerator component-focus evidence from common release data.

The workflow consumes the repository's solver-neutral ion-release receipt and
its canonical state table.  SIMION-coordinate projection remains deliberately
outside this component until a shared or reviewed adapter is available.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from statistics import fmean
from typing import Any

from common.ion_release.release import validate_materialized_release, validate_release_spec
from projects.orthogonal_accelerator.simion.two_zone_candidate import _load_geometry_profile

_CSV_FIELDS = ("kind", "ion", "code", "t_us", "x_mm", "y_mm", "z_mm", "vz_mm_us")
_REQUIRED = {
    "source": frozenset({"ion", "t_us", "x_mm", "y_mm", "z_mm"}),
    "focus": frozenset({"ion", "t_us", "x_mm", "y_mm", "z_mm", "vz_mm_us"}),
    "terminal": frozenset({"ion", "code", "t_us", "x_mm", "y_mm", "z_mm"}),
}

class ComponentFocusError(ValueError):
    """Raised when component focus evidence is incomplete or inconsistent."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def _load_campaign(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ComponentFocusError("component-focus campaign is unreadable") from error
    required = {"schema_version", "role", "geometry_profile_id", "release_spec", "operating_point", "numerics", "acceptance", "simion_projection"}
    if not isinstance(value, dict) or set(value) != required or value["schema_version"] != 1 or value["role"] != "orthogonal_accelerator_component_focus_campaign":
        raise ComponentFocusError("component-focus campaign fields or identity are invalid")
    try:
        validate_release_spec(value["release_spec"])
    except ValueError as error:
        raise ComponentFocusError(f"component-focus release specification is invalid: {error}") from error
    point, numerics, acceptance, projection = (value["operating_point"], value["numerics"], value["acceptance"], value["simion_projection"])
    if not isinstance(point, dict) or set(point) != {"acceleration_direction", "focus_plane_offset_from_exit_mm", "electrode_voltages_v", "instance_center_y_mm"}:
        raise ComponentFocusError("component-focus operating point is invalid")
    if (point["acceleration_direction"] != "-z"
            or _finite(point["focus_plane_offset_from_exit_mm"], "focus plane") > 0.0
            or not math.isfinite(_finite(point["instance_center_y_mm"], "instance center y"))):
        raise ComponentFocusError("component-focus must declare an exit or downstream -z focus plane")
    voltages = point["electrode_voltages_v"]
    if not isinstance(voltages, list) or len(voltages) != 9:
        raise ComponentFocusError("component-focus must declare all nine electrode voltages")
    for voltage in voltages:
        _finite(voltage, "operating-point voltage")
    if not isinstance(numerics, dict) or set(numerics) != {"trajectory_quality", "maximum_step_us"} or min(_finite(numerics[key], f"numerics.{key}") for key in numerics) <= 0.0:
        raise ComponentFocusError("component-focus numerical settings are invalid")
    if not isinstance(acceptance, dict) or set(acceptance) != {"required_transport_fraction", "maximum_focus_peak_to_peak_time_ns", "time_spread_exceedance", "focus_plane_tolerance_mm"}:
        raise ComponentFocusError("component-focus acceptance settings are invalid")
    required_transport = _finite(acceptance["required_transport_fraction"], "required transport fraction")
    if (required_transport != 1.0
            or acceptance["time_spread_exceedance"] != "warning"
            or min(_finite(acceptance[key], key) for key in ("maximum_focus_peak_to_peak_time_ns", "focus_plane_tolerance_mm")) <= 0.0):
        raise ComponentFocusError("component-focus acceptance settings are invalid")
    if (not isinstance(projection, dict) or set(projection) != {"source_frame", "workbench_mapping", "local_pa_span_mm", "iob_origin_rule", "local_exit_z_mm", "focus_plane_padding_mm", "positive_z_enclosure_padding_mm", "semantics"}
            or projection["workbench_mapping"] != "identity_xyz_with_local_exit_z_translation_v1"
            or projection["iob_origin_rule"] != "negative_half_transverse_span__local_z_zero_v1"
            or projection["source_frame"] != value["release_spec"]["frame_id"]
            or not isinstance(projection["local_pa_span_mm"], list) or len(projection["local_pa_span_mm"]) != 3
            or min(_finite(item, "projection PA span") for item in projection["local_pa_span_mm"]) <= 0.0
            or _finite(projection["local_exit_z_mm"], "projection local exit") < 0.0
            or min(_finite(projection[key], key) for key in ("focus_plane_padding_mm", "positive_z_enclosure_padding_mm")) <= 0.0):
        raise ComponentFocusError("component-focus SIMION projection contract is invalid")
    return value


def _source_rows(receipt_path: Path, campaign: dict[str, Any]) -> tuple[dict[int, dict[str, float]], dict[str, Any]]:
    try:
        receipt = validate_materialized_release(receipt_path)
    except ValueError as error:
        raise ComponentFocusError(f"common ion-release receipt validation failed: {error}") from error
    if receipt["release_spec"] != campaign["release_spec"]:
        raise ComponentFocusError("common ion-release specification differs from the component campaign")
    table = Path(receipt["state_table"]["path"])
    with table.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    state_fields = ("x_mm", "y_mm", "z_mm", "vx_m_s", "vy_m_s", "vz_m_s")
    result = {int(row["particle_id"]): {key: _finite(row[key], f"source.{key}") for key in state_fields} for row in rows}
    count = campaign["release_spec"]["particle_count"]
    if len(rows) != count or sorted(result) != list(range(1, count + 1)):
        raise ComponentFocusError("common ion-release particle identities differ from the component campaign")
    return result, receipt


def _linear_association(values: list[float], arrivals_ns: list[float]) -> dict[str, float] | None:
    if len(values) < 2:
        return None
    mean_value, mean_arrival = fmean(values), fmean(arrivals_ns)
    value_sum_squares = sum((value - mean_value) ** 2 for value in values)
    arrival_sum_squares = sum((arrival - mean_arrival) ** 2 for arrival in arrivals_ns)
    if value_sum_squares == 0.0 or arrival_sum_squares == 0.0:
        return None
    covariance = sum((value - mean_value) * (arrival - mean_arrival) for value, arrival in zip(values, arrivals_ns, strict=True))
    slope = covariance / value_sum_squares
    correlation = covariance / math.sqrt(value_sum_squares * arrival_sum_squares)
    return {"pearson_r": correlation, "slope_ns_per_unit": slope, "r_squared": correlation ** 2}


def _arrival_time_diagnostics(hits: list[tuple[dict[str, float], dict[str, float]]]) -> dict[str, Any]:
    """Classify source-coordinate evidence without claiming a field mechanism."""
    if not hits:
        return {"status": "unavailable_no_focus_hits", "coordinate_associations": {}, "edge_field_evidence": "not_assessed", "numerical_convergence": "not_assessed"}
    arrivals_ns = [focus["t_us"] * 1000.0 for _, focus in hits]
    associations = {
        field: _linear_association([source[field] for source, _ in hits], arrivals_ns)
        for field in ("x_mm", "y_mm", "z_mm", "vx_m_s", "vy_m_s", "vz_m_s")
    }
    coordinates = {field: associations[field] for field in ("x_mm", "y_mm", "z_mm")}
    ranked = sorted(((abs(value["pearson_r"]), field) for field, value in coordinates.items() if value is not None), reverse=True)
    status = "no_single_source_coordinate_dominates"
    if ranked and ranked[0][0] >= 0.8:
        status = f"source_{ranked[0][1][0]}_dominated"
    return {
        "status": status,
        "coordinate_associations": associations,
        "edge_field_evidence": "not_determined_from_arrival_coordinate_association",
        "numerical_convergence": "not_assessed_from_one_numerics_setting",
    }


def _positive_root(distance_m: float, velocity_m_s: float, acceleration_m_s2: float) -> float:
    if distance_m <= 0.0 or acceleration_m_s2 <= 0.0:
        raise ComponentFocusError("ideal two-zone propagation requires positive distance and acceleration")
    return (math.sqrt(velocity_m_s * velocity_m_s + 2.0 * acceleration_m_s2 * distance_m) - velocity_m_s) / acceleration_m_s2


def _ideal_two_zone_contrast(sources: dict[int, dict[str, float]], campaign: dict[str, Any], native_p2p_ns: float | None) -> dict[str, Any]:
    """Compare the native PA flight with its matching piecewise-uniform two-zone field.

    The common release states and runtime voltage table are unchanged.  Uniform fields
    deliberately remove transverse finite-electrode variation; this is a diagnostic,
    not a physical qualification result.
    """
    profile = _load_geometry_profile(campaign["geometry_profile_id"])
    gap1, gap2 = float(profile["gap_1_mm"]), float(profile["gap_2_mm"])
    point = campaign["operating_point"]
    voltages = point["electrode_voltages_v"]
    repeller, grid1, exit_v = (_finite(voltages[index], "ideal voltage") for index in (1, 2, 3))
    species = campaign["release_spec"]["species"]
    mass_kg = _finite(species["mass_amu"], "ion mass") * 1.66053906660e-27
    charge_c = _finite(species["charge_state"], "ion charge state") * 1.602176634e-19
    if mass_kg <= 0.0 or charge_c <= 0.0:
        raise ComponentFocusError("ideal two-zone contrast requires positive ion mass and charge")
    a1 = charge_c * (repeller - grid1) * 1000.0 / (mass_kg * gap1)
    a2 = charge_c * (grid1 - exit_v) * 1000.0 / (mass_kg * gap2)
    arrivals_ns: list[float] = []
    for state in sources.values():
        release = gap1 + gap2 - state["z_mm"]
        if not 0.0 < release < gap1:
            raise ComponentFocusError("common release is outside the ideal first acceleration gap")
        t1 = _positive_root((gap1 - release) * 1.0e-3, -state["vz_m_s"], a1)
        v1 = -state["vz_m_s"] + a1 * t1
        t2 = _positive_root(gap2 * 1.0e-3, v1, a2)
        arrivals_ns.append((t1 + t2) * 1.0e9)
    ideal_p2p = max(arrivals_ns) - min(arrivals_ns)
    excess = None if native_p2p_ns is None else native_p2p_ns - ideal_p2p
    status = "native_finite_geometry_excess_supported" if excess is not None and excess > 0.05 else "no_material_native_finite_geometry_excess"
    return {
        "field_model": "two_zone_piecewise_uniform_ideal_field_v1",
        "same_release_and_runtime_voltages": True,
        "ideal_peak_to_peak_t_ns": ideal_p2p,
        "native_minus_ideal_peak_to_peak_t_ns": excess,
        "diagnosis": status,
        "interpretation": ("The PA result has additional timing spread beyond the matching uniform two-zone field." if status == "native_finite_geometry_excess_supported" else "The matching uniform two-zone field accounts for the observed timing spread within the diagnostic threshold."),
    }


def _events(path: Path) -> dict[int, dict[str, dict[str, float]]]:
    result: dict[int, dict[str, dict[str, float]]] = {}
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != list(_CSV_FIELDS):
                raise ComponentFocusError("component-focus event CSV header is invalid")
            rows = list(reader)
    except OSError as error:
        raise ComponentFocusError("component-focus event CSV is unreadable") from error
    for row in rows:
        if set(row) != set(_CSV_FIELDS) or any(value is None for value in row.values()):
            raise ComponentFocusError("component-focus event CSV row is invalid")
        kind = row["kind"]
        if kind not in _REQUIRED:
            raise ComponentFocusError(f"unknown component-focus event: {kind}")
        fields = {
            name: _finite(value, f"{kind} event")
            for name, value in row.items()
            if name in _REQUIRED[kind]
        }
        if len(fields) != len(_REQUIRED[kind]):
            raise ComponentFocusError(f"component-focus {kind} event is incomplete")
        ion_value = fields.pop("ion")
        if not ion_value.is_integer() or ion_value < 1:
            raise ComponentFocusError("component-focus ion must be a positive integer")
        bucket = result.setdefault(int(ion_value), {})
        if kind in bucket:
            raise ComponentFocusError(f"duplicate component-focus {kind} event for ion {int(ion_value)}")
        bucket[kind] = fields
    return result

def analyze(event_csv_path: Path, release_receipt_path: Path, campaign_path: Path) -> dict[str, Any]:
    campaign = _load_campaign(campaign_path)
    sources, release = _source_rows(release_receipt_path, campaign)
    events = _events(event_csv_path)
    if sorted(events) != sorted(sources):
        raise ComponentFocusError("component-focus event identities differ from the common release")
    plane = _finite(campaign["operating_point"]["focus_plane_offset_from_exit_mm"], "focus plane")
    plane_tolerance = _finite(campaign["acceptance"]["focus_plane_tolerance_mm"], "focus-plane tolerance")
    hits: list[tuple[dict[str, float], dict[str, float]]] = []
    for ion, state in sources.items():
        record = events[ion]
        if "source" not in record or "terminal" not in record:
            raise ComponentFocusError(f"ion {ion} lacks source or terminal evidence")
        for field in ("x_mm", "y_mm", "z_mm"):
            if not math.isclose(record["source"][field], state[field], rel_tol=0.0, abs_tol=1e-9):
                raise ComponentFocusError(f"ion {ion} source event differs from common release state")
        focus = record.get("focus")
        if focus is None:
            continue
        if focus["vz_mm_us"] >= 0.0:
            raise ComponentFocusError(f"ion {ion} focus crossing is not -z directed")
        if abs(focus["z_mm"] - plane) > plane_tolerance:
            raise ComponentFocusError(f"ion {ion} focus event differs from declared focus plane")
        hits.append((state, focus))
    total = len(sources)
    fraction = len(hits) / total
    rms_radius = math.sqrt(fmean(focus["x_mm"] ** 2 + focus["y_mm"] ** 2 for _, focus in hits)) if hits else None
    acceptance = campaign["acceptance"]
    warnings = ([] if fraction == 1.0 else ["transport_not_complete"])
    peak_to_peak_time_ns = ((max(focus["t_us"] for _, focus in hits) - min(focus["t_us"] for _, focus in hits)) * 1000.0
                            if hits else None)
    if peak_to_peak_time_ns is not None and peak_to_peak_time_ns > _finite(acceptance["maximum_focus_peak_to_peak_time_ns"], "maximum focus time spread"):
        warnings.append("longitudinal_time_spread_exceeds_target")
    transport_ok = fraction == _finite(acceptance["required_transport_fraction"], "required transport")
    focus_ok = peak_to_peak_time_ns is not None and peak_to_peak_time_ns <= _finite(acceptance["maximum_focus_peak_to_peak_time_ns"], "maximum focus time spread")
    return {
        "schema_version": 1, "role": "orthogonal_accelerator_component_focus_analysis",
        "status": "candidate_complete" if transport_ok else "candidate_incomplete",
        "qualification": "candidate_prototype_numeric_component_focus_only",
        "geometry_profile_id": campaign["geometry_profile_id"], "particle_count": total,
        "focus_particle_count": len(hits), "loss_particle_count": total - len(hits), "transport_fraction": fraction,
        "focus_metrics": {"mean_t_us": fmean(focus["t_us"] for _, focus in hits) if hits else None, "peak_to_peak_t_ns": peak_to_peak_time_ns, "transverse_rms_radius_mm": rms_radius},
        "arrival_time_diagnostics": _arrival_time_diagnostics(hits),
        "ideal_field_contrast": _ideal_two_zone_contrast(sources, campaign, peak_to_peak_time_ns),
        "warnings": warnings, "hard_gate": {"complete_transport_passed": transport_ok},
        "time_focus_assessment": {"passed": focus_ok, "threshold_ns": _finite(acceptance["maximum_focus_peak_to_peak_time_ns"], "maximum focus time spread"), "exceedance_policy": acceptance["time_spread_exceedance"]},
        "identity": {"campaign_sha256": _sha256(campaign_path), "release_receipt_sha256": _sha256(release_receipt_path), "release_state_table_sha256": release["state_table"]["sha256"], "event_csv_sha256": _sha256(event_csv_path)},
        "simion_projection": campaign["simion_projection"],
        "limitations": ["Component-only result; it does not qualify system transport, detector arrival, or mass resolution."],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", required=True, type=Path)
    parser.add_argument("--release-receipt", required=True, type=Path)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = analyze(args.events, args.release_receipt, args.campaign)
    except (OSError, ValueError) as error:
        print(f"ACCELERATOR_COMPONENT_FOCUS_ANALYSIS=FAIL ERROR={error}")
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"ACCELERATOR_COMPONENT_FOCUS_ANALYSIS={'PASS' if result['status'] == 'candidate_complete' else 'INCOMPLETE'} PARTICLES={result['particle_count']} FOCUS={result['focus_particle_count']}")
    return 0 if result["status"] == "candidate_complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
