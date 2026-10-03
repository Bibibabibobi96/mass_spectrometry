"""Parse MR-TOF Candidate SIMION event receipts without filtering losses."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import re
from pathlib import Path
from statistics import mean, median, pstdev
from typing import Any

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.drift_phase_contract import (
    resolve_drift_phase_contract,
)


EVENT = re.compile(r"^MRTOF_EVENT\s+(?P<kind>\w+)\s+(?P<fields>.*)$")
FIELD = re.compile(r"(?P<key>[A-Za-z_]+)=(?P<value>[^\s]+)")
FLY_COMPLETED = re.compile(r"^status,Fly completed\.\s+(?P<splats>\d+) splats", re.MULTILINE)
SOURCE_COUNT_KEYS = {
    "center_fly2": "center_particle_count",
    "candidate_bunch_fly2": "candidate_bunch_particle_count",
    "mirror_internal_diagnostic_center_fly2": "center_particle_count",
    "mirror_internal_diagnostic_bunch_fly2": "candidate_bunch_particle_count",
    "accelerator_focus_center_fly2": "center_particle_count",
    "accelerator_focus_bunch_fly2": "candidate_bunch_particle_count",
    "first_prism_entry_center_fly2": "center_particle_count",
    "full_mrtof_center_fly2": "center_particle_count",
}
SOURCE_PROFILE_IDS = {
    "mirror_internal_diagnostic_center_fly2": "mirror_internal_diagnostic",
    "mirror_internal_diagnostic_bunch_fly2": "mirror_internal_diagnostic",
    "accelerator_focus_center_fly2": "accelerator_focus_diagnostic",
    "accelerator_focus_bunch_fly2": "accelerator_focus_diagnostic",
    "first_prism_entry_center_fly2": "first_prism_entry_diagnostic",
    "full_mrtof_center_fly2": "full_mrtof_center",
}
ELEMENTARY_CHARGE_C = 1.602176634e-19
ATOMIC_MASS_KG = 1.66053906660e-27
STATIC_RETURN_KINDS = (
    "return_p2_entry", "return_p2_pass",
    "return_positive_mirror_turn", "detector",
)
REQUIRED_FIELDS = {
    "turn": {"ion", "n", "t_us", "z_mm"},
    "fast_turn": {"ion", "n", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us"},
    "slow_turn": {"ion", "n", "t_us", "x_mm", "y_mm", "z_mm"},
    "p1_plane": {"ion", "n", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us"},
    "prism_entry": {"ion", "n", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us"},
    "prism_pass": {"ion", "n", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us"},
    "pre_injection_mirror_turn": {"ion", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us"},
    "p2_low_field_reference": {"ion", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us"},
    "p2_low_field_crossing": {
        "ion", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us",
        "inside_aperture", "direction_ok",
    },
    "pre_origin_positive_mirror_turn": {"ion", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us"},
    "drift_phase_origin": {"ion", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us"},
    "drift_phase_candidate": {"ion", "k", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us"},
    "drift_phase_return": {"ion", "k", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us"},
    "drift_coordinate_return": {"ion", "k_before", "fractional_k", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us"},
    "target_k_phase_sample": {"ion", "k", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us"},
    "prism_voltage_switch": {"ion", "electrode", "t_us", "from_v", "to_v"},
    "post_return_mirror_turn": {"ion", "n", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us"},
    "return_origin_mirror_turn": {"ion", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us"},
    "return_p2_entry": {"ion", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us"},
    "return_p2_pass": {"ion", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us"},
    "return_positive_mirror_turn": {"ion", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us"},
    "nonmirror_reversal": {
        "ion", "direction_before", "direction_after", "t_us",
        "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us",
    },
    "accelerator_launch_vz_zero": {
        "ion", "direction_before", "direction_after", "t_us",
        "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us",
    },
    "return_p1_entry": {"ion", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us"},
    "return_p1_pass": {"ion", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us"},
    "slow_coordinate_y0": {"ion", "n", "direction_y", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us"},
    "central_plane": {"ion", "n", "t_us", "x_mm", "y_mm"},
    "central_plane_directional": {"ion", "n", "direction_z", "t_us", "x_mm", "y_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us"},
    "detector": {"ion", "t_us", "x_mm", "y_mm", "z_mm"},
    "detector_plane": {"ion", "direction_z", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us"},
    "instance_transition": {"ion", "t_us", "instance", "x_mm", "y_mm", "z_mm"},
    "accelerator_pulse_off": {
        "ion", "t_us", "from_instance", "to_instance", "x_mm", "y_mm", "z_mm",
    },
    "accelerator_safe_exit": {
        "ion", "t_us", "from_instance", "to_instance", "x_mm", "y_mm", "z_mm",
        "vx_mm_us", "vy_mm_us", "vz_mm_us",
    },
    "accelerator_geometric_exit": {
        "ion", "localization", "t_us", "x_mm", "y_mm", "z_mm",
        "vx_mm_us", "vy_mm_us", "vz_mm_us",
    },
    "accelerator_reentry": {
        "ion", "t_us", "instance", "x_mm", "y_mm", "z_mm",
        "vx_mm_us", "vy_mm_us", "vz_mm_us",
    },
    "accelerator_global_pulse_applied": {
        "ion", "t_us", "scheduled_t_us", "instance", "x_mm", "y_mm", "z_mm", "trigger",
    },
    "local_field_handoff": {"ion", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us", "to_instance"},
    "target_k": {"ion", "k", "t_us", "x_mm", "y_mm", "z_mm"},
    "splat": {"ion", "code", "t_us", "turns"},
    "terminal": {"ion", "splat", "t_us", "turns"},
}
LOG_REQUIRED_FIELDS = {
    **REQUIRED_FIELDS,
    "terminal": REQUIRED_FIELDS["terminal"] | {
        "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us", "central_crossings",
    },
    "splat": REQUIRED_FIELDS["splat"] | {"x_mm", "y_mm", "z_mm", "central_crossings"},
}


def _integer(value: object, *, minimum: int | None = None) -> bool:
    return (type(value) in (int, float) and math.isfinite(value)
            and int(value) == value and (minimum is None or value >= minimum))


def _half_integer(value: object, *, minimum: float | None = None) -> bool:
    return (type(value) in (int, float) and math.isfinite(value)
            and int(round(2.0 * value)) == 2.0 * value
            and (minimum is None or value >= minimum))


def _odd_half_integer(value: object, *, minimum: float | None = None) -> bool:
    return (_half_integer(value, minimum=minimum)
            and int(round(2.0 * float(value))) % 2 == 1)


def _event_error(event: dict[str, Any]) -> str | None:
    kind = event.get("kind")
    if kind not in REQUIRED_FIELDS or not REQUIRED_FIELDS[kind] <= event.keys():
        return "unknown_event_or_missing_fields"
    string_fields = {
        "name", "region", "face", "trigger", "termination_kind", "reason", "localization",
    }
    if any(type(value) not in (float, int) or not math.isfinite(value)
           for key, value in event.items()
           if key not in {"kind", *string_fields}):
        return "nonfinite_or_nonnumeric_event_field"
    for key in string_fields:
        if key in event and (not isinstance(event[key], str) or not event[key]):
            return "invalid_event_identity"
    if not _integer(event["ion"], minimum=1) or event["t_us"] < 0:
        return "invalid_particle_id_or_time"
    for key in (
        "turns", "central_crossings", "n", "half_cycles", "electrode", "to_instance",
        "inside_aperture", "direction_ok",
    ):
        if key in event and not _integer(event[key], minimum=0):
            return "invalid_event_counter"
    for key in ("inside_aperture", "direction_ok"):
        if key in event and event[key] not in (0, 1):
            return "invalid_boolean_flag"
    for key in ("k", "k_before"):
        if key in event and not _half_integer(event[key], minimum=0):
            return "invalid_event_phase_ratio"
    for key in ("instance", "from_instance", "to_instance"):
        if key in event and not _integer(event[key], minimum=0):
            return "invalid_instance_number"
    for key in ("splat", "code"):
        if key in event and not _integer(event[key]):
            return "invalid_splat_code"
    for key in ("direction", "direction_y", "direction_z", "direction_before", "direction_after"):
        if key in event and event[key] not in (-1, 1):
            return "invalid_direction_sign"
    return None


def parse_events(text: str) -> list[dict[str, Any]]:
    """Read only explicitly emitted Candidate events from a SIMION log."""
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        match = EVENT.match(line.strip())
        if not match:
            continue
        event: dict[str, Any] = {"kind": match.group("kind")}
        for token in match.group("fields").split():
            field = FIELD.fullmatch(token)
            if field is None or field.group("key") in event:
                raise ValueError(f"malformed or duplicate event field at line {line_number}")
            value = field.group("value")
            try:
                event[field.group("key")] = float(value)
            except ValueError:
                event[field.group("key")] = value
        error = _event_error(event)
        if not error and not LOG_REQUIRED_FIELDS[event["kind"]] <= event.keys():
            error = "incomplete_log_event"
        if error:
            raise ValueError(f"{error} at line {line_number}")
        events.append(event)
    return events


def peak_time_metrics(
    times_us: list[float], *, mass_th: float | None,
    analysis_contract: dict[str, Any] | None, cohort_role: str | None,
) -> dict[str, Any]:
    """Adapt the common KDE for a complete volume cohort; never filter hits."""
    result = {
        "method_id": (analysis_contract or {}).get("method_id", "legacy_histogram_unversioned"),
        "status": "unavailable_missing_analysis_contract",
        "fwhm": None, "mean": mean(times_us) if times_us else None,
        "mass_resolution_t_over_2fwhm": None, "time_equivalent_resolution": None,
        "significant_kde_modes": None,
        "analysis_contract": analysis_contract,
    }
    if analysis_contract is None:
        return result
    if analysis_contract.get("method_id") != "common_gaussian_kde_time_v1":
        raise ValueError("unsupported peak analysis method")
    from common.analysis.peak_metrics import AnalysisSettings, compute_peak_metrics

    if (analysis_contract.get("resolution_definition") != "mean_tof_us/(2*direct_fwhm_tof_us)"
            or analysis_contract.get("time_basis") != "instrument_arrival_us_from_common_zero_birth"
            or set(analysis_contract["settings"]) != set(AnalysisSettings.__dataclass_fields__)):
        raise ValueError("peak analysis requires explicit settings and supported time/resolution definitions")
    settings = AnalysisSettings(**analysis_contract["settings"])
    result["settings"] = settings.to_dict()
    if cohort_role != "formal_volume":
        result["status"] = "unavailable_controlled_or_unclassified_cohort"
        return result
    if any(not math.isfinite(value) or value <= 0 for value in times_us):
        raise ValueError("peak TOFs must be finite positive instrument arrival times")
    if mass_th is None or not math.isfinite(mass_th) or mass_th <= 0:
        raise ValueError("peak analysis requires the frozen source mass")
    if len(times_us) < 3:
        result["status"] = "unavailable_fewer_than_three_hits"
        return result
    if min(times_us) == max(times_us):
        result["status"] = "unavailable_zero_variance"
        return result
    metrics, _ = compute_peak_metrics(times_us, mass_th, settings)
    result.update(
        status="evaluated", fwhm=metrics["direct_fwhm_tof_ns"] / 1000.0,
        mean=metrics["mean_tof_us"],
        mass_resolution_t_over_2fwhm=metrics["time_equivalent_resolution"],
        time_equivalent_resolution=metrics["time_equivalent_resolution"],
        significant_kde_modes=metrics["significant_kde_modes"],
    )
    return result


def _fwhm(times_us: list[float]) -> float | None:
    if len(times_us) < 8:
        return None
    low, high = min(times_us), max(times_us)
    if not high > low:
        return 0.0
    bin_count = max(8, min(128, int(math.sqrt(len(times_us)))))
    width = (high - low) / bin_count
    counts = [0] * bin_count
    for value in times_us:
        counts[min(bin_count - 1, int((value - low) / width))] += 1
    half = max(counts) / 2.0
    occupied = [index for index, count in enumerate(counts) if count >= half]
    return width * (occupied[-1] - occupied[0] + 1) if occupied else None


def _same_direction_periods_us(events: list[dict[str, Any]]) -> list[float]:
    """Extract complete same-direction central-plane periods, retaining all values."""
    grouped: dict[tuple[int, int], list[float]] = {}
    for event in events:
        if event["kind"] == "central_plane_directional":
            grouped.setdefault((int(event["ion"]), int(event["direction_z"])), []).append(float(event["t_us"]))
    periods: list[float] = []
    for times in grouped.values():
        ordered = sorted(times)
        periods.extend(later - earlier for earlier, later in zip(ordered, ordered[1:]))
    return periods


def _drift_coordinate_return_diagnostics(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Retain the turn-phase count observed at the slow-coordinate return."""
    diagnostics: list[dict[str, Any]] = []
    for event in events:
        if event["kind"] != "drift_coordinate_return":
            continue
        diagnostics.append({
            "k_before": float(event["k_before"]),
            "fractional_k": float(event["fractional_k"]),
            "z_mm": float(event["z_mm"]),
            "derivation": "turn_phase_counter_at_slow_coordinate_crossing",
        })
    return diagnostics


def _linear_correlation(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    x_mean, y_mean = mean(xs), mean(ys)
    x_var = sum((value - x_mean) ** 2 for value in xs)
    y_var = sum((value - y_mean) ** 2 for value in ys)
    if x_var == 0.0 or y_var == 0.0:
        return None
    return sum(
        (x - x_mean) * (y - y_mean) for x, y in zip(xs, ys, strict=True)
    ) / math.sqrt(x_var * y_var)


def _kinetic_energy_ev(mass_th: float, vx: float, vy: float, vz: float) -> float:
    speed_squared_m2_s2 = (vx * vx + vy * vy + vz * vz) * 1.0e6
    return 0.5 * mass_th * ATOMIC_MASS_KG * speed_squared_m2_s2 / ELEMENTARY_CHARGE_C


def _summary(values: list[float], unit: str) -> dict[str, Any]:
    return {
        "sample_count": len(values), "unit": unit,
        "mean": mean(values) if values else None,
        "standard_deviation": pstdev(values) if len(values) >= 2 else None,
        "minimum": min(values) if values else None,
        "maximum": max(values) if values else None,
    }


def _prism_phase_space_diagnostic(
    events: list[dict[str, Any]], expected_ids: tuple[int, ...] | None,
    mass_th: float | None, charge_e: float | None = None,
    *, theoretical_transverse_energy_per_charge_v: float | None = None,
    theoretical_axial_energy_per_charge_v: float | None = None,
    theoretical_release_slow_energy_per_charge_v: float | None = None,
    transverse_energy_tolerance_per_charge_v: float | None = None,
    slow_energy_tolerance_per_charge_v: float | None = None,
    axial_energy_tolerance_per_charge_v: float | None = None,
    source_transverse_reference: dict[str, Any] | None = None,
    transverse_velocity_bias_tolerance_mm_per_us: float | None = None,
) -> dict[str, Any] | None:
    """Describe every logged Prism-section arrival without detector filtering."""
    if expected_ids is None or mass_th is None:
        return None
    reference = source_transverse_reference if isinstance(source_transverse_reference, dict) else None
    center_particle_id = reference.get("center_particle_id") if reference is not None else None
    if center_particle_id is not None and (
        type(center_particle_id) is not int or center_particle_id not in expected_ids
    ):
        raise ValueError("source center particle identity is invalid")
    terminal_codes = {
        int(event["ion"]): int(event["splat"])
        for event in events if event["kind"] == "terminal"
    }
    terminal_events = {
        int(event["ion"]): event for event in events if event["kind"] == "terminal"
    }
    by_ion: dict[int, list[dict[str, Any]]] = {}
    for event in events:
        by_ion.setdefault(int(event["ion"]), []).append(event)

    def first_main_drift_central_plane(ion: int) -> dict[str, Any] | None:
        particle = by_ion.get(ion, [])
        origins = [event for event in particle if event["kind"] == "drift_phase_origin"]
        if len(origins) != 1:
            return None
        after = [
            event for event in particle
            if event["kind"] == "central_plane_directional"
            and float(event["t_us"]) > float(origins[0]["t_us"])
        ]
        return min(after, key=lambda event: float(event["t_us"])) if after else None

    raw_low_field_available = any(
        event["kind"] == "p2_low_field_crossing" for event in events
    )
    selectors = {
        "accelerator_safe_exit": lambda event: event["kind"] == "accelerator_safe_exit",
        "p1_entry": lambda event: event["kind"] == "prism_entry" and int(event.get("n", 0)) == 1,
        "p1_exit": lambda event: event["kind"] == "prism_pass" and int(event.get("n", 0)) == 1,
        "p2_entry": lambda event: event["kind"] == "prism_entry" and int(event.get("n", 0)) == 2,
        "p2_exit": lambda event: event["kind"] == "prism_pass" and int(event.get("n", 0)) == 2,
        "p2_fixed_observation_plane": lambda event: event["kind"] == (
            "p2_low_field_crossing" if raw_low_field_available else "p2_low_field_reference"
        ),
    }
    expected = list(expected_ids)

    def terminal_histogram(ids: list[int]) -> dict[str, int]:
        codes = [terminal_codes.get(ion) for ion in ids]
        return {
            str(code): codes.count(code) for code in sorted({value for value in codes if value is not None})
        }

    def terminal_locations(ids: list[int]) -> dict[str, Any]:
        grouped: dict[int, list[dict[str, Any]]] = {}
        for ion in ids:
            event = terminal_events.get(ion)
            if event is not None:
                grouped.setdefault(int(event["splat"]), []).append(event)
        return {
            str(code): {
                "particle_count": len(group),
                "location_event_count": len(located := [
                    event for event in group if all(name in event for name in ("x_mm", "y_mm", "z_mm"))
                ]),
                "x": _summary([float(event["x_mm"]) for event in located], "mm"),
                "y": _summary([float(event["y_mm"]) for event in located], "mm"),
                "z": _summary([float(event["z_mm"]) for event in located], "mm"),
            }
            for code, group in sorted(grouped.items())
        }

    def surface(events_at_surface: list[dict[str, Any]], *, expected_direction: int) -> dict[str, Any]:
        one_by_ion: dict[int, dict[str, Any]] = {}
        duplicates: list[int] = []
        for event in events_at_surface:
            ion = int(event["ion"])
            if ion in one_by_ion:
                duplicates.append(ion)
            else:
                one_by_ion[ion] = event
        reached = sorted(one_by_ion)
        missing = [ion for ion in expected if ion not in one_by_ion]
        rows: list[dict[str, float]] = []
        energy_rows: list[dict[str, float]] = []
        undefined_angle_ids: list[int] = []
        for ion in reached:
            event = one_by_ion[ion]
            vx, vy, vz = (float(event[name]) for name in ("vx_mm_us", "vy_mm_us", "vz_mm_us"))
            if charge_e is not None and math.isfinite(charge_e) and abs(charge_e) > 0.0:
                divisor = abs(charge_e)
                energy_rows.append({
                    "ion": float(ion),
                    "Ex": _kinetic_energy_ev(mass_th, vx, 0.0, 0.0) / divisor,
                    "Ey": _kinetic_energy_ev(mass_th, 0.0, vy, 0.0) / divisor,
                    "Ez": _kinetic_energy_ev(mass_th, 0.0, 0.0, vz) / divisor,
                })
            if abs(vz) <= 1e-15:
                undefined_angle_ids.append(ion)
                continue
            rows.append({
                "ion": float(ion), "x_mm": float(event["x_mm"]), "y_mm": float(event["y_mm"]),
                "slow_angle_deg": math.degrees(math.atan2(vy, abs(vz))),
                "transverse_angle_deg": math.degrees(math.atan2(vx, abs(vz))),
                "kinetic_energy_ev": _kinetic_energy_ev(mass_th, vx, vy, vz),
                "vz_mm_us": vz,
            })
        slow = [row["slow_angle_deg"] for row in rows]
        transverse = [row["transverse_angle_deg"] for row in rows]
        energy = [row["kinetic_energy_ev"] for row in rows]
        xs = [row["x_mm"] for row in rows]
        ys = [row["y_mm"] for row in rows]
        reached_vx = [float(one_by_ion[ion]["vx_mm_us"]) for ion in reached]
        center = (
            one_by_ion.get(center_particle_id) if center_particle_id is not None else None
        )
        center_energy = (
            next(
                (row for row in energy_rows if int(row["ion"]) == center_particle_id),
                None,
            )
            if center_particle_id is not None else None
        )
        return {
            "reached_particle_count": len(reached), "reached_particle_ids": reached,
            "missing_particle_count": len(missing), "missing_particle_ids": missing,
            "duplicate_particle_ids": sorted(set(duplicates)),
            "wrong_axial_direction_particle_ids": [
                int(row["ion"]) for row in rows if row["vz_mm_us"] * expected_direction <= 0.0
            ],
            "undefined_angle_particle_ids": undefined_angle_ids,
            "outside_declared_aperture_particle_ids": [
                ion for ion, event in one_by_ion.items()
                if event.get("inside_aperture") == 0
            ],
            "failed_declared_direction_particle_ids": [
                ion for ion, event in one_by_ion.items()
                if event.get("direction_ok") == 0
            ],
            "center_state": center,
            "kinetic_energy_per_charge": {
                "status": "evaluated" if energy_rows else "pending__source_charge_unavailable",
                "semantics": "velocity_component_kinetic_energy_only__not_total_hamiltonian",
                "Ex": _summary([row["Ex"] for row in energy_rows], "V"),
                "Ey": _summary([row["Ey"] for row in energy_rows], "V"),
                "Ez": _summary([row["Ez"] for row in energy_rows], "V"),
                "center_particle_id": center_particle_id if center_energy is not None else None,
                "center": ({name: center_energy[name] for name in ("Ex", "Ey", "Ez")}
                           if center_energy is not None else None),
            },
            "slow_plane_angle": _summary(slow, "deg"),
            "transverse_plane_angle": _summary(transverse, "deg"),
            "position_x": _summary(xs, "mm"),
            "transverse_velocity": _summary(reached_vx, "mm/us"),
            "kinetic_energy": _summary(energy, "eV"),
            "correlations": {
                "y_vs_slow_angle": _linear_correlation(ys, slow),
                "x_vs_transverse_angle": _linear_correlation(xs, transverse),
                "slow_angle_vs_energy": _linear_correlation(slow, energy),
                "transverse_angle_vs_energy": _linear_correlation(transverse, energy),
            },
            "terminal_code_histogram_reached": terminal_histogram(reached),
            "terminal_code_histogram_missing": terminal_histogram(missing),
            "terminal_locations_reached": terminal_locations(reached),
            "terminal_locations_missing": terminal_locations(missing),
        }

    surface_events = {
        label: surface(
            [event for event in events if selector(event)],
            expected_direction=(
                -1 if label in {"accelerator_safe_exit", "p1_entry", "p1_exit"} else 1
            ),
        )
        for label, selector in selectors.items()
    }
    main_drift_events = [
        event for ion in expected
        if (event := first_main_drift_central_plane(ion)) is not None
    ]
    surface_events["first_main_drift_central_plane_after_positive_mirror"] = surface(
        main_drift_events, expected_direction=-1,
    )
    surface_events["p2_fixed_observation_plane"]["observation_semantics"] = (
        "raw_plane_crossing_with_aperture_and_direction_flags"
        if raw_low_field_available
        else "legacy_aperture_and_direction_filtered_reference"
    )
    p2_energy = surface_events["p2_fixed_observation_plane"]["kinetic_energy_per_charge"]
    measured_center = p2_energy["center"]
    measured_slow = measured_center["Ey"] if measured_center is not None else None
    measured_axial = measured_center["Ez"] if measured_center is not None else None
    p2_energy["fixed_observation_plane_target_diagnostic"] = {
        "status": (
            "evaluated__diagnostic_only"
            if (measured_center is not None
                and theoretical_axial_energy_per_charge_v is not None
                and theoretical_release_slow_energy_per_charge_v is not None)
            else "pending__theory_or_center_measurement_unavailable"
        ),
        "qualification": "diagnostic_only__low_field_plateau_not_formally_validated",
        "comparison_scope": (
            "center_particle_only" if center_particle_id is not None
            else "unavailable__source_has_no_declared_center"
        ),
        "energy_semantics": "component_kinetic_energy_only__must_not_be_interpreted_as_hamiltonian",
        "theoretical_target_axial_energy_per_charge_v": theoretical_axial_energy_per_charge_v,
        "theoretical_release_slow_energy_per_charge_v": theoretical_release_slow_energy_per_charge_v,
        "measured_center_axial_kinetic_energy_per_charge_v": measured_axial,
        "measured_center_slow_kinetic_energy_per_charge_v": measured_slow,
        "measured_minus_theoretical_axial_energy_per_charge_v": (
            measured_axial - theoretical_axial_energy_per_charge_v
            if measured_axial is not None and theoretical_axial_energy_per_charge_v is not None else None
        ),
        "measured_minus_theoretical_release_slow_energy_per_charge_v": (
            measured_slow - theoretical_release_slow_energy_per_charge_v
            if measured_slow is not None and theoretical_release_slow_energy_per_charge_v is not None else None
        ),
        "slow_energy_acceptance": {
            "status": "not_applicable__downstream_fields_intentionally_change_component_energies",
            "absolute_tolerance_per_charge_v": None,
            "reference_provider_tolerance_per_charge_v": slow_energy_tolerance_per_charge_v,
            "tolerance_authority": None,
            "within_tolerance": None,
        },
        "axial_energy_acceptance": {
            "status": "not_applicable__downstream_fields_intentionally_change_component_energies",
            "absolute_tolerance_per_charge_v": None,
            "reference_provider_tolerance_per_charge_v": axial_energy_tolerance_per_charge_v,
            "tolerance_authority": None,
            "within_tolerance": None,
        },
    }
    component_targets = {
        "Ex": (theoretical_transverse_energy_per_charge_v,
               transverse_energy_tolerance_per_charge_v,
               "accelerator_provider_receipt_or_explicit_contract"),
        "Ey": (theoretical_release_slow_energy_per_charge_v,
               slow_energy_tolerance_per_charge_v,
               "accelerator_provider_receipt_or_explicit_contract"),
        "Ez": (theoretical_axial_energy_per_charge_v,
               axial_energy_tolerance_per_charge_v,
               "accelerator_provider_receipt_or_explicit_request"),
    }
    for label, surface_record in surface_events.items():
        energy_record = surface_record["kinetic_energy_per_charge"]
        center_record = energy_record["center"]
        comparisons: dict[str, Any] = {}
        provider_acceptance_applies = label == "accelerator_safe_exit"
        for component, (target, tolerance, authority) in component_targets.items():
            measured = center_record[component] if center_record is not None else None
            residual = measured - target if measured is not None and target is not None else None
            comparisons[component] = {
                "status": (
                    "evaluated" if measured is not None and target is not None
                    else "pending__measured_or_theoretical_target_unavailable"
                ),
                "measured_center_kinetic_energy_per_charge_v": measured,
                "theoretical_target_energy_per_charge_v": target,
                "measured_minus_theoretical_per_charge_v": residual,
                "acceptance": {
                    "status": (
                        "evaluated__center_particle_only"
                        if provider_acceptance_applies and residual is not None and tolerance is not None
                        else f"pending__{authority}_tolerance_unavailable"
                        if provider_acceptance_applies
                        else "not_applicable__downstream_fields_intentionally_change_component_energies"
                    ),
                    "absolute_tolerance_per_charge_v": (
                        tolerance if provider_acceptance_applies else None
                    ),
                    "reference_provider_tolerance_per_charge_v": (
                        None if provider_acceptance_applies else tolerance
                    ),
                    "within_tolerance": (
                        abs(residual) <= tolerance
                        if provider_acceptance_applies and residual is not None and tolerance is not None
                        else None
                    ),
                },
            }
        energy_record["component_target_diagnostic"] = {
            "status": "diagnostic_only",
            "surface": label,
            "comparison_scope": (
                "center_particle_only" if center_particle_id is not None
                else "unavailable__source_has_no_declared_center"
            ),
            "energy_semantics": "velocity_component_kinetic_energy_only__not_total_hamiltonian",
            "components": comparisons,
        }
    safe_exit_surface = surface_events["accelerator_safe_exit"]
    center_exit = safe_exit_surface["center_state"]
    # Ex is unsigned energy and cannot supply signed steering.  Use raw
    # source-to-safe-exit position and velocity differences instead.
    exit_x_mean = safe_exit_surface["position_x"]["mean"]
    exit_vx_mean = safe_exit_surface["transverse_velocity"]["mean"]
    tolerance = transverse_velocity_bias_tolerance_mm_per_us
    center_delta_x = (
        float(center_exit["x_mm"]) - float(reference["center_x_mm"])
        if center_exit is not None and reference is not None
        and reference.get("center_x_mm") is not None else None
    )
    center_delta_vx = (
        float(center_exit["vx_mm_us"]) - float(reference["center_vx_mm_per_us"])
        if center_exit is not None and reference is not None
        and reference.get("center_vx_mm_per_us") is not None else None
    )
    mean_delta_x = (
        float(exit_x_mean) - float(reference["mean_x_mm"])
        if exit_x_mean is not None and reference is not None else None
    )
    mean_delta_vx = (
        float(exit_vx_mean) - float(reference["mean_vx_mm_per_us"])
        if exit_vx_mean is not None and reference is not None else None
    )
    complete = safe_exit_surface["reached_particle_count"] == len(expected)
    bias_evaluated = (
        complete and center_delta_vx is not None and mean_delta_vx is not None
        and tolerance is not None and math.isfinite(tolerance) and tolerance >= 0.0
    )
    safe_exit_surface["signed_transverse_bias"] = {
        "status": "evaluated" if bias_evaluated else "pending__complete_cohort_center_source_or_tolerance_unavailable",
        "comparison": "source_to_accelerator_safe_exit",
        "center_delta_x_mm": center_delta_x,
        "mean_delta_x_mm": mean_delta_x,
        "center_delta_vx_mm_per_us": center_delta_vx,
        "mean_delta_vx_mm_per_us": mean_delta_vx,
        "maximum_absolute_velocity_bias_mm_per_us": tolerance,
        "center_velocity_bias_passed": (
            abs(center_delta_vx) <= tolerance if bias_evaluated else None
        ),
        "mean_velocity_bias_passed": (
            abs(mean_delta_vx) <= tolerance if bias_evaluated else None
        ),
        "passed": (
            abs(center_delta_vx) <= tolerance and abs(mean_delta_vx) <= tolerance
            if bias_evaluated else None
        ),
    }
    p2_entry_by_ion = {
        int(event["ion"]): event for event in events if selectors["p2_entry"](event)
    }
    p2_exit_by_ion = {
        int(event["ion"]): event for event in events if selectors["p2_exit"](event)
    }
    common_p2_ids = sorted(set(p2_entry_by_ion) & set(p2_exit_by_ion))
    slow_angle_changes: list[float] = []
    transverse_angle_changes: list[float] = []
    energy_changes: list[float] = []
    for ion in common_p2_ids:
        before, after = p2_entry_by_ion[ion], p2_exit_by_ion[ion]
        before_v = [float(before[name]) for name in ("vx_mm_us", "vy_mm_us", "vz_mm_us")]
        after_v = [float(after[name]) for name in ("vx_mm_us", "vy_mm_us", "vz_mm_us")]
        if abs(before_v[2]) <= 1e-15 or abs(after_v[2]) <= 1e-15:
            continue
        slow_angle_changes.append(
            math.degrees(math.atan2(after_v[1], abs(after_v[2])))
            - math.degrees(math.atan2(before_v[1], abs(before_v[2])))
        )
        transverse_angle_changes.append(
            math.degrees(math.atan2(after_v[0], abs(after_v[2])))
            - math.degrees(math.atan2(before_v[0], abs(before_v[2])))
        )
        energy_changes.append(
            _kinetic_energy_ev(mass_th, *after_v) - _kinetic_energy_ev(mass_th, *before_v)
        )

    def paired_angle_segment(
        input_selector: Any, output_selector: Any,
    ) -> dict[str, Any]:
        input_by_ion: dict[int, dict[str, Any]] = {}
        output_by_ion: dict[int, dict[str, Any]] = {}
        for event in events:
            ion = int(event["ion"])
            if input_selector(event) and ion not in input_by_ion:
                input_by_ion[ion] = event
            if output_selector(event) and ion not in output_by_ion:
                output_by_ion[ion] = event
        common = sorted(set(input_by_ion) & set(output_by_ion))
        rows: list[dict[str, float]] = []
        undefined: list[int] = []
        for ion in common:
            before, after = input_by_ion[ion], output_by_ion[ion]
            input_v = [float(before[name]) for name in ("vx_mm_us", "vy_mm_us", "vz_mm_us")]
            output_v = [float(after[name]) for name in ("vx_mm_us", "vy_mm_us", "vz_mm_us")]
            if abs(input_v[2]) <= 1e-15 or abs(output_v[2]) <= 1e-15:
                undefined.append(ion)
                continue
            input_slow = math.degrees(math.atan2(input_v[1], abs(input_v[2])))
            output_slow = math.degrees(math.atan2(output_v[1], abs(output_v[2])))
            input_transverse = math.degrees(math.atan2(input_v[0], abs(input_v[2])))
            output_transverse = math.degrees(math.atan2(output_v[0], abs(output_v[2])))
            rows.append({
                "ion": float(ion),
                "input_slow": input_slow, "output_slow": output_slow,
                "input_transverse": input_transverse, "output_transverse": output_transverse,
            })

        def transfer(axis: str) -> dict[str, Any]:
            xs = [row[f"input_{axis}"] for row in rows]
            ys = [row[f"output_{axis}"] for row in rows]
            x_mean = mean(xs) if xs else None
            y_mean = mean(ys) if ys else None
            variance = sum((value - x_mean) ** 2 for value in xs) if x_mean is not None else 0.0
            slope = (
                sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys, strict=True)) / variance
                if variance > 0.0 and y_mean is not None else None
            )
            intercept = y_mean - slope * x_mean if slope is not None else None
            residuals = (
                [y - (intercept + slope * x) for x, y in zip(xs, ys, strict=True)]
                if intercept is not None and slope is not None else []
            )
            return {
                "input": _summary(xs, "deg"),
                "output": _summary(ys, "deg"),
                "output_minus_input": _summary(
                    [y - x for x, y in zip(xs, ys, strict=True)], "deg",
                ),
                "linear_output_vs_input": {
                    "slope": slope,
                    "intercept_deg": intercept,
                    "correlation": _linear_correlation(xs, ys),
                    "residual": _summary(residuals, "deg"),
                },
            }

        expected_set = set(expected)
        return {
            "status": "evaluated" if rows else "pending__no_common_defined_angle_particles",
            "common_particle_ids": common,
            "defined_angle_particle_ids": [int(row["ion"]) for row in rows],
            "undefined_angle_particle_ids": undefined,
            "missing_input_particle_ids": sorted(expected_set - set(input_by_ion)),
            "missing_output_particle_ids": sorted(expected_set - set(output_by_ion)),
            "slow_plane": transfer("slow"),
            "transverse_plane": transfer("transverse"),
            "spread_semantics": (
                "input_and_output_standard_deviations_are_reported_separately; "
                "standard_deviations_must_not_be_subtracted_to_attribute_added_aberration"
            ),
        }

    paired_angle_attribution = {
        "accelerator_safe_exit_to_p1_exit": {
            **paired_angle_segment(
                selectors["accelerator_safe_exit"], selectors["p1_exit"],
            ),
            "segment_semantics": (
                "combined_accelerator_exit_to_p1_exit__includes_intervening_drift_and_p1; "
                "must_not_be_interpreted_as_isolated_p1_aberration"
            ),
        },
        "accelerator_safe_exit_to_p1_entry": paired_angle_segment(
            selectors["accelerator_safe_exit"], selectors["p1_entry"],
        ),
        "p1_entry_to_p1_exit": paired_angle_segment(
            selectors["p1_entry"], selectors["p1_exit"],
        ),
        "p1_exit_to_p2_exit": {
            **paired_angle_segment(selectors["p1_exit"], selectors["p2_exit"]),
            "segment_semantics": (
                "combined_p1_exit_to_p2_exit__includes_intervening_transport_and_p2; "
                "must_not_be_interpreted_as_isolated_p2_aberration"
            ),
        },
        "p2_entry_to_p2_exit": paired_angle_segment(
            selectors["p2_entry"], selectors["p2_exit"],
        ),
    }
    return {
        "status": "descriptive__acceptance_boundary_not_assigned",
        "scope": "all_source_particles_at_each_logged_surface__not_detector_survivors",
        "surfaces": surface_events,
        "p2_entry_to_exit": {
            "common_particle_ids": common_p2_ids,
            "slow_angle_change": _summary(slow_angle_changes, "deg"),
            "transverse_angle_change": _summary(transverse_angle_changes, "deg"),
            "kinetic_energy_change": _summary(energy_changes, "eV"),
        },
        "paired_angle_attribution": paired_angle_attribution,
        "qualification": (
            "diagnostic_only__position_angle_energy_acceptance_and_field_plateau_validation_pending"
        ),
    }


def _downstream_drift_capability(
    events: list[dict[str, Any]], expected_ids: tuple[int, ...] | None,
) -> dict[str, Any] | None:
    """Summarize downstream reach from the full frozen source cohort."""
    if expected_ids is None:
        return None
    expected = list(expected_ids)
    by_ion: dict[int, list[dict[str, Any]]] = {}
    for event in events:
        by_ion.setdefault(int(event["ion"]), []).append(event)

    first_drift: dict[int, dict[str, Any]] = {}
    main_slow_turn: dict[int, tuple[dict[str, Any], dict[str, Any]]] = {}
    for ion in expected:
        particle = by_ion.get(ion, [])
        origins = [event for event in particle if event["kind"] == "drift_phase_origin"]
        if len(origins) != 1:
            continue
        origin = origins[0]
        central = [
            event for event in particle
            if event["kind"] == "central_plane_directional"
            and float(event["t_us"]) > float(origin["t_us"])
        ]
        if central:
            first_drift[ion] = min(central, key=lambda event: float(event["t_us"]))
        turns = [
            event for event in particle
            if event["kind"] == "slow_turn"
            and float(event["t_us"]) > float(origin["t_us"])
        ]
        if turns:
            main_slow_turn[ion] = (origin, min(turns, key=lambda event: float(event["t_us"])))

    expected_set = set(expected)
    target_k_ids = sorted({
        int(event["ion"]) for event in events
        if event["kind"] == "target_k" and int(event["ion"]) in expected_set
    })
    reached_ids = sorted(first_drift)
    missing_ids = [ion for ion in expected if ion not in first_drift]
    terminal_by_ion = {
        int(event["ion"]): event for event in events if event["kind"] == "terminal"
    }
    missing_terminals = [terminal_by_ion[ion] for ion in missing_ids if ion in terminal_by_ion]
    turn_rows = [
        {
            "ion": ion,
            "origin_y_mm": float(origin["y_mm"]),
            "slow_turn_y_mm": float(turn["y_mm"]),
            "drift_length_mm": abs(float(turn["y_mm"]) - float(origin["y_mm"])),
        }
        for ion, (origin, turn) in sorted(main_slow_turn.items())
    ]
    population = len(expected)
    return {
        "scope": "all_source_particles__not_detector_survivors",
        "first_main_drift": {
            "reached_particle_count": len(reached_ids),
            "reached_particle_ids": reached_ids,
            "arrival_fraction": len(reached_ids) / population,
            "missing_particle_count": len(missing_ids),
            "missing_particle_ids": missing_ids,
        },
        "target_k": {
            "reached_particle_count": len(target_k_ids),
            "reached_particle_ids": target_k_ids,
            "fraction": len(target_k_ids) / population,
        },
        "main_slow_turn": {
            "reached_particle_count": len(turn_rows),
            "particle_rows": turn_rows,
            "position_y": _summary([row["slow_turn_y_mm"] for row in turn_rows], "mm"),
            "drift_length": _summary([row["drift_length_mm"] for row in turn_rows], "mm"),
        },
        "missing_first_main_drift_terminal_attribution": {
            "terminal_code_histogram": {
                str(code): sum(int(event["splat"]) == code for event in missing_terminals)
                for code in sorted({int(event["splat"]) for event in missing_terminals})
            },
            "located_particle_count": sum(
                all(name in event for name in ("x_mm", "y_mm", "z_mm"))
                for event in missing_terminals
            ),
            "particle_rows": [
                {name: event[name] for name in ("ion", "splat", "x_mm", "y_mm", "z_mm") if name in event}
                for event in missing_terminals
            ],
        },
    }


def _mirrored_branch_turn_diagnostics(
    events: list[dict[str, Any]], target_k: float,
) -> list[dict[str, Any]]:
    """Pair internal turns between opposite-turn endpoints across slow return.

    For the declared non-retracing branch, paired states at the same slow
    coordinate satisfy ``z_return=-z_outbound``.  The diagnostic deliberately
    reports residuals without inventing a numerical acceptance tolerance.
    """
    events_by_ion: dict[int, list[dict[str, Any]]] = {}
    for event in events:
        events_by_ion.setdefault(int(event["ion"]), []).append(event)
    diagnostics: list[dict[str, Any]] = []
    for ion in sorted(events_by_ion):
        particle = events_by_ion[ion]
        origins = [event for event in particle if event["kind"] == "drift_phase_origin"]
        returns = [
            event for event in particle
            if event["kind"] == "drift_phase_return" and float(event["k"]) == target_k
        ]
        if len(origins) != 1 or len(returns) != 1:
            diagnostics.append({
                "ion": ion,
                "status": "not_evaluated__exact_target_k_phase_return_required",
                "expected_internal_turn_count": int(2 * target_k) - 1,
            })
            continue
        start, end = float(origins[0]["t_us"]), float(returns[0]["t_us"])
        turns = sorted(
            (
                event for event in particle
                if event["kind"] == "fast_turn" and start < float(event["t_us"]) < end
            ),
            key=lambda event: float(event["t_us"]),
        )
        expected = int(2 * target_k) - 1
        if len(turns) != expected:
            diagnostics.append({
                "ion": ion,
                "status": "not_evaluated__main_drift_turn_count_mismatch",
                "expected_internal_turn_count": expected,
                "observed_internal_turn_count": len(turns),
            })
            continue
        paired_count = expected // 2
        pairs = list(zip(turns[:paired_count], reversed(turns[paired_count:])))

        def residuals(field: str, sign: int) -> list[float]:
            return [float(outbound[field]) + sign * float(returned[field])
                    for outbound, returned in pairs]

        components = {
            "x_same_residual_mm": residuals("x_mm", -1),
            "y_same_residual_mm": residuals("y_mm", -1),
            "z_reflection_residual_mm": residuals("z_mm", 1),
            "vx_reversal_residual_mm_us": residuals("vx_mm_us", 1),
            "vy_reversal_residual_mm_us": residuals("vy_mm_us", 1),
        }
        diagnostics.append({
            "ion": ion,
            "status": "evaluated__tolerance_not_assigned",
            "expected_internal_turn_count": expected,
            "observed_internal_turn_count": len(turns),
            "paired_turn_count": len(pairs),
            "opposite_mirror_side_pair_count": sum(
                float(outbound["z_mm"]) * float(returned["z_mm"]) < 0.0
                for outbound, returned in pairs
            ),
            "maximum_absolute_residuals": {
                name: max(abs(value) for value in values)
                for name, values in components.items()
            },
            "rms_residuals": {
                name: math.sqrt(sum(value * value for value in values) / len(values))
                for name, values in components.items()
            },
            "qualification": "diagnostic_only__mesh_and_step_convergence_tolerance_required",
        })
    return diagnostics


def _effective_axial_width_mm(period_us: float, kinetic_energy_ev: float, mass_th: float) -> float:
    r"""Apply $W=T_0\sqrt{E/(2m)}$ to one full same-direction period."""
    if not all(math.isfinite(value) and value > 0.0 for value in (period_us, kinetic_energy_ev, mass_th)):
        raise ValueError("period, kinetic energy, and mass must be finite positive values")
    return period_us * 1.0e-6 * math.sqrt(
        kinetic_energy_ev * ELEMENTARY_CHARGE_C / (2.0 * mass_th * ATOMIC_MASS_KG)
    ) * 1.0e3


def _polygon_membership(point: tuple[float, float], polygon: list[list[float]]) -> tuple[bool, float]:
    y, z = point
    inside = False
    distance = math.inf
    for start, end in zip(polygon, polygon[1:] + polygon[:1]):
        y0, z0 = float(start[0]), float(start[1])
        y1, z1 = float(end[0]), float(end[1])
        dy, dz = y1 - y0, z1 - z0
        scale = dy * dy + dz * dz
        along = 0.0 if scale == 0.0 else max(0.0, min(1.0, ((y - y0) * dy + (z - z0) * dz) / scale))
        distance = min(distance, math.hypot(y - (y0 + along * dy), z - (z0 + along * dz)))
        if (z0 > z) != (z1 > z):
            crossing_y = y0 + (z - z0) * dy / dz
            if y < crossing_y:
                inside = not inside
    return inside, distance


def _polygon_contains(point: tuple[float, float], polygon: list[list[float]], tolerance: float) -> bool:
    """Return whether a y-z point is inside or within tolerance of a polygon."""
    inside, distance = _polygon_membership(point, polygon)
    return inside or distance <= tolerance


def _strict_polygon_hole(point: tuple[float, float], polygon: list[list[float]], tolerance: float) -> bool:
    inside, distance = _polygon_membership(point, polygon)
    return inside and distance > tolerance


def _box_contains(point: tuple[float, float, float], box: list[float], tolerance: float) -> bool:
    return all(
        float(box[index]) - tolerance <= point[index] <= float(box[index + 3]) + tolerance
        for index in range(3)
    )


def _strict_box_hole(point: tuple[float, float, float], box: list[float], tolerance: float) -> bool:
    return all(
        float(box[index]) + tolerance < point[index] < float(box[index + 3]) - tolerance
        for index in range(3)
    )


def _extruded_polygon_contains(
    point: tuple[float, float, float], x_range: list[float], polygon: list[list[float]], tolerance: float,
) -> bool:
    return (
        float(x_range[0]) - tolerance <= point[0] <= float(x_range[1]) + tolerance
        and _polygon_contains((point[1], point[2]), polygon, tolerance)
    )


def _last_completed_stage(events: list[dict[str, Any]], terminal: dict[str, Any]) -> str | None:
    stage_names = {
        "accelerator_safe_exit": "accelerator_safe_exit",
        "target_k": "target_k",
        "return_p2_entry": "return_p2_entry",
        "return_p2_pass": "return_p2_pass",
        "return_positive_mirror_turn": "return_positive_mirror_turn",
        "detector": "detector",
    }
    candidates: list[tuple[float, str]] = []
    for event in events:
        if float(event["t_us"]) > float(terminal["t_us"]):
            continue
        name = stage_names.get(str(event["kind"]))
        if event["kind"] == "prism_pass" and int(event.get("n", 0)) in (1, 2):
            name = f"p{int(event['n'])}_pass"
        if name is not None:
            candidates.append((float(event["t_us"]), name))
    return max(candidates)[1] if candidates else None


def collision_diagnostics(
    events: list[dict[str, Any]], collision_geometry: dict[str, Any] | None,
) -> dict[str, Any]:
    """Name electrode collisions from terminal coordinates and frozen resolved solids."""
    empty = {
        "collision_component_histogram": {}, "electrode_id_histogram": {},
        "collision_particles": [], "dominant_collision_component": None,
    }
    if not isinstance(collision_geometry, dict):
        return empty
    mesh = float(collision_geometry.get("mesh_mm_per_gu", 0.25))
    tolerance = mesh + 1.0e-9
    solids: list[dict[str, Any]] = []

    def add_box(component: str, electrode_id: int, box: list[float], holes: list[list[float]] | None = None) -> None:
        solids.append({"component": component, "electrode_id": electrode_id, "box": box,
                       "box_holes": [] if holes is None else holes})

    def add_polygon(component: str, electrode_id: int, x_range: list[float], polygon: list[list[float]],
                    box_holes: list[list[float]] | None = None, polygon_holes: list[list[list[float]]] | None = None) -> None:
        solids.append({"component": component, "electrode_id": electrode_id, "x": x_range,
                       "polygon": polygon, "box_holes": [] if box_holes is None else box_holes,
                       "polygon_holes": [] if polygon_holes is None else polygon_holes})

    for shield in collision_geometry.get("prism_ground_shields", []):
        component = ("p2_central_prism_ground_shield" if int(shield["id"]) == 20
                     else "p1_accelerator_exit_ground_shield")
        for section in shield["body_sections"]:
            add_polygon(component, int(shield["id"]), section["x"], section["polygon_yz_mm"],
                        shield.get("rectangular_slots_mm", []), [shield["prism_clearance_polygon_yz_mm"]])
    for body in collision_geometry.get("central_ground_electrodes", []):
        add_polygon("central_ion_foil_2_ground", 15, body["x"], body["polygon_yz_mm"],
                    collision_geometry.get("central_ground_slots", []))
    for stripe in collision_geometry.get("stripe_electrodes", []):
        electrode_id = int(stripe["id"])
        component = "stripe_set_1" if electrode_id in (11, 12) else "stripe_set_2"
        for key in ("polygon_yz_mm", "terminal_polygon_yz_mm"):
            add_polygon(component, electrode_id, stripe["x"], stripe[key], [collision_geometry["stripe_slot"]])
    for shield in collision_geometry.get("mirror_ground_shields", []):
        add_box("mirror_inner_ground_shields", 15, shield["box"], [collision_geometry["mirror_inner_shield_slot"]])
    for mirror in collision_geometry.get("mirror_electrodes", []):
        add_box("mirror_electrodes", int(mirror["id"]), mirror["box"], [collision_geometry["mirror_slot"]])
    for closure in collision_geometry.get("mirror_e_closures", []):
        add_box("mirror_outer_e_closures", int(closure["id"]), closure["box"])
    for prism in collision_geometry.get("prism_electrodes", []):
        for part in prism["parts"]:
            add_polygon(f"p{int(prism['id']) - 15}_prism_electrode", int(prism["id"]),
                        part["x"], part["polygon_yz_mm"])

    by_ion: dict[int, list[dict[str, Any]]] = {}
    for event in events:
        by_ion.setdefault(int(event["ion"]), []).append(event)
    particles = []
    for terminal in events:
        if terminal["kind"] != "terminal" or int(terminal["splat"]) != -1:
            continue
        point = (float(terminal["x_mm"]), float(terminal["y_mm"]), float(terminal["z_mm"]))
        matches = []
        for solid in solids:
            occupied = (_box_contains(point, solid["box"], tolerance) if "box" in solid else
                        _extruded_polygon_contains(point, solid["x"], solid["polygon"], tolerance))
            if not occupied or any(_strict_box_hole(point, hole, tolerance) for hole in solid["box_holes"]):
                continue
            if any(
                float(solid["x"][0]) + tolerance < point[0] < float(solid["x"][1]) - tolerance
                and _strict_polygon_hole((point[1], point[2]), hole, tolerance)
                   for hole in solid.get("polygon_holes", [])):
                continue
            matches.append(solid)
        identities = sorted({(item["component"], int(item["electrode_id"])) for item in matches})
        match = matches[0] if len(identities) == 1 else None
        particles.append({
            "ion": int(terminal["ion"]),
            "component": match["component"] if match else "unclassified",
            "electrode_id": match["electrode_id"] if match else None,
            "candidate_components": [
                {"component": component, "electrode_id": electrode_id}
                for component, electrode_id in sorted({
                    (item["component"], int(item["electrode_id"])) for item in matches
                })
            ],
            "x_mm": point[0], "y_mm": point[1], "z_mm": point[2],
            "last_completed_stage": _last_completed_stage(by_ion[int(terminal["ion"])], terminal),
        })
    component_counts = Counter(item["component"] for item in particles)
    electrode_counts = Counter(str(item["electrode_id"]) for item in particles if item["electrode_id"] is not None)
    dominant = component_counts.most_common(1)[0][0] if component_counts else None
    return {
        "collision_component_histogram": dict(sorted(component_counts.items())),
        "electrode_id_histogram": dict(sorted(electrode_counts.items(), key=lambda item: int(item[0]))),
        "collision_particles": sorted(particles, key=lambda item: item["ion"]),
        "dominant_collision_component": dominant,
    }


def summarize_events(
    events: list[dict[str, Any]], target_k: float, reported_splat_count: int | None = None,
    *, expected_particle_ids: tuple[int, ...] | None = None,
    completion_count: int | None = None,
    kinetic_energy_ev: float | None = None,
    mass_th: float | None = None,
    charge_e: float | None = None,
    theoretical_axial_energy_per_charge_v: float | None = None,
    theoretical_release_slow_energy_per_charge_v: float | None = None,
    theoretical_transverse_energy_per_charge_v: float | None = None,
    transverse_energy_tolerance_per_charge_v: float | None = None,
    slow_energy_tolerance_per_charge_v: float | None = None,
    axial_energy_tolerance_per_charge_v: float | None = None,
    source_transverse_reference: dict[str, Any] | None = None,
    transverse_velocity_bias_tolerance_mm_per_us: float | None = None,
    collision_geometry: dict[str, Any] | None = None,
    volume_particle_id_min: int | None = None,
    peak_analysis_contract: dict[str, Any] | None = None,
    cohort_role: str | None = None,
) -> dict[str, Any]:
    """Validate exact source identities; absent source/completion is diagnostic only.

    Raw observed counts and times remain visible on failure. Derived rates and
    peak statistics are published only after the complete cohort is accounted
    for. A splat plus terminal for one ion is one lifecycle, not two particles.
    """
    if not _odd_half_integer(target_k, minimum=0.5):
        raise ValueError("opposite-mirror target_k must be a positive odd half-integer")
    if expected_particle_ids is not None and (
        not expected_particle_ids
        or any(type(value) is not int or value <= 0 for value in expected_particle_ids)
        or len(set(expected_particle_ids)) != len(expected_particle_ids)
    ):
        raise ValueError("expected_particle_ids must be unique positive integer identities")
    if volume_particle_id_min is not None and (
        type(volume_particle_id_min) is not int or volume_particle_id_min <= 0
    ):
        raise ValueError("volume_particle_id_min must be a positive integer")
    errors: list[str] = []
    if any(_event_error(event) for event in events):
        raise ValueError("invalid event payload; refusing to infer missing event fields")
    completed = completion_count if completion_count is not None else int(reported_splat_count is not None)
    if completed != 1 or not _integer(reported_splat_count, minimum=0):
        errors.append("missing_or_multiple_fly_completion")
    if expected_particle_ids is None:
        errors.append("missing_frozen_particle_source")
    if any(event["kind"] == "prism_voltage_switch" for event in events):
        errors.append("prism_voltage_switch_forbidden")
    if any(event["kind"] in {"return_p1_entry", "return_p1_pass"} for event in events):
        errors.append("return_p1_forbidden__p1_is_injection_only")
    if any(event["kind"] == "nonmirror_reversal" for event in events):
        errors.append("nonmirror_vz_reversal_observed")
    expected = set(expected_particle_ids or ())
    events_by_ion: dict[int, list[dict[str, Any]]] = {}
    events_by_ion_kind: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for event in events:
        ion = int(event["ion"])
        events_by_ion.setdefault(ion, []).append(event)
        events_by_ion_kind.setdefault((ion, str(event["kind"])), []).append(event)
    observed = {int(event["ion"]) for event in events}
    unknown = sorted(observed - expected) if expected_particle_ids is not None else []
    if unknown:
        errors.append("unknown_particle_ids")
    terminal = [event for event in events if event["kind"] == "terminal"]
    splat_events = [event for event in events if event["kind"] == "splat"]
    duplicates = {}
    for kind in ("terminal", "splat", "detector", "target_k", "target_k_phase_sample"):
        counts = Counter(int(event["ion"]) for event in events if event["kind"] == kind)
        duplicates[kind] = sorted(ion for ion, count in counts.items() if count > 1)
    if any(duplicates.values()):
        errors.append("duplicate_particle_events")
    terminal_ions = {int(event["ion"]) for event in terminal}
    fallback_splats = [
        event for event in splat_events
        if int(event["ion"]) not in terminal_ions
    ]
    lifecycle = terminal + fallback_splats
    lifecycle_ids = {int(event["ion"]) for event in lifecycle}
    if _integer(reported_splat_count, minimum=0) and len(lifecycle_ids) != reported_splat_count:
        errors.append("lifecycle_count_differs_from_fly_splats")
    missing = sorted(expected - lifecycle_ids)
    if missing:
        errors.append("missing_particle_terminal_events")
    population_count = len(expected) if expected_particle_ids is not None else None
    if population_count is not None and reported_splat_count != population_count:
        errors.append("fly_splat_count_differs_from_source")
    by_terminal = {int(event["ion"]): event for event in terminal}
    for event in splat_events:
        final = by_terminal.get(int(event["ion"]))
        if final is not None and event["code"] != final["splat"]:
            errors.append("splat_terminal_reason_conflict")
    if any(event["kind"] in ("detector", "target_k")
           and int(event["ion"]) not in lifecycle_ids for event in events):
        errors.append("arrival_without_terminal_event")
    detector = [event for event in events if event["kind"] == "detector"]
    target_k_events = [event for event in events if event["kind"] == "target_k"]
    target_k_phase_samples = [
        event for event in events if event["kind"] == "target_k_phase_sample"
    ]
    if any(event["k"] != target_k for event in target_k_events):
        errors.append("target_k_event_differs_from_source_contract")
    if any(event["k"] != target_k for event in target_k_phase_samples):
        errors.append("target_k_phase_sample_differs_from_source_contract")
    for detector_event in detector:
        ion = int(detector_event["ion"])
        particle_events = events_by_ion.get(ion, [])
        chain = {
            kind: events_by_ion_kind.get((ion, kind), [])
            for kind in STATIC_RETURN_KINDS
        }
        valid_chain = all(len(chain[kind]) == 1 for kind in STATIC_RETURN_KINDS)
        if valid_chain:
            times = [float(chain[kind][0]["t_us"]) for kind in STATIC_RETURN_KINDS]
            valid_chain = all(later > earlier for earlier, later in zip(times, times[1:]))
            phase_origins = [event for event in particle_events if event["kind"] == "drift_phase_origin"]
            phase_returns = [event for event in particle_events if event["kind"] == "drift_phase_return"]
            outbound_prisms = {
                int(event["n"]): event for event in particle_events
                if event["kind"] == "prism_pass" and int(event["n"]) in (1, 2)
            }
            valid_chain = valid_chain and len(phase_origins) == 1 and len(phase_returns) == 1
            if valid_chain:
                origin, returned = phase_origins[0], phase_returns[0]
                valid_chain = (
                    float(origin["z_mm"]) > 0.0
                    and float(returned["z_mm"]) < 0.0
                    and float(origin["vy_mm_us"]) > 0.0
                    and float(returned["vy_mm_us"]) < 0.0
                    and abs(float(origin["vz_mm_us"])) <= 1.0e-12
                    and abs(float(returned["vz_mm_us"])) <= 1.0e-12
                    and float(returned["k"]) == target_k
                    and set(outbound_prisms) == {1, 2}
                    and float(outbound_prisms[1]["vz_mm_us"]) < 0.0
                    and float(outbound_prisms[2]["vz_mm_us"]) > 0.0
                    and float(chain["return_p2_entry"][0]["vz_mm_us"]) > 0.0
                    and float(chain["return_p2_pass"][0]["vz_mm_us"]) > 0.0
                    and float(chain["return_positive_mirror_turn"][0]["z_mm"]) > 0.0
                    and abs(float(chain["return_positive_mirror_turn"][0]["vz_mm_us"])) <= 1.0e-12
                )
            valid_chain = valid_chain and int(detector_event.get("direction_z", 0)) == -1
            valid_chain = valid_chain and float(detector_event.get("z_mm", 0.0)) > 0.0
            valid_chain = valid_chain and not any(
                event["kind"] == "accelerator_reentry" for event in particle_events
            )
            safe_exits = [event for event in particle_events if event["kind"] == "accelerator_safe_exit"]
            if len(safe_exits) == 1:
                safe_exit = safe_exits[0]
                accelerator_instance = int(safe_exit["from_instance"])
                valid_chain = valid_chain and not any(
                    event["kind"] == "instance_transition"
                    and float(event["t_us"]) > float(safe_exit["t_us"])
                    and int(event["instance"]) == accelerator_instance
                    for event in particle_events
                )
            final = by_terminal.get(ion)
            valid_chain = valid_chain and final is not None and int(final["splat"]) == 1
            valid_chain = valid_chain and not any(
                event["kind"] == "post_return_mirror_turn"
                or (event["kind"] == "drift_phase_candidate" and float(event["k"]) > target_k)
                for event in particle_events
            )
        if not valid_chain:
            errors.append("invalid_static_detector_event_chain")
    mirrored_branch_diagnostics = _mirrored_branch_turn_diagnostics(events, target_k)
    mirrored_by_ion = {int(item["ion"]): item for item in mirrored_branch_diagnostics}
    for detector_event in detector:
        diagnostic = mirrored_by_ion.get(int(detector_event["ion"]))
        if (
            diagnostic is None
            or diagnostic.get("status") != "evaluated__tolerance_not_assigned"
            or diagnostic.get("paired_turn_count") != int(target_k)
            or diagnostic.get("opposite_mirror_side_pair_count") != int(target_k)
        ):
            errors.append("mirrored_nonretracing_branch_turn_evidence_incomplete")
    turns = [int(event["turns"]) for event in lifecycle]
    splat_codes = [int(event["splat"] if event["kind"] == "terminal" else event["code"]) for event in lifecycle]
    valid = not errors
    oscillations = [value // 2 for value in turns]
    detected_times = [float(event["t_us"]) for event in detector]
    target_k_times = [float(event["t_us"]) for event in target_k_events]
    directional_periods = _same_direction_periods_us(events)
    slow_turn_y_mm = [float(event["y_mm"]) for event in events if event["kind"] == "slow_turn"]
    widths = (
        [_effective_axial_width_mm(period, kinetic_energy_ev, mass_th) for period in directional_periods]
        if kinetic_energy_ev is not None and mass_th is not None else []
    )
    peak = peak_time_metrics(
        detected_times if valid else [], mass_th=mass_th,
        analysis_contract=peak_analysis_contract, cohort_role=cohort_role,
    )
    fwhm = peak["fwhm"]
    target_k_fwhm = _fwhm(target_k_times) if valid else None
    center_time = median(detected_times) if valid and detected_times else None
    target_k_center_time = median(target_k_times) if valid and target_k_times else None
    resolution = peak["time_equivalent_resolution"]
    volume_expected_ids = [
        ion for ion in (expected_particle_ids or ())
        if volume_particle_id_min is not None and ion >= volume_particle_id_min
    ]
    volume_detector_times = [
        float(event["t_us"]) for event in detector
        if int(event["ion"]) in set(volume_expected_ids)
    ]
    volume_peak = peak if volume_detector_times == detected_times else peak_time_metrics(
        volume_detector_times if valid else [], mass_th=mass_th,
        analysis_contract=peak_analysis_contract, cohort_role=cohort_role,
    )
    volume_fwhm = volume_peak["fwhm"]
    volume_center_time = (
        median(volume_detector_times) if valid and volume_detector_times else None
    )
    volume_resolution = volume_peak["time_equivalent_resolution"]
    volume_only = (
        {
            "status": "supplemental_not_formal_replacement",
            "particle_id_min": volume_particle_id_min,
            "expected_particle_count": len(volume_expected_ids),
            "detector_hit_count": len(volume_detector_times),
            "detection_rate": (
                len(volume_detector_times) / len(volume_expected_ids) if valid else None
            ),
            "detector_tof_us": volume_detector_times,
            "detector_tof_fwhm_us": volume_fwhm,
            "detector_tof_median_us": volume_center_time,
            "mass_resolution_t_over_2fwhm": volume_resolution,
        }
        if volume_expected_ids else {
            "status": "unavailable_no_volume_particles_in_cohort",
            "particle_id_min": volume_particle_id_min,
            "expected_particle_count": 0,
            "detector_hit_count": 0,
            "detection_rate": None,
            "detector_tof_fwhm_us": None,
            "detector_tof_median_us": None,
            "mass_resolution_t_over_2fwhm": None,
        }
    ) if volume_particle_id_min is not None else None
    return {
        "schema_version": 3,
        "status": "candidate_not_formal" if valid else "candidate_not_formal__invalid_event_receipt",
        "event_integrity_passed": valid,
        "integrity_errors": sorted(set(errors)),
        "expected_particle_count": population_count,
        "expected_particle_ids": list(expected_particle_ids) if expected_particle_ids is not None else None,
        "observed_particle_ids": sorted(observed),
        "missing_terminal_particle_ids": missing,
        "unknown_particle_ids": unknown,
        "duplicate_event_particle_ids": duplicates,
        "fly_completion_count": completed,
        "particle_terminal_count": len(lifecycle),
        "unique_particle_terminal_count": len(lifecycle_ids),
        "terminal_event_count": len(terminal),
        "splat_fallback_event_count": len(fallback_splats),
        "flight_reported_splat_count": reported_splat_count,
        "unrecorded_splat_count": (len(missing) if population_count is not None
                                   else max(0, reported_splat_count - len(lifecycle_ids))
                                   if _integer(reported_splat_count, minimum=0) else None),
        "splat_code_histogram": {
            str(value): splat_codes.count(value) for value in sorted(set(splat_codes))
        },
        "splat_code_missing_count": 0,
        "electrode_collision_count": sum(value == -1 for value in splat_codes),
        **collision_diagnostics(events, collision_geometry),
        "full_path_timeout_count": sum(value == 2 for value in splat_codes),
        "detector_hit_count": len(detector),
        "detection_rate": len(detector) / population_count if valid else None,
        "target_k": target_k,
        "target_k_reached_event_count": len(target_k_events),
        "target_k_phase_sample_count": len(target_k_phase_samples),
        "target_k_phase_y_residuals_mm": [
            float(event["y_mm"]) for event in target_k_phase_samples
        ],
        "target_k_count": len(target_k_events),
        "target_k_fraction": (
            len(target_k_events) / population_count
            if valid
            else None
        ),
        "overtone_histogram": {
            str(value): oscillations.count(value) for value in sorted(set(oscillations))
        },
        "central_plane_crossing_count": sum(
            event["kind"] == "central_plane" for event in events
        ),
        "fast_z_turn_count": sum(event["kind"] == "fast_turn" for event in events),
        "slow_y_turn_count": sum(event["kind"] == "slow_turn" for event in events),
        "slow_y_turning_positions_mm": slow_turn_y_mm,
        "slow_drift_abs_lengths_from_y0_mm": [abs(value) for value in slow_turn_y_mm],
        "slow_coordinate_y0_crossing_count": sum(event["kind"] == "slow_coordinate_y0" for event in events),
        "slow_coordinate_y0_inbound_crossing_count": sum(
            event["kind"] == "slow_coordinate_y0" and event["direction_y"] < 0 for event in events
        ),
        "slow_coordinate_y0_outbound_crossing_count": sum(
            event["kind"] == "slow_coordinate_y0" and event["direction_y"] > 0 for event in events
        ),
        "P1_plane_crossing_count": sum(event["kind"] == "p1_plane" for event in events),
        "P2_low_field_reference_crossing_count": sum(
            event["kind"] == "p2_low_field_reference" for event in events
        ),
        "P2_low_field_raw_crossing_count": sum(
            event["kind"] == "p2_low_field_crossing" for event in events
        ),
        "prism_phase_space_diagnostic": _prism_phase_space_diagnostic(
            events, expected_particle_ids, mass_th, charge_e,
            theoretical_transverse_energy_per_charge_v=(
                theoretical_transverse_energy_per_charge_v
            ),
            theoretical_axial_energy_per_charge_v=theoretical_axial_energy_per_charge_v,
            theoretical_release_slow_energy_per_charge_v=(
                theoretical_release_slow_energy_per_charge_v
            ),
            slow_energy_tolerance_per_charge_v=slow_energy_tolerance_per_charge_v,
            transverse_energy_tolerance_per_charge_v=(
                transverse_energy_tolerance_per_charge_v
            ),
            axial_energy_tolerance_per_charge_v=axial_energy_tolerance_per_charge_v,
            source_transverse_reference=source_transverse_reference,
            transverse_velocity_bias_tolerance_mm_per_us=(
                transverse_velocity_bias_tolerance_mm_per_us
            ),
        ),
        "downstream_drift_capability": _downstream_drift_capability(
            events, expected_particle_ids,
        ),
        "drift_phase_origin_count": sum(event["kind"] == "drift_phase_origin" for event in events),
        "drift_phase_return_count": sum(event["kind"] == "drift_phase_return" for event in events),
        "drift_phase_candidate_count": sum(
            event["kind"] == "drift_phase_candidate" for event in events
        ),
        "drift_coordinate_return_count": sum(
            event["kind"] == "drift_coordinate_return" for event in events
        ),
        "drift_coordinate_return_diagnostics": _drift_coordinate_return_diagnostics(events),
        "mirrored_nonretracing_branch_turn_diagnostics": mirrored_branch_diagnostics,
        "same_direction_central_plane_periods_us": directional_periods,
        "same_direction_central_plane_period_median_us": median(directional_periods) if directional_periods else None,
        "effective_axial_width_W_mm": widths if kinetic_energy_ev is not None and mass_th is not None else None,
        "effective_axial_width_W_median_mm": median(widths) if widths else None,
        "detector_tof_us": detected_times,
        "detector_tof_fwhm_us": fwhm,
        "peak_analysis": peak,
        "peak_analysis_contract": peak_analysis_contract,
        "particle_mass_th": mass_th,
        "cohort_role": cohort_role,
        "detector_tof_mean_us": peak["mean"],
        "detector_tof_median_us": center_time,
        "mass_resolution_t_over_2fwhm": resolution,
        "volume_only": volume_only,
        "target_k_handoff_tof_us": target_k_times,
        "target_k_handoff_tof_fwhm_us": target_k_fwhm,
        "target_k_handoff_tof_median_us": target_k_center_time,
        "target_k_handoff_sample_count": len(target_k_times),
        "target_k_handoff_is_not_detector_resolution": True,
        "all_losses_retained": valid,
    }


def _bound_input(root: Path, record: dict[str, Any]) -> Path:
    name = record.get("filename")
    if not isinstance(name, str) or Path(name).name != name:
        raise ValueError("prototype input must be a local filename")
    path = root / name
    if hashlib.sha256(path.read_bytes()).hexdigest() != record.get("sha256"):
        raise ValueError(f"prototype input identity changed: {name}")
    return path


def load_particle_source(input_manifest: Path, source_key: str) -> dict[str, Any]:
    """Resolve the selected frozen Fly2 and its contract-derived exact cohort."""
    manifest = json.loads(input_manifest.read_text(encoding="utf-8"))
    schema_version = manifest.get("schema_version")
    if schema_version not in (2, 3) or source_key not in SOURCE_COUNT_KEYS:
        raise ValueError("current prototype source manifest and explicit source key are required")
    contract_path = _bound_input(input_manifest.parent, manifest["derived_contract"])
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    record = manifest[source_key]
    source_path = _bound_input(input_manifest.parent, record)
    count_key = SOURCE_COUNT_KEYS[source_key]
    count = contract["particle_source"][count_key]
    if type(count) is not int or count <= 0:
        raise ValueError("source contract has invalid particle count")
    particle_ids = list(range(1, count + 1))
    identity = json.dumps(particle_ids, separators=(",", ":")).encode("utf-8")
    if (record.get("particle_count_contract_key") != count_key
            or type(record.get("particle_count")) is not int or record["particle_count"] != count
            or record.get("expected_particle_ids") != particle_ids
            or any(type(value) is not int for value in record.get("expected_particle_ids", []))
            or record.get("expected_particle_ids_sha256") != hashlib.sha256(identity).hexdigest()):
        raise ValueError("frozen particle identities differ from the source contract")
    target_k = resolve_drift_phase_contract(contract).target_period_ratio
    particle_source = contract.get("particle_source", {})
    species = particle_source.get("species") if isinstance(particle_source, dict) else None
    if not isinstance(species, dict):
        species = None
    elif not type(species.get("mass_th")) in (int, float) or not math.isfinite(
        float(species["mass_th"])
    ) or float(species["mass_th"]) <= 0.0:
        raise ValueError("source contract species mass must be finite and positive")
    if species is not None and (
        type(species.get("charge_e")) not in (int, float)
        or not math.isfinite(float(species["charge_e"]))
        or float(species["charge_e"]) == 0.0
    ):
        raise ValueError("source contract species charge must be finite and nonzero")
    axial_kinetic_energy_ev: float | None = None
    if schema_version == 2:
        if species is not None and (
            type(species.get("kinetic_energy_ev")) not in (int, float)
            or not math.isfinite(float(species["kinetic_energy_ev"]))
            or float(species["kinetic_energy_ev"]) <= 0.0
        ):
            raise ValueError("legacy source contract kinetic energy must be finite and positive")
        if species is not None:
            axial_kinetic_energy_ev = float(species["kinetic_energy_ev"])
    else:
        expected_profile = SOURCE_PROFILE_IDS.get(source_key)
        if expected_profile is None or record.get("source_profile_id") != expected_profile:
            raise ValueError("current frozen source does not bind its named source profile")
        profile = particle_source.get(expected_profile) if isinstance(particle_source, dict) else None
        if not isinstance(profile, dict):
            raise ValueError("current source contract omits the selected named profile")
        if expected_profile == "full_mrtof_center" and profile.get("publishable") is not True:
            raise ValueError("full MR-TOF center remains unpublished")
        if expected_profile == "mirror_internal_diagnostic":
            energy = profile.get("axial_kinetic_energy_ev")
        elif expected_profile in ("first_prism_entry_diagnostic", "full_mrtof_center"):
            energy = contract.get("prism_transport", {}).get("energy_partition", {}).get(
                "fast_reflection_kinetic_energy_ev"
            )
        else:
            energy = None
        if energy is not None:
            if type(energy) not in (int, float) or not math.isfinite(float(energy)) or float(energy) <= 0.0:
                raise ValueError("selected source profile axial energy must be finite and positive")
            axial_kinetic_energy_ev = float(energy)
    return {"expected_particle_ids": tuple(particle_ids), "target_k": target_k, "species": species,
            "axial_kinetic_energy_ev": axial_kinetic_energy_ev,
            "provenance": {"input_manifest_sha256": hashlib.sha256(input_manifest.read_bytes()).hexdigest(),
                           "source_key": source_key, "fly2_filename": source_path.name,
                           "fly2_sha256": record["sha256"],
                           "expected_particle_ids_sha256": record["expected_particle_ids_sha256"],
                           "derived_contract_sha256": manifest["derived_contract"]["sha256"]}}


def analyze_log(log_path: Path, output_path: Path, *, input_manifest: Path, source_key: str) -> dict[str, Any]:
    """Parse a run log and write a stable JSON Candidate result receipt."""
    source = load_particle_source(input_manifest, source_key)
    text = log_path.read_text(encoding="utf-8")
    matches = list(FLY_COMPLETED.finditer(text))
    reported_splat_count = int(matches[0].group("splats")) if len(matches) == 1 else None
    summary = summarize_events(parse_events(text), source["target_k"], reported_splat_count,
                               expected_particle_ids=source["expected_particle_ids"], completion_count=len(matches),
                               kinetic_energy_ev=source["axial_kinetic_energy_ev"],
                               mass_th=(float(source["species"]["mass_th"]) if source["species"] else None),
                               charge_e=(float(source["species"]["charge_e"]) if source["species"] else None))
    summary["source"] = source["provenance"]
    summary["log_sha256"] = hashlib.sha256(log_path.read_bytes()).hexdigest()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an all-particle MR-TOF SIMION event receipt.")
    parser.add_argument("log_path", type=Path)
    parser.add_argument("output_path", type=Path)
    parser.add_argument("--input-manifest", required=True, type=Path)
    parser.add_argument("--source-key", required=True, choices=tuple(SOURCE_COUNT_KEYS))
    arguments = parser.parse_args()
    try:
        summary = analyze_log(arguments.log_path, arguments.output_path,
                              input_manifest=arguments.input_manifest, source_key=arguments.source_key)
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(f"MRTOF_EVENT_ANALYSIS=FAIL ERROR={error}")
        return 1
    print(
        f"MRTOF_EVENT_ANALYSIS={'PASS' if summary['event_integrity_passed'] else 'FAIL'} "
        f"TERMINAL={summary['particle_terminal_count']} "
        f"DETECTOR={summary['detector_hit_count']} "
        f"TARGET_K={summary['target_k_count']}"
    )
    return 0 if summary["event_integrity_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
