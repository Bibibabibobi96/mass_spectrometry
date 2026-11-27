"""Validate independent accelerator component-focus evidence from common release data.

The workflow consumes the repository's solver-neutral ion-release receipt and
its canonical state table.  SIMION-coordinate projection remains deliberately
outside this component until a shared or reviewed adapter is available.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from statistics import fmean
from typing import Any

from msplatform.io.file_identity import file_sha256
from msplatform.io.scientific_csv import iter_csv_rows
from msplatform.particle_release.release import validate_materialized_release
from msplatform.components.orthogonal_accelerator.focus_theory import _exit_energy_assessment, _ideal_two_zone_contrast

from msplatform.components.orthogonal_accelerator.focus_campaign import ComponentFocusError, _finite, validate_campaign, geometry_profile_identity


def _load_campaign(path: Path, *, geometry_profile: dict[str, Any]) -> dict[str, Any]:
    """Read an explicitly supplied campaign against explicit profile content."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ComponentFocusError("component-focus campaign is unreadable") from error
    return validate_campaign(value, geometry_profile=geometry_profile)

_CSV_FIELDS = ("kind", "ion", "code", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us")
_REQUIRED = {
    "source": frozenset({"ion", "t_us", "x_mm", "y_mm", "z_mm"}),
    "exit": frozenset({"ion", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us"}),
    "focus": frozenset({"ion", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us"}),
    "terminal": frozenset({"ion", "code", "t_us", "x_mm", "y_mm", "z_mm"}),
}







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
    result = {int(row["particle_id"]): {
        **{key: _finite(row[key], f"source.{key}") for key in state_fields},
        "t_us": _finite(_finite(row["birth_time_s"], "source.birth_time_s") * 1.0e6, "source birth us"),
    } for row in rows}
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




def _events(path: Path) -> dict[int, dict[str, dict[str, float]]]:
    try:
        rows = iter_csv_rows(path, _CSV_FIELDS, exact_header=_CSV_FIELDS)
        return _collect_events(rows)
    except (OSError, ValueError) as error:
        raise ComponentFocusError(f"component-focus event CSV is unreadable or invalid: {error}") from error


def _collect_events(rows) -> dict[int, dict[str, dict[str, float]]]:
    result: dict[int, dict[str, dict[str, float]]] = {}
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


def _recorded_scalar_equal(left: float, right: float) -> bool:
    # Each %.12g scalar rounds by at most half its final significant digit.
    # Two independently rounded records can differ by one such decimal unit.
    scale = max(abs(left), abs(right))
    decimal_unit = 10.0 ** (math.floor(math.log10(scale)) - 11) if scale else 0.0
    return abs(left-right) <= max(decimal_unit, math.ulp(left), math.ulp(right))


def _validate_event_sequence(ion: int, record: dict[str, dict[str, float]], plane: float) -> None:
    # Physical order is per ID, independent of cross-particle CSV row order.
    present = [kind for kind in ("source", "exit", "focus", "terminal") if kind in record]
    for before, after in zip(present, present[1:]):
        left, right = record[before]["t_us"], record[after]["t_us"]
        if left > right and not _recorded_scalar_equal(left, right):
            raise ComponentFocusError(f"ion {ion} event order violates {before} <= {after}")
    if plane == 0.0 and "exit" in record and "focus" in record:
        for field in ("t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us"):
            if not _recorded_scalar_equal(record["exit"][field], record["focus"][field]):
                raise ComponentFocusError(f"ion {ion} same-plane exit/focus crossing differs in {field}")







def analyze(event_csv_path: Path, release_receipt_path: Path, campaign_path: Path, *, geometry_profile: dict[str, Any]) -> dict[str, Any]:
    campaign = _load_campaign(campaign_path, geometry_profile=geometry_profile)
    sources, release = _source_rows(release_receipt_path, campaign)
    events = _events(event_csv_path)
    if sorted(events) != sorted(sources):
        raise ComponentFocusError("component-focus event identities differ from the common release")
    plane = _finite(campaign["operating_point"]["focus_plane_offset_from_exit_mm"], "focus plane")
    plane_tolerance = _finite(campaign["acceptance"]["focus_plane_tolerance_mm"], "focus-plane tolerance")
    hits: dict[int, tuple[dict[str, float], dict[str, float]]] = {}
    for ion, state in sources.items():
        record = events[ion]
        if "source" not in record or "terminal" not in record:
            raise ComponentFocusError(f"ion {ion} lacks source or terminal evidence")
        for field in ("x_mm", "y_mm", "z_mm"):
            if not math.isclose(record["source"][field], state[field], rel_tol=0.0, abs_tol=1e-9):
                raise ComponentFocusError(f"ion {ion} source event differs from common release state")
        # The event writer uses %.12g; accept only its serialization rounding.
        if not math.isclose(record["source"]["t_us"], state["t_us"], rel_tol=5e-12, abs_tol=1e-12):
            raise ComponentFocusError(f"ion {ion} source event clock differs from common release birth")
        _validate_event_sequence(ion, record, plane)
        focus = record.get("focus")
        if focus is None:
            continue
        if focus["vz_mm_us"] >= 0.0:
            raise ComponentFocusError(f"ion {ion} focus crossing is not -z directed")
        if abs(focus["z_mm"] - plane) > plane_tolerance:
            raise ComponentFocusError(f"ion {ion} focus event differs from declared focus plane")
        if focus["t_us"] < record["source"]["t_us"] or focus["t_us"] > record["terminal"]["t_us"]:
            raise ComponentFocusError(f"ion {ion} focus event clock is outside its source-to-terminal interval")
        hits[ion] = (state, focus)
    total = len(sources)
    fraction = len(hits) / total
    rms_radius = math.sqrt(fmean(focus["x_mm"] ** 2 + focus["y_mm"] ** 2 for _, focus in hits.values())) if hits else None
    acceptance = campaign["acceptance"]
    warnings = ([] if fraction == 1.0 else ["transport_not_complete"])
    peak_to_peak_time_ns = ((max(focus["t_us"] for _, focus in hits.values()) - min(focus["t_us"] for _, focus in hits.values())) * 1000.0
                            if len(hits) >= 2 else None)
    if peak_to_peak_time_ns is not None and peak_to_peak_time_ns > _finite(acceptance["maximum_focus_peak_to_peak_time_ns"], "maximum focus time spread"):
        warnings.append("longitudinal_time_spread_exceeds_target")
    transport_ok = fraction == _finite(acceptance["required_transport_fraction"], "required transport")
    focus_ok = peak_to_peak_time_ns is not None and peak_to_peak_time_ns <= _finite(acceptance["maximum_focus_peak_to_peak_time_ns"], "maximum focus time spread")
    exit_energy = _exit_energy_assessment(sources, events, campaign, plane_tolerance, geometry_profile=geometry_profile)
    slow_energy_ok = bool(exit_energy["cohort"]["slow_energy_passed"])
    axial_energy_ok = bool(exit_energy["cohort"]["axial_energy_passed"])
    transverse_energy_ok = bool(exit_energy["cohort"]["transverse_energy_passed"])
    transverse_velocity_bias_ok = bool(exit_energy["cohort"]["transverse_velocity_bias_passed"])
    hard_gate_passed = transport_ok and slow_energy_ok and axial_energy_ok and transverse_energy_ok and transverse_velocity_bias_ok
    return {
        "schema_version": 2, "role": "orthogonal_accelerator_component_focus_analysis",
        "status": "candidate_complete" if hard_gate_passed else "candidate_incomplete",
        "qualification": "candidate_prototype_numeric_component_focus_only",
        "geometry_profile_id": campaign["geometry_profile_id"], "particle_count": total,
        "focus_particle_count": len(hits),
        "not_reached_focus_particle_count": total - len(hits),
        "not_reached_focus_particle_ids": sorted(set(sources) - set(hits)),
        "loss_particle_count": total - len(hits),
        "loss_particle_count_semantics": "legacy_alias_for_not_reached_focus_count_not_physical_loss",
        "release_mother_particle_count": int(release["mother_particle_count"]),
        "transport_fraction": fraction, "transport_fraction_denominator_semantics": "this_run_released_cohort",
        "focus_metrics": {"mean_t_us": fmean(focus["t_us"] for _, focus in hits.values()) if hits else None, "peak_to_peak_t_ns": peak_to_peak_time_ns, "transverse_rms_radius_mm": rms_radius,
            "clock_semantics": "instrument_clock_arrival_times",
            "propagation_duration_mean_us": fmean(focus["t_us"]-source["t_us"] for source, focus in hits.values()) if hits else None,
            "propagation_duration_peak_to_peak_ns": (max(focus["t_us"]-source["t_us"] for source, focus in hits.values())-min(focus["t_us"]-source["t_us"] for source, focus in hits.values()))*1000.0 if len(hits)>=2 else None},
        "exit_energy_assessment": exit_energy,
        "arrival_time_diagnostics": _arrival_time_diagnostics(list(hits.values())),
        "ideal_field_contrast": _ideal_two_zone_contrast(hits, campaign, geometry_profile=geometry_profile),
        "warnings": warnings, "hard_gate": {"complete_transport_passed": transport_ok, "exit_slow_energy_passed": slow_energy_ok, "exit_axial_energy_passed": axial_energy_ok, "exit_transverse_energy_passed": transverse_energy_ok, "exit_transverse_velocity_bias_passed": transverse_velocity_bias_ok},
        "time_focus_assessment": {"passed": focus_ok, "threshold_ns": _finite(acceptance["maximum_focus_peak_to_peak_time_ns"], "maximum focus time spread"), "exceedance_policy": acceptance["time_spread_exceedance"]},
        "identity": {"geometry_profile_sha256": geometry_profile_identity(geometry_profile), "campaign_sha256": file_sha256(campaign_path).lower(), "release_receipt_sha256": file_sha256(release_receipt_path).lower(), "release_state_table_sha256": release["state_table"]["sha256"], "event_csv_sha256": file_sha256(event_csv_path).lower()},
        "simion_projection": campaign["simion_projection"],
        "limitations": ["Component-only result; it does not qualify system transport, detector arrival, or mass resolution."],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", required=True, type=Path)
    parser.add_argument("--release-receipt", required=True, type=Path)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--component-contract", required=True, type=Path)
    args = parser.parse_args()
    try:
        campaign = json.loads(args.campaign.read_text(encoding="utf-8"))
        profile = json.loads(args.component_contract.read_text(encoding="utf-8"))["geometry_profiles"][campaign["geometry_profile_id"]]
        result = analyze(args.events, args.release_receipt, args.campaign, geometry_profile=profile)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"ACCELERATOR_COMPONENT_FOCUS_ANALYSIS=FAIL ERROR={error}")
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"ACCELERATOR_COMPONENT_FOCUS_ANALYSIS={'PASS' if result['status'] == 'candidate_complete' else 'INCOMPLETE'} PARTICLES={result['particle_count']} FOCUS={result['focus_particle_count']}")
    return 0 if result["status"] == "candidate_complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
