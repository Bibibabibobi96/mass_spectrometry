"""Extract particle-resolved checkpoints and detector metrics from one SIMION flight."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import csv
import json
import re
from pathlib import Path

import numpy as np

from common.contracts.particle_physics import kinetic_energy_ev
from projects.single_reflection_oa_tof_mass_analyzer.analysis.peak_metrics import (
    bootstrap_resolution_distribution,
    compute_peak_metrics,
)


STATE_PATTERN = re.compile(
    r"TRACE: (?P<event>source_release|single_flight_handoff|pre_pulse_state|accelerator_grid1_forward|local_accelerator_exit|accelerator_focus_forward|reflectron_entrance_forward|reflectron_midgrid_forward|reflectron_turning_point|reflectron_exit_return) "
    r"ion=(?P<ion>\d+)(?: particle_id=(?P<particle_id>\d+))? instrument_time_us=(?P<t>[-+0-9.eE]+) "
    r"(?:tof_since_pulse_us=(?P<tof_since_pulse>[-+0-9.eE]+) )?"
    r"x_mm=(?P<x>[-+0-9.eE]+) y_mm=(?P<y>[-+0-9.eE]+) z_mm=(?P<z>[-+0-9.eE]+) "
    r"vx_mm_per_us=(?P<vx>[-+0-9.eE]+) vy_mm_per_us=(?P<vy>[-+0-9.eE]+) "
    r"vz_mm_per_us=(?P<vz>[-+0-9.eE]+)(?: kinetic_energy_eV=(?P<energy>[-+0-9.eE]+) survival_status=(?P<survival>\w+))?"
)
DETECTOR_PATTERN = re.compile(
    r"TRACE: detector_crossing ion=(?P<ion>\d+) t=(?P<t>[-+0-9.eE]+) "
    r"x=(?P<x>[-+0-9.eE]+) y=(?P<y>[-+0-9.eE]+) z=(?P<z>[-+0-9.eE]+)"
)
PULSE_PATTERN = re.compile(r"TRACE: handoff_pulse_on instrument_time_us=(?P<t>[-+0-9.eE]+)")
COLUMNS = [
    "particle_id", "event", "instrument_time_us", "x_mm", "y_mm", "z_mm",
    "vx_mm_per_us", "vy_mm_per_us", "vz_mm_per_us", "kinetic_energy_eV",
    "pulse_eligibility", "tof_since_pulse_us", "survival_status",
]

POST_FOCUS_EVENTS = (
    "accelerator_focus_forward",
    "reflectron_entrance_forward",
    "reflectron_midgrid_forward",
    "reflectron_turning_point",
    "reflectron_exit_return",
    "detector_crossing",
)
REFLECTRON_EVENTS = POST_FOCUS_EVENTS[1:5]
REFLECTRON_PATH_EVENTS = POST_FOCUS_EVENTS[:-1]


def _validate_reflectron_event_order(rows: list[dict[str, object]]) -> None:
    """Reject non-prefix or non-monotonic reflectron checkpoint sequences."""
    by_particle: dict[int, dict[str, float]] = {}
    for row in rows:
        event = str(row["event"])
        if event in REFLECTRON_EVENTS:
            by_particle.setdefault(int(row["particle_id"]), {})[event] = float(
                row["instrument_time_us"]
            )
    for particle_id, observed in by_particle.items():
        observed_indices = [
            index for index, event in enumerate(REFLECTRON_EVENTS) if event in observed
        ]
        if observed_indices != list(range(len(observed_indices))):
            raise ValueError(
                f"reflectron checkpoint sequence is not a prefix: particle={particle_id}"
            )
        times = [observed[event] for event in REFLECTRON_EVENTS[: len(observed_indices)]]
        if any(right <= left for left, right in zip(times, times[1:])):
            raise ValueError(
                f"reflectron checkpoint times are not strictly ordered: particle={particle_id}"
            )


def _resolve_pulse_time_us(
    configured_time_us: float | None, observed_times_us: list[float]
) -> float | None:
    """Resolve one effective pulse time and reject inconsistent log/config clocks."""
    if configured_time_us is not None and not np.isfinite(configured_time_us):
        raise ValueError("pulse effective time must be finite")
    if observed_times_us:
        reference = observed_times_us[0]
        if any(abs(value - reference) > 1e-9 for value in observed_times_us[1:]):
            raise ValueError("SIMION batches report inconsistent pulse effective times")
        if configured_time_us is not None and abs(configured_time_us - reference) > 1e-9:
            raise ValueError("configured and logged pulse effective times differ")
        return reference
    return configured_time_us


def _peak_summary(
    times_us: np.ndarray,
    mass_amu: float,
    *,
    bootstrap_resamples: int,
    bootstrap_seed: int,
) -> tuple[dict[str, object] | None, dict[str, object]]:
    """Compute the canonical direct peak and its fixed-seed bootstrap metadata."""
    bootstrap: dict[str, object] = {
        "resamples_requested": bootstrap_resamples,
        "seed": bootstrap_seed,
        "status": "not_computed",
    }
    if times_us.size < 3:
        bootstrap["reason"] = "fewer_than_three_detected_particles"
        return None, bootstrap
    peak, _ = compute_peak_metrics(times_us, mass_amu)
    if bootstrap_resamples > 0:
        bootstrap = bootstrap_resolution_distribution(
            times_us,
            mass_amu,
            resamples=bootstrap_resamples,
            seed=bootstrap_seed,
        )
        bootstrap["status"] = "computed"
        bootstrap["relative_95pct_interval_width"] = (
            float(bootstrap["resolution_p97p5"])
            - float(bootstrap["resolution_p2p5"])
        ) / float(peak["mass_resolution"])
    return peak, bootstrap


def _segment_diagnostics(
    rows: list[dict[str, object]], eligible_ids: set[int]
) -> dict[str, object]:
    """Summarize paired post-focus flight increments without outcome filtering."""
    by_event = {
        event: {
            int(row["particle_id"]): row
            for row in rows
            if row["event"] == event and int(row["particle_id"]) in eligible_ids
        }
        for event in POST_FOCUS_EVENTS
    }
    reflectron_common_ids = set(eligible_ids)
    for event in REFLECTRON_PATH_EVENTS:
        reflectron_common_ids &= set(by_event[event])
    reflectron_common = sorted(reflectron_common_ids)
    segments = []
    for start_event, end_event in zip(POST_FOCUS_EVENTS, POST_FOCUS_EVENTS[1:]):
        common = (
            sorted(reflectron_common_ids & set(by_event["detector_crossing"]))
            if end_event == "detector_crossing"
            else reflectron_common
        )
        record: dict[str, object] = {
            "start_event": start_event,
            "end_event": end_event,
            "cohort_basis": (
                "reflectron_complete_path_paired_with_detector"
                if end_event == "detector_crossing"
                else "reflectron_complete_path_without_detector_filter"
            ),
            "common_cohort_count": len(common),
        }
        if common:
            start = by_event[start_event]
            end = by_event[end_event]
            delta_ns = np.asarray([
                1000.0 * (
                    float(end[particle_id]["instrument_time_us"])
                    - float(start[particle_id]["instrument_time_us"])
                )
                for particle_id in common
            ])
            record.update({
                "mean_segment_time_ns": float(np.mean(delta_ns)),
                "sample_sigma_segment_time_ns": (
                    float(np.std(delta_ns, ddof=1)) if len(common) > 1 else 0.0
                ),
            })
            if len(common) >= 2:
                predictors = np.asarray([
                    [
                        float(start[particle_id][field])
                        for field in ("x_mm", "y_mm", "z_mm", "vx_mm_per_us", "vy_mm_per_us", "vz_mm_per_us")
                    ]
                    for particle_id in common
                ])
                design = np.column_stack([np.ones(len(common)), predictors])
                rank = int(np.linalg.matrix_rank(design))
                degrees_of_freedom = len(common) - rank
                record["linear_regression_rank"] = rank
                record["linear_regression_degrees_of_freedom"] = degrees_of_freedom
                if rank == design.shape[1] and degrees_of_freedom > 0:
                    coefficients, _, _, _ = np.linalg.lstsq(
                        design, delta_ns, rcond=None
                    )
                    residual = delta_ns - design @ coefficients
                    record["linear_regression_residual_sigma_ns"] = float(
                        np.sqrt(np.sum(residual**2) / degrees_of_freedom)
                    )
                    record["linear_regression_status"] = "computed"
                else:
                    record["linear_regression_residual_sigma_ns"] = None
                    record["linear_regression_status"] = (
                        "insufficient_rank_or_residual_degrees_of_freedom"
                    )
                record["pearson_delta_time_by_start_state"] = {
                    name: (
                        float(np.corrcoef(predictors[:, index], delta_ns)[0, 1])
                        if np.std(predictors[:, index]) > 0 and np.std(delta_ns) > 0
                        else None
                    )
                    for index, name in enumerate(("x", "y", "z", "vx", "vy", "vz"))
                }
        segments.append(record)
    return {
        "population_basis": "pulse_eligible_reflectron_complete_path_without_detector_filter",
        "event_order": list(POST_FOCUS_EVENTS),
        "reflectron_common_cohort_particle_ids": reflectron_common,
        "reflectron_common_cohort_count": len(reflectron_common),
        "detector_paired_cohort_particle_ids": sorted(
            reflectron_common_ids & set(by_event["detector_crossing"])
        ),
        "detector_paired_cohort_count": len(
            reflectron_common_ids & set(by_event["detector_crossing"])
        ),
        "segments": segments,
    }


def analyze(
    log_path: Path | Sequence[Path],
    launched: int,
    mass_amu: float,
    geometry_path: Path | None = None,
    pulse_time_us: float | None = None,
    clock_basis: str = "legacy_relative_time",
    batch_particle_counts: Sequence[int] | None = None,
    initial_global_state_path: Path | None = None,
    spatial_window_profile: dict[str, object] | None = None,
    population_denominator_count: int | None = None,
    eligible_population_count: int | None = None,
    bootstrap_resamples: int = 0,
    bootstrap_seed: int = 20260812,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    if clock_basis not in {"legacy_relative_time", "absolute_birth_time"}:
        raise ValueError("unknown single-flight clock basis")
    if bootstrap_resamples < 0:
        raise ValueError("bootstrap resamples must be non-negative")
    log_paths = [log_path] if isinstance(log_path, Path) else list(log_path)
    if batch_particle_counts is None:
        batch_particle_counts = [launched]
    if (
        len(log_paths) != len(batch_particle_counts)
        or any(count < 1 for count in batch_particle_counts)
        or sum(batch_particle_counts) != launched
    ):
        raise ValueError("single-flight batch log/count identity differs")
    rows: list[dict[str, object]] = []
    seen: set[tuple[int, str]] = set()
    pulse_times: list[float] = []
    offset = 0
    lines: list[tuple[str, int, int]] = []
    for path, count in zip(log_paths, batch_particle_counts, strict=True):
        lines.extend(
            (line, offset, count)
            for line in path.read_text(
                encoding="utf-8-sig", errors="replace"
            ).splitlines()
        )
        offset += count
    for line, particle_offset, batch_count in lines:
        match = STATE_PATTERN.search(line)
        if match:
            event = {
                "source_release": "source_release",
                "single_flight_handoff": "multipole_handoff",
                "pre_pulse_state": "pre_pulse_state",
                "local_accelerator_exit": "local_accelerator_exit",
                "accelerator_grid1_forward": "accelerator_grid1_forward",
                "accelerator_focus_forward": "accelerator_focus_forward",
                "reflectron_entrance_forward": "reflectron_entrance_forward",
                "reflectron_midgrid_forward": "reflectron_midgrid_forward",
                "reflectron_turning_point": "reflectron_turning_point",
                "reflectron_exit_return": "reflectron_exit_return",
            }[match["event"]]
            local_id = int(match["ion"])
            if not 1 <= local_id <= batch_count:
                raise ValueError("logged particle identity is outside its batch")
            global_id = local_id + particle_offset
            if match["particle_id"] is not None and int(match["particle_id"]) != global_id:
                raise ValueError("logged global particle identity differs from batch offset")
            key = (global_id, event)
            if key in seen:
                raise ValueError(f"duplicate checkpoint: particle={key[0]} event={event}")
            seen.add(key)
            vx = float(match["vx"])
            vy = float(match["vy"])
            vz = float(match["vz"])
            recomputed_energy = kinetic_energy_ev(
                mass_amu, 1000.0 * vx, 1000.0 * vy, 1000.0 * vz
            )
            logged_energy = (
                float(match["energy"]) if match["energy"] is not None else None
            )
            if logged_energy is not None and not np.isclose(
                logged_energy,
                recomputed_energy,
                rtol=5e-9,
                atol=5e-10,
            ):
                raise ValueError(
                    f"logged kinetic energy differs from velocity: particle={key[0]} "
                    f"event={event}"
                )
            rows.append({
                "particle_id": key[0], "event": event, "instrument_time_us": float(match["t"]),
                "x_mm": float(match["x"]), "y_mm": float(match["y"]), "z_mm": float(match["z"]),
                "vx_mm_per_us": vx, "vy_mm_per_us": vy, "vz_mm_per_us": vz,
                "kinetic_energy_eV": recomputed_energy,
                "pulse_eligibility": "",
                "tof_since_pulse_us": (
                    float(match["tof_since_pulse"])
                    if match["tof_since_pulse"] is not None else ""
                ),
                "survival_status": match["survival"] or "alive",
            })
            continue
        match = DETECTOR_PATTERN.search(line)
        if match:
            local_id = int(match["ion"])
            if not 1 <= local_id <= batch_count:
                raise ValueError("logged particle identity is outside its batch")
            key = (local_id + particle_offset, "detector_crossing")
            if key in seen:
                raise ValueError(f"duplicate detector crossing: particle={key[0]}")
            seen.add(key)
            rows.append({
                "particle_id": key[0], "event": key[1], "instrument_time_us": float(match["t"]),
                "x_mm": float(match["x"]), "y_mm": float(match["y"]), "z_mm": float(match["z"]),
                "vx_mm_per_us": "", "vy_mm_per_us": "", "vz_mm_per_us": "",
                "kinetic_energy_eV": "",
                "pulse_eligibility": "",
                "tof_since_pulse_us": "",
                "survival_status": "detected",
            })
            continue
        match = PULSE_PATTERN.search(line)
        if match:
            pulse_times.append(float(match["t"]))
    if initial_global_state_path is not None:
        with initial_global_state_path.open(encoding="utf-8-sig", newline="") as handle:
            initial_rows = list(csv.DictReader(handle))
        if len(initial_rows) != launched:
            raise ValueError("initial global state row count differs from launched particles")
        traced_release_ids = {
            int(row["particle_id"])
            for row in rows
            if row["event"] == "source_release"
        }
        for initial in initial_rows:
            particle_id = int(initial["particle_id"])
            if particle_id in traced_release_ids:
                continue
            vx = float(initial["velocity_x_m_s"]) / 1000.0
            vy = float(initial["velocity_y_m_s"]) / 1000.0
            vz = float(initial["velocity_z_m_s"]) / 1000.0
            rows.append({
                "particle_id": particle_id,
                "event": "source_release",
                "instrument_time_us": float(initial["instrument_time_us"]),
                "x_mm": float(initial["position_x_mm"]),
                "y_mm": float(initial["position_y_mm"]),
                "z_mm": float(initial["position_z_mm"]),
                "vx_mm_per_us": vx,
                "vy_mm_per_us": vy,
                "vz_mm_per_us": vz,
                "kinetic_energy_eV": kinetic_energy_ev(
                    mass_amu, 1000.0 * vx, 1000.0 * vy, 1000.0 * vz
                ),
                "pulse_eligibility": "",
                "tof_since_pulse_us": "",
                "survival_status": "alive",
            })
    detector_offset_applied = False
    if clock_basis == "absolute_birth_time":
        birth_times = {
            int(row["particle_id"]): float(row["instrument_time_us"])
            for row in rows
            if row["event"] == "source_release"
        }
        detector_rows = [row for row in rows if row["event"] == "detector_crossing"]
        missing = sorted(
            int(row["particle_id"])
            for row in detector_rows
            if int(row["particle_id"]) not in birth_times
        )
        if missing:
            raise ValueError(
                "absolute detector clock correction lacks source-release times: "
                + ",".join(map(str, missing[:10]))
            )
        for row in detector_rows:
            particle_id = int(row["particle_id"])
            row["instrument_time_us"] = (
                float(row["instrument_time_us"]) + birth_times[particle_id]
            )
        detector_offset_applied = True
    rows.sort(key=lambda row: (int(row["particle_id"]), str(row["event"])))
    _validate_reflectron_event_order(rows)
    counts = {event: sum(row["event"] == event for row in rows) for event in (
        "source_release", "multipole_handoff", "pre_pulse_state",
        "accelerator_grid1_forward", "local_accelerator_exit", "accelerator_focus_forward",
        "reflectron_entrance_forward", "reflectron_midgrid_forward",
        "reflectron_turning_point", "reflectron_exit_return", "detector_crossing",
    )}
    if launched < 1 or any(int(row["particle_id"]) < 1 or int(row["particle_id"]) > launched for row in rows):
        raise ValueError("logged particle identity is outside the launched mother sample")
    effective_pulse_time_us = _resolve_pulse_time_us(pulse_time_us, pulse_times)
    detector_rows = [row for row in rows if row["event"] == "detector_crossing"]
    for row in rows:
        if effective_pulse_time_us is not None:
            computed = float(row["instrument_time_us"]) - effective_pulse_time_us
            reported = row["tof_since_pulse_us"]
            if reported != "" and abs(float(reported) - computed) > 1e-8:
                raise ValueError("logged pulse-effective checkpoint time is inconsistent")
            row["tof_since_pulse_us"] = computed
    instrument_detector_times = np.asarray(
        [float(row["instrument_time_us"]) for row in detector_rows], dtype=float
    )
    instrument_clock_peak, _ = _peak_summary(
        instrument_detector_times,
        mass_amu,
        bootstrap_resamples=0,
        bootstrap_seed=bootstrap_seed,
    )
    injection_energy_validation = None
    pulse_capture = None
    geometry = None
    if geometry_path is not None:
        geometry = json.loads(geometry_path.read_text(encoding="utf-8-sig"))
        dimensions = geometry["geometry_mm"]
        axis_x = float(geometry["coordinate_convention"]["accelerator_axis_x"])
        repeller_z = float(dimensions["accelerator_repeller_z"])
        grid1_z = float(dimensions["accelerator_grid1_z"])
        bore_half = float(dimensions["accelerator_bore_half"])
        samples = [row for row in rows if row["event"] == "pre_pulse_state"]
        if not samples:
            raise ValueError("injection energy validation requires pre_pulse_state samples")
        if pulse_time_us is None or any(
            float(row["instrument_time_us"]) > pulse_time_us + 1e-9
            for row in samples
        ):
            raise ValueError("pre_pulse_state energy sample is not before the accelerator pulse")
        eligibility_counts = {
            "eligible": 0,
            "upstream_of_repeller": 0,
            "downstream_of_grid1": 0,
            "outside_transverse_bore": 0,
            "missing_before_pulse": launched - len(samples),
        }
        eligible: list[dict[str, object]] = []
        for row in samples:
            z_mm = float(row["z_mm"])
            if z_mm <= repeller_z:
                classification = "upstream_of_repeller"
            elif z_mm >= grid1_z:
                classification = "downstream_of_grid1"
            elif abs(float(row["x_mm"]) - axis_x) >= bore_half or abs(float(row["y_mm"])) >= bore_half:
                classification = "outside_transverse_bore"
            else:
                classification = "eligible"
                eligible.append(row)
            row["pulse_eligibility"] = classification
            eligibility_counts[classification] += 1
        eligible_ids = {int(row["particle_id"]) for row in eligible}
        detector_ids = {
            int(row["particle_id"])
            for row in rows
            if row["event"] == "detector_crossing"
        }
        detected_eligible = len(eligible_ids & detector_ids)
        pulse_capture = {
            "definition": "inside_open_accelerator_stage1_at_pulse",
            "counts": eligibility_counts,
            "capture_fraction_of_launched": len(eligible) / launched,
            "detected_eligible_count": detected_eligible,
            "conditional_detector_efficiency": (
                detected_eligible / len(eligible) if eligible else None
            ),
            "selection_uses_detector_outcome": False,
        }
        energies = np.asarray(
            [float(row["kinetic_energy_eV"]) for row in eligible], dtype=float
        )
        target = geometry.get("single_flight_layout_derivation", {}).get(
            "target_injection_energy_eV"
        )
        injection_energy_validation = {
            "sampling_event": "pre_pulse_state",
            "sampling_scope": "oatof_accelerator_stage1_interior_before_pulse",
            "sample_count": len(eligible),
            "all_samples_inside_accelerator_stage1": True if eligible else None,
            "all_samples_at_or_before_pulse": True,
            "target_kinetic_energy_eV": target,
            "mean_kinetic_energy_eV": float(np.mean(energies)) if len(energies) else None,
            "sample_sigma_kinetic_energy_eV": float(np.std(energies, ddof=1)) if len(energies) > 1 else (0.0 if len(energies) else None),
            "minimum_kinetic_energy_eV": float(np.min(energies)) if len(energies) else None,
            "maximum_kinetic_energy_eV": float(np.max(energies)) if len(energies) else None,
            "mean_target_error_eV": None if target is None or not len(energies) else float(np.mean(energies) - float(target)),
            "terminal_or_handoff_energy_is_target_validation": False,
        }
    spatial_window_peak = None
    if spatial_window_profile is not None:
        if geometry is None:
            raise ValueError("spatial-window analysis requires resolved geometry")
        event = str(spatial_window_profile.get("event", ""))
        axes = spatial_window_profile.get("axes")
        if spatial_window_profile.get("selection_uses_detector_outcome") is not False:
            raise ValueError("spatial-window profile must be explicitly detector-blind")
        field_error_budget = spatial_window_profile.get("field_error_budget")
        if (
            not isinstance(field_error_budget, dict)
            or field_error_budget.get("frozen_before_particle_outcomes") is not True
            or float(field_error_budget.get("tof_error_budget_ns", 0.0)) <= 0
            or not str(field_error_budget.get("derivation", "")).strip()
        ):
            raise ValueError("spatial-window field-error budget is not frozen")
        minimum_coverage = float(
            spatial_window_profile.get("minimum_pulse_eligible_coverage", 0.0)
        )
        if not 0 < minimum_coverage <= 1:
            raise ValueError("spatial-window minimum coverage is invalid")
        if event not in {"source_release", "multipole_handoff", "pre_pulse_state", "local_accelerator_exit"}:
            raise ValueError("spatial-window event is invalid")
        if (
            not isinstance(axes, dict)
            or not axes
            or set(axes) - {"x", "y", "z", "angle_x", "angle_y"}
        ):
            raise ValueError("spatial-window axes are invalid")
        bounds: dict[str, dict[str, float | str]] = {}
        for axis, specification in axes.items():
            if not isinstance(specification, dict):
                raise ValueError("spatial-window axis specification is invalid")
            if axis in {"angle_x", "angle_y"}:
                expected_binding = "theory_source_center_angle_deg"
                if specification.get("center_binding") != expected_binding:
                    raise ValueError("spatial-window angle center binding is invalid")
                center = float(specification["center_deg"])
                width = float(specification["full_width_deg"])
                unit = "deg"
            else:
                expected_binding = f"particle_source.center_{axis}_mm"
                if specification.get("center_binding") != expected_binding:
                    raise ValueError("spatial-window center binding is invalid")
                center = float(geometry["particle_source"][f"center_{axis}_mm"])
                width = float(specification["full_width_mm"])
                unit = "mm"
            if width <= 0:
                raise ValueError("spatial-window width must be positive")
            bounds[axis] = {
                "center_binding": expected_binding,
                f"center_{unit}": center,
                f"full_width_{unit}": width,
                f"minimum_{unit}": center - width / 2.0,
                f"maximum_{unit}": center + width / 2.0,
            }
        pulse_eligible_ids = {
            int(row["particle_id"])
            for row in rows
            if row["event"] == "pre_pulse_state"
            and row["pulse_eligibility"] == "eligible"
        }
        event_rows = [
            row for row in rows
            if row["event"] == event
            and int(row["particle_id"]) in pulse_eligible_ids
        ]
        selected_ids = {
            int(row["particle_id"])
            for row in event_rows
            if all(
                (
                    float(bound["minimum_deg"])
                    <= np.degrees(np.arctan2(
                        float(row["vx_mm_per_us"] if axis == "angle_x" else row["vy_mm_per_us"]),
                        float(row["vz_mm_per_us"]),
                    ))
                    <= float(bound["maximum_deg"])
                    and float(row["vz_mm_per_us"]) > 0
                )
                if axis in {"angle_x", "angle_y"}
                else (
                    float(bound["minimum_mm"])
                    <= float(row[f"{axis}_mm"])
                    <= float(bound["maximum_mm"])
                )
                for axis, bound in bounds.items()
            )
        }
        coverage = len(selected_ids) / len(event_rows) if event_rows else None
        if coverage is None or coverage < minimum_coverage:
            raise ValueError("spatial-window pulse-eligible coverage is below its frozen minimum")
        selected_detector_times = np.asarray([
            float(row["tof_since_pulse_us"])
            for row in rows
            if row["event"] == "detector_crossing"
            and int(row["particle_id"]) in selected_ids
        ]) if effective_pulse_time_us is not None else np.asarray([], dtype=float)
        selected_peak, selected_bootstrap = _peak_summary(
            selected_detector_times,
            mass_amu,
            bootstrap_resamples=bootstrap_resamples,
            bootstrap_seed=bootstrap_seed,
        )
        spatial_window_peak = {
            "profile_id": spatial_window_profile["profile_id"],
            "event": event,
            "axis_semantics": {
                "acceleration_direction": "z",
                "non_acceleration_directions": ["x", "y"],
            },
            "bounds": bounds,
            "selection_uses_detector_outcome": False,
            "field_error_budget": field_error_budget,
            "minimum_pulse_eligible_coverage": minimum_coverage,
            "event_population_count": len(event_rows),
            "selected_count": len(selected_ids),
            "pulse_eligible_coverage_fraction": coverage,
            "selected_fraction_of_event_population": (
                len(selected_ids) / len(event_rows) if event_rows else None
            ),
            "detected_count": int(selected_detector_times.size),
            "conditional_detector_efficiency": (
                selected_detector_times.size / len(selected_ids) if selected_ids else None
            ),
            "pulse_effective_peak": selected_peak,
            "bootstrap": selected_bootstrap,
            "is_causal_counterfactual": False,
        }
    if population_denominator_count is None:
        population_denominator_count = launched
    full_candidate_population_simulated = launched == population_denominator_count
    if eligible_population_count is None:
        eligible_population_count = (
            pulse_capture["counts"]["eligible"]
            if full_candidate_population_simulated and pulse_capture is not None
            else launched
        )
    if not 0 <= eligible_population_count <= population_denominator_count:
        raise ValueError("source population counts are inconsistent")
    if not 0 < launched <= population_denominator_count:
        raise ValueError("simulated population count is inconsistent")
    if not full_candidate_population_simulated and launched > eligible_population_count:
        raise ValueError("conditional population exceeds the pulse-eligible population")
    if (
        full_candidate_population_simulated
        and pulse_capture is not None
        and eligible_population_count != pulse_capture["counts"]["eligible"]
    ):
        raise ValueError("pulse-eligible count conflicts with the observed full population")
    eligible_ids = {
        int(row["particle_id"])
        for row in rows
        if row["event"] == "pre_pulse_state"
        and row["pulse_eligibility"] == "eligible"
    }
    if geometry is None:
        eligible_ids = set(range(1, launched + 1))
    eligible_detector_tof = np.asarray(
        [
            float(row["tof_since_pulse_us"])
            for row in detector_rows
            if int(row["particle_id"]) in eligible_ids
        ],
        dtype=float,
    ) if effective_pulse_time_us is not None else np.asarray([], dtype=float)
    pulse_effective_peak, full_bootstrap = _peak_summary(
        eligible_detector_tof,
        mass_amu,
        bootstrap_resamples=bootstrap_resamples,
        bootstrap_seed=bootstrap_seed,
    )
    if spatial_window_peak is not None:
        selected_peak = spatial_window_peak["pulse_effective_peak"]
        spatial_window_peak["mass_resolution_ratio_to_full_pulse_eligible"] = (
            None if selected_peak is None or pulse_effective_peak is None else
            float(selected_peak["mass_resolution"])
            / float(pulse_effective_peak["mass_resolution"])
        )
    segment_diagnostics = _segment_diagnostics(rows, eligible_ids)
    detected_eligible_count = len(
        eligible_ids & {int(row["particle_id"]) for row in detector_rows}
    )
    complete_eligible_population_simulated = (
        full_candidate_population_simulated
        or (
            launched == eligible_population_count
            and eligible_ids == set(range(1, launched + 1))
        )
    )
    summary = {
        "schema_version": 3,
        "role": "rf_oatof_simion_single_flight_summary",
        "status": "success",
        "census": {"launched": launched, **counts},
        "transmission": {
            "multipole_handoff_fraction": counts["multipole_handoff"] / launched,
            "detector_fraction": counts["detector_crossing"] / launched,
            "detector_fraction_of_candidate_population": (
                counts["detector_crossing"] / population_denominator_count
            ),
            "eligible_to_detector_fraction": (
                detected_eligible_count / eligible_population_count
                if eligible_population_count else None
            ),
            "eligible_to_detector_qualification_ready": (
                complete_eligible_population_simulated
            ),
        },
        "source_population": {
            "candidate_population_count": population_denominator_count,
            "pulse_eligible_population_count": eligible_population_count,
            "simulated_population_count": launched,
            "simulation_population_basis": (
                "candidate_full_population"
                if full_candidate_population_simulated
                else "pulse_eligible_conditional_population"
            ),
            "raw_pulse_capture_fraction": (
                eligible_population_count / population_denominator_count
            ),
            "simulated_fraction_of_candidate_population": (
                launched / population_denominator_count
            ),
            "simulated_fraction_of_pulse_eligible_population": (
                None
                if full_candidate_population_simulated
                else launched / eligible_population_count
            ),
            "efficiency_denominator": "candidate_population_count",
            "qualification_requires_complete_pulse_eligible_simulation": True,
            "complete_pulse_eligible_population_simulated": (
                complete_eligible_population_simulated
            ),
        },
        "pulse_first_observed_us": min(pulse_times) if pulse_times else None,
        "pulse_effective_time_us": effective_pulse_time_us,
        "clock_basis": clock_basis,
        "resolution_time_basis": "detector_time_minus_pulse_effective_time",
        "pulse_effective_peak": pulse_effective_peak,
        "full_pulse_eligible_bootstrap": full_bootstrap,
        "detector_time_basis": "instrument_time_us_diagnostic_only",
        "detector_native_time_offset_applied": detector_offset_applied,
        "instrument_clock_peak": instrument_clock_peak,
        "instrument_clock_peak_is_resolution_claim": False,
        "injection_energy_validation": injection_energy_validation,
        "pulse_capture": pulse_capture,
        "spatial_window_peak": spatial_window_peak,
        "post_focus_common_cohort": segment_diagnostics,
        "spatial_six_panel": "results/single_flight_spatial_six_panel.png",
        "formal_gate_passed": False,
    }
    return rows, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", required=True, action="append", type=Path)
    parser.add_argument("--batch-particle-count", action="append", type=int)
    parser.add_argument("--launched", required=True, type=int)
    parser.add_argument("--mass-amu", required=True, type=float)
    parser.add_argument("--geometry", type=Path)
    parser.add_argument("--pulse-time-us", type=float)
    parser.add_argument("--initial-global-state", type=Path)
    parser.add_argument("--configuration", type=Path)
    parser.add_argument("--spatial-window-profile-id")
    parser.add_argument("--population-denominator-count", type=int)
    parser.add_argument("--eligible-population-count", type=int)
    parser.add_argument("--bootstrap-resamples", type=int, default=0)
    parser.add_argument("--bootstrap-seed", type=int, default=20260812)
    parser.add_argument(
        "--clock-basis",
        default="legacy_relative_time",
        choices=("legacy_relative_time", "absolute_birth_time"),
    )
    parser.add_argument("--checkpoints", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    args = parser.parse_args()
    spatial_window_profile = None
    if args.spatial_window_profile_id is not None:
        if args.configuration is None:
            parser.error("--spatial-window-profile-id requires --configuration")
        configuration = json.loads(
            args.configuration.read_text(encoding="utf-8-sig")
        )
        matches = [
            profile for profile in configuration.get("spatial_window_profiles", [])
            if profile.get("profile_id") == args.spatial_window_profile_id
        ]
        if len(matches) != 1:
            parser.error("spatial-window profile must resolve exactly once")
        spatial_window_profile = matches[0]
    rows, summary = analyze(
        args.log,
        args.launched,
        args.mass_amu,
        args.geometry,
        args.pulse_time_us,
        args.clock_basis,
        args.batch_particle_count,
        args.initial_global_state,
        spatial_window_profile,
        args.population_denominator_count,
        args.eligible_population_count,
        args.bootstrap_resamples,
        args.bootstrap_seed,
    )
    args.checkpoints.parent.mkdir(parents=True, exist_ok=True)
    with args.checkpoints.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    args.summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"SINGLE_FLIGHT_ANALYSIS=PASS HANDOFF={summary['census']['multipole_handoff']} DETECTOR={summary['census']['detector_crossing']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
