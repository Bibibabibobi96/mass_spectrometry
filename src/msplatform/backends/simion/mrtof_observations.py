"""Read recorded MR SIMION observations and retain native event/trajectory semantics."""
from __future__ import annotations
import argparse
from collections import Counter
from collections.abc import Iterable
from contextlib import nullcontext
import copy
import csv
import hashlib
import json
from io import StringIO
import math
from pathlib import Path
import re
from statistics import mean, pstdev
from typing import Any
from msplatform.io.scientific_csv import iter_csv_rows
from msplatform.io.file_identity import file_sha256
from msplatform.contracts.particle_physics import AMU_KG as ATOMIC_MASS_KG, ELEMENTARY_CHARGE_C
from msplatform.contracts.trajectory_recording import resolve_trajectory_recording
from msplatform.backends.simion.native_completion import parse_fly_completed_line


EVENT = re.compile(r"^MRTOF_EVENT\s+(?P<kind>\w+)\s+(?P<fields>.*)$")


FIELD = re.compile(r"(?P<key>[A-Za-z_]+)=(?P<value>[^\s]+)")


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
    return parse_event_lines(StringIO(text))


def parse_event_lines(lines: Iterable[str]) -> list[dict[str, Any]]:
    """Legacy stdout adapter; each input line is consumed once."""
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, 1):
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


def unavailable_peak_metadata(
    sample_count: int, status: str, *, method_id: str | None = None,
    settings: dict[str, Any] | None = None,
    time_reference: dict[str, Any] | None = None,
    weights: list[float] | None = None,
) -> dict[str, Any]:
    """Describe observed inputs without inventing an unavailable peak or clock.

    None weights explicitly mean the native unit-weight source. Measured callers
    supply their canonical per-ID weights, even when no peak was requested.
    """
    if weights is None:
        weight_sum, effective_count, equal = float(sample_count), float(sample_count), True
    else:
        if len(weights) != sample_count or any(
            isinstance(value, bool) or not math.isfinite(value) or value <= 0 for value in weights
        ):
            raise ValueError("peak input weights must be positive finite values matching the observations")
        weight_sum = math.fsum(weights)
        if not math.isfinite(weight_sum):
            raise ValueError("peak input weight sum must be finite")
        equal = not weights or all(value == weights[0] for value in weights)
        scale = max(weights, default=1.0)
        scaled = [value / scale for value in weights]
        effective_count = (math.fsum(scaled)**2 / math.fsum(value*value for value in scaled)
                           if scaled else 0.0)
    return {
        "schema_version": 1, "method_id": method_id, "status": status,
        "scientific_qualification": "not_assessed", "mass_axis": None,
        "sample_count": sample_count, "weight_sum": weight_sum,
        "effective_sample_count": effective_count, "sample_sigma_ddof": 1,
        "weight_policy": ("equal_positive_relative_weights" if equal
                          else "nonuniform_positive_relative_weights__kde_unsupported"),
        "settings": settings,
        "units": {"tof": "us", "time_width": "ns", "time_density": "1/us"},
        "time_reference": time_reference or {"kind": "unspecified", "clock_qualification": "unspecified"},
    }


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
                    box_holes: list[list[float]] | None = None, polygon_holes: list[list[list[float]]] | None = None,
                    extruded_holes: list[dict[str, Any]] | None = None) -> None:
        solids.append({"component": component, "electrode_id": electrode_id, "x": x_range,
                       "polygon": polygon, "box_holes": [] if box_holes is None else box_holes,
                       "polygon_holes": [] if polygon_holes is None else polygon_holes,
                       "extruded_holes": [] if extruded_holes is None else extruded_holes})

    def primitive_contains(point: tuple[float, float, float], shape: dict[str, Any], margin: float) -> bool:
        # Match the normalized IP GEM union-minus-cutouts, including finite
        # cylinder end caps. Negative margin selects a strict interior hole.
        if shape["shape"] == "box":
            box = shape["min_mm"] + shape["max_mm"]
            return (_box_contains(point, box, margin) if margin >= 0 else
                    _strict_box_hole(point, box, -margin))
        if shape["shape"] != "cylinder3d":
            raise ValueError("unsupported normalized IP collision primitive")
        start, end = shape["endpoints_mm"]
        axis = [end[a] - start[a] for a in range(3)]
        length = math.sqrt(sum(v * v for v in axis))
        along = sum((point[a] - start[a]) * axis[a] for a in range(3)) / length
        radial = math.sqrt(sum((point[a] - start[a] - along * axis[a] / length) ** 2 for a in range(3)))
        return -margin < along < length + margin and radial < float(shape["radius_mm"]) + margin

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
        if "polygon_yz_mm" in shield:
            add_polygon("mirror_inner_ground_shields", 15, shield["x"], shield["polygon_yz_mm"],
                        extruded_holes=shield["holes"])
        else:
            add_box("mirror_inner_ground_shields", 15, shield["box"], [collision_geometry["mirror_inner_shield_slot"]])
    for mirror in collision_geometry.get("mirror_electrodes", []):
        if "polygon_yz_mm" in mirror:
            add_polygon("mirror_electrodes", int(mirror["id"]), mirror["x"], mirror["polygon_yz_mm"],
                        extruded_holes=mirror["holes"])
        else:
            add_box("mirror_electrodes", int(mirror["id"]), mirror["box"], [collision_geometry["mirror_slot"]])
    for closure in collision_geometry.get("mirror_e_closures", []):
        if "polygon_yz_mm" in closure:
            add_polygon("mirror_outer_e_closures", int(closure["id"]), closure["x"], closure["polygon_yz_mm"],
                        extruded_holes=closure["holes"])
        else:
            add_box("mirror_outer_e_closures", int(closure["id"]), closure["box"])
    for prism in collision_geometry.get("prism_electrodes", []):
        for part in prism["parts"]:
            add_polygon(f"p{int(prism['id']) - 15}_prism_electrode", int(prism["id"]),
                        part["x"], part["polygon_yz_mm"])
    for electrode in collision_geometry.get("ion_processor_electrodes", []):
        for shape in electrode["solids"]:
            solids.append({"component": "ion_processor_" + electrode["name"],
                           "electrode_id": int(electrode["electrode_id"]), "primitive": shape,
                           "primitive_holes": electrode["cutouts"], "box_holes": []})
    if "detector" in collision_geometry:
        detector = collision_geometry["detector"]
        add_box("detector", int(detector["id"]), detector["box"])

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
            occupied = (primitive_contains(point, solid["primitive"], tolerance) if "primitive" in solid else
                        _box_contains(point, solid["box"], tolerance) if "box" in solid else
                        _extruded_polygon_contains(point, solid["x"], solid["polygon"], tolerance))
            if not occupied or any(_strict_box_hole(point, hole, tolerance) for hole in solid["box_holes"]):
                continue
            if any(primitive_contains(point, hole, -tolerance) for hole in solid.get("primitive_holes", [])):
                continue
            if any(
                float(solid["x"][0]) + tolerance < point[0] < float(solid["x"][1]) - tolerance
                and _strict_polygon_hole((point[1], point[2]), hole, tolerance)
                   for hole in solid.get("polygon_holes", [])):
                continue
            if any(hole["x"][0] + tolerance < point[0] < hole["x"][1] - tolerance
                   and _strict_polygon_hole((point[1], point[2]), hole["polygon_yz_mm"], tolerance)
                   for hole in solid.get("extruded_holes", [])):
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


def read_scientific_events(log_path: Path, *, scientific_event_output: dict[str, Any] | None = None, native_log_observer=None) -> tuple[list[dict[str, Any]], list[Any], str]:
    """Read declared CSV or legacy event lines, with one native-log byte scan.

    CSV paths must come from the caller's frozen run/receipt. A declared missing
    or malformed CSV never falls back to stdout. Native completion is separate.
    """
    digest = hashlib.sha256()
    completions = []
    def lines():
        with log_path.open("rb") as stream:
            for number, raw in enumerate(stream):
                digest.update(raw)
                line = raw.decode("utf-8-sig" if number == 0 else "utf-8")
                if native_log_observer is not None:
                    native_log_observer(line)
                completion = parse_fly_completed_line(line)
                if completion is not None:
                    completions.append(completion)
                yield line
    if scientific_event_output is None:
        events = parse_event_lines(lines())
    else:
        if "events_path" not in scientific_event_output:
            raise ValueError("declared scientific event output lacks events_path")
        for _ in lines():
            pass
        events = []
        for number, row in enumerate(iter_csv_rows(Path(scientific_event_output["events_path"]), ("kind", "ion"), expected_record=scientific_event_output.get("events_record")), 2):
            event = {}
            for key, value in row.items():
                if value == "":
                    continue
                try:
                    event[key] = float(value) if key != "kind" else value
                except ValueError:
                    event[key] = value
            error = _event_error(event)
            if not error and not LOG_REQUIRED_FIELDS[event["kind"]] <= event.keys():
                error = "incomplete_log_event"
            if error:
                raise ValueError(f"{error} at CSV row {number}")
            events.append(event)
    return events, completions, digest.hexdigest()


def _collision_geometry_projection(resolved: dict[str, Any]) -> dict[str, Any]:
    """Freeze only the resolved solids needed to name terminal collisions."""
    keys = (
        "mirror_electrodes", "mirror_slot", "mirror_inner_shield_slot",
        "mirror_ground_shields", "mirror_e_closures", "stripe_electrodes",
        "stripe_slot", "central_ground_electrodes", "central_ground_slots",
        "prism_electrodes", "prism_ground_shields",
    )
    return {
        "schema_version": 1,
        "mesh_mm_per_gu": 0.25,
        **{key: copy.deepcopy(resolved[key]) for key in keys},
        **{key: copy.deepcopy(resolved[key]) for key in ("ion_processor_electrodes", "detector") if key in resolved},
    }


def extract_trajectory_samples(*, log_path: Path, output_path: Path, receipt_path: Path,
                               recording_config: dict[str, Any] | None = None,
                               scientific_event_output: dict[str, Any] | None = None) -> dict[str, Any]:
    """Stream solver callback states into CSV, rejecting incomplete per-ion lifecycles."""
    recording = resolve_trajectory_recording({"simion": {"trajectory_recording": recording_config}})
    mode = recording["mode"] if recording else "every_step"
    columns = ["ion", "phase", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us"]
    counts: dict[int, int] = {}
    last: dict[int, tuple[float, str]] = {}
    prior_time: dict[int, float] = {}
    last_state: dict[int, tuple[float, ...]] = {}
    terminal_clock_backsteps = []
    output_path.parent.mkdir(parents=True, exist_ok=True)
    trajectory_identity = {}
    declared_path = None
    def actual_rows():
        nonlocal declared_path
        if scientific_event_output is not None:
            if not scientific_event_output.get("trajectory_path"):
                raise ValueError("declared trajectory output missing")
            declared_path = Path(scientific_event_output["trajectory_path"])
            yield from iter_csv_rows(declared_path, columns, exact_header=columns, identity_result=trajectory_identity, expected_record=scientific_event_output.get("trajectory_record"))
        else:
            with log_path.open(encoding="utf-8-sig") as source:
                for line in source:
                    if line.startswith("MRTOF_TRAJECTORY "):
                        yield dict(item.split("=", 1) for item in line.split()[1:])
    with (output_path.open("w",encoding="utf-8",newline="") if scientific_event_output is None else nullcontext(None)) as target:
        writer=csv.DictWriter(target,fieldnames=columns) if target is not None else None
        if writer is not None: writer.writeheader()
        for row in actual_rows():
            if set(row) != set(columns):
                raise ValueError("trajectory sample has missing or unknown fields")
            ion, time = int(row["ion"]), float(row["t_us"])
            if ion < 1 or not all(math.isfinite(float(row[key])) for key in columns[2:]):
                raise ValueError("trajectory sample identity or state is invalid")
            phase = row["phase"]
            state = tuple(float(row[key]) for key in columns[3:])
            if phase not in {"birth", "step", "terminal"}:
                raise ValueError("unknown trajectory sample phase")
            if ion not in last:
                if phase != "birth":
                    raise ValueError("trajectory does not start at birth")
            else:
                if phase == "birth" or last[ion][1] == "terminal":
                    raise ValueError("trajectory lifecycle or time order is invalid")
                if time < last[ion][0]:
                    # Native electrode contact can restore the preceding callback
                    # clock at terminate while retaining the last identical state.
                    # Keep both raw records. Every-step recording requires the
                    # exact prior callback clock; sparse recording bounds it by
                    # adjacent observations and does not establish one-step size.
                    clock_matches = time == prior_time.get(ion)
                    if mode == "fixed_interval":
                        clock_matches = prior_time.get(ion, last[ion][0]) <= time < last[ion][0]
                    if phase != "terminal" or not clock_matches or state != last_state[ion]:
                        raise ValueError("trajectory time order is invalid")
                    terminal_clock_backsteps.append({"ion": ion, "backstep_us": last[ion][0] - time})
                prior_time[ion] = last[ion][0]
            last[ion] = (time, phase)
            last_state[ion] = state
            counts[ion] = counts.get(ion, 0) + 1
            if writer is not None: writer.writerow(row)
    if declared_path is not None: output_path=declared_path
    minimum_samples = 2 if mode == "fixed_interval" else 3
    if not counts or any(phase != "terminal" or counts[ion] < minimum_samples for ion, (_, phase) in last.items()):
        raise ValueError("trajectory is empty or lacks steps/terminal state")
    result = {"schema_version": 1, "role": "mrtof_solver_step_trajectory", "status": "success",
              "sampling": ("initialize__first_other_actions_callback_per_absolute_clock_bucket__terminate"
                           if mode == "fixed_interval" else "initialize__every_other_actions_callback__terminate"),
              "sampling_mode": mode, "sampling_interval_us": recording["interval_us"] if mode == "fixed_interval" else None,
              "sampling_grid_origin_us": 0 if mode == "fixed_interval" else None,
              "recording_configuration": recording,
              "interpolated": False, "frame_id": "astral.xyz.reflection_z.drift_y.transverse_x.v2",
              "clock_basis": "instrument_time_us_from_frozen_source_authority",
              "sample_count": sum(counts.values()), "samples_per_particle": counts,
              "terminal_clock_backsteps": terminal_clock_backsteps,
              "record_order": "solver_callback_order__raw_terminal_clock_retained",
              "source_log": str(log_path.resolve()), "source_log_sha256": file_sha256(log_path).lower(),
              "trajectory_csv": str(output_path.resolve()), "trajectory_csv_sha256": trajectory_identity["sha256"] if declared_path is not None else file_sha256(output_path).lower()}
    receipt_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    extract = commands.add_parser("extract-trajectory")
    extract.add_argument("--log", required=True, type=Path)
    extract.add_argument("--output", required=True, type=Path)
    extract.add_argument("--receipt", required=True, type=Path)
    extract.add_argument("--contract", type=Path)
    args = parser.parse_args()
    recording = resolve_trajectory_recording(json.loads(args.contract.read_text(encoding="utf-8-sig"))) if args.contract else None
    result = extract_trajectory_samples(log_path=args.log, output_path=args.output, receipt_path=args.receipt,
        recording_config=recording)
    print(f"MRTOF_TRAJECTORY_EXTRACT=PASS SAMPLES={result['sample_count']}")


if __name__ == "__main__":
    main()
