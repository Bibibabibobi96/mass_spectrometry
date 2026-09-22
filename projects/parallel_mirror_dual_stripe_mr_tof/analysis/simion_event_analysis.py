"""Parse MR-TOF Candidate SIMION event receipts without filtering losses."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import re
from pathlib import Path
from statistics import median
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
    "patch_interface": {
        "ion", "name", "region", "face", "n", "direction", "t_us",
        "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us",
    },
    "instance_transition": {"ion", "t_us", "instance", "x_mm", "y_mm", "z_mm"},
    "accelerator_pulse_off": {
        "ion", "t_us", "from_instance", "to_instance", "x_mm", "y_mm", "z_mm",
    },
    "accelerator_safe_exit": {
        "ion", "t_us", "from_instance", "to_instance", "x_mm", "y_mm", "z_mm",
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
    string_fields = {"name", "region", "face", "trigger", "termination_kind", "reason"}
    if any(type(value) not in (float, int) or not math.isfinite(value)
           for key, value in event.items()
           if key not in {"kind", *string_fields}):
        return "nonfinite_or_nonnumeric_event_field"
    for key in string_fields:
        if key in event and (not isinstance(event[key], str) or not event[key]):
            return "invalid_event_identity"
    if not _integer(event["ion"], minimum=1) or event["t_us"] < 0:
        return "invalid_particle_id_or_time"
    for key in ("turns", "central_crossings", "n", "half_cycles", "electrode", "to_instance"):
        if key in event and not _integer(event[key], minimum=0):
            return "invalid_event_counter"
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


def summarize_events(
    events: list[dict[str, Any]], target_k: float, reported_splat_count: int | None = None,
    *, expected_particle_ids: tuple[int, ...] | None = None,
    completion_count: int | None = None,
    kinetic_energy_ev: float | None = None,
    mass_th: float | None = None,
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
    fwhm = _fwhm(detected_times) if valid else None
    target_k_fwhm = _fwhm(target_k_times) if valid else None
    center_time = median(detected_times) if valid and detected_times else None
    target_k_center_time = median(target_k_times) if valid and target_k_times else None
    resolution = (
        center_time / (2.0 * fwhm)
        if center_time is not None and fwhm is not None and fwhm > 0.0
        else None
    )
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
        "detector_tof_median_us": center_time,
        "mass_resolution_t_over_2fwhm": resolution,
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
                               mass_th=(float(source["species"]["mass_th"]) if source["species"] else None))
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
