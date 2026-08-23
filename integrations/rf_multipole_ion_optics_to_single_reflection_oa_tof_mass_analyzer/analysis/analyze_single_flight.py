"""Extract particle-resolved checkpoints and detector metrics from one SIMION flight."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import csv
import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np

from common.contracts.file_identity import file_sha256
from common.contracts.particle_physics import kinetic_energy_ev
from common.analysis.peak_metrics import (
    bootstrap_resolution_distribution,
    compute_peak_metrics,
)


STATE_PATTERN = re.compile(
    r"TRACE: (?P<event>source_release|single_flight_handoff|pre_pulse_state|accelerator_grid1_forward|accelerator_intermediate2_forward|local_accelerator_exit|accelerator_focus_forward|reflectron_entrance_forward|reflectron_midgrid_forward|reflectron_turning_point|reflectron_exit_return) "
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

RESOLUTION_QUALIFICATION_RESAMPLES = 5000
RESOLUTION_QUALIFICATION_MIN_VALID_RESAMPLES = 4750
RESOLUTION_QUALIFICATION_MAX_RELATIVE_INTERVAL_WIDTH = 0.10


def resolve_analysis_mass_amu(initial_global_state_path: Path) -> float:
    """Return the unique physical mass represented by a frozen state table.

    A single-flight resolution is defined for one ion mass.  The initial state
    table is the frozen particle authority used by the analysis, so a launcher
    must not substitute a separate hard-coded mass.  Mixed masses need an
    explicit target-species contract, which this analysis does not yet model.
    """

    with initial_global_state_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "mass_amu" not in reader.fieldnames:
            raise ValueError("initial global state lacks mass_amu")
        masses: set[float] = set()
        for row in reader:
            try:
                mass = float(row["mass_amu"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("initial global state mass_amu is invalid") from exc
            if not math.isfinite(mass) or mass <= 0:
                raise ValueError("initial global state mass_amu must be positive")
            masses.add(mass)
    if len(masses) != 1:
        raise ValueError(
            "single-flight resolution analysis requires exactly one mass_amu"
        )
    return masses.pop()


def validate_resolution_qualification(summary: dict) -> None:
    """Apply the frozen bootstrap acceptance rule to an analysis summary.

    Python owns interpretation of statistical output; PowerShell only launches
    this analysis and propagates failure.  Constants preserve the pre-existing
    qualification rule exactly.
    """

    records = list(summary.get("full_pulse_eligible_bootstrap") or [])
    spatial_peak = summary.get("spatial_window_peak")
    if isinstance(spatial_peak, dict):
        bootstrap = spatial_peak.get("bootstrap")
        if isinstance(bootstrap, dict):
            records.append(bootstrap)
    if len(records) < 2:
        raise ValueError("resolution qualification requires two bootstrap records")
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("resolution qualification bootstrap record is invalid")
        if (
            record.get("status") != "computed"
            or record.get("resamples_requested") != RESOLUTION_QUALIFICATION_RESAMPLES
            or record.get("resamples_valid", 0) < RESOLUTION_QUALIFICATION_MIN_VALID_RESAMPLES
            or record.get("relative_95pct_interval_width", float("inf"))
            > RESOLUTION_QUALIFICATION_MAX_RELATIVE_INTERVAL_WIDTH
        ):
            raise ValueError("resolution qualification bootstrap acceptance failed")


def validate_three_zone_checkpoint_census(summary: dict) -> None:
    """Apply the frozen three-zone checkpoint-census acceptance rule.

    The census is produced by this analyzer from the particle logs, so its
    physical interpretation belongs here rather than in the orchestration
    wrapper.  This preserves the former PowerShell rule exactly.
    """

    census = summary.get("census")
    if not isinstance(census, dict):
        raise ValueError("three-zone intermediate2 checkpoint census differs")
    event_names = (
        "accelerator_grid1_forward",
        "accelerator_intermediate2_forward",
        "local_accelerator_exit",
        "detector_crossing",
    )
    try:
        launched = int(census["launched"])
        counts = {event_name: int(census[event_name]) for event_name in event_names}
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("three-zone intermediate2 checkpoint census differs") from exc
    if (
        launched < 1
        or counts["accelerator_grid1_forward"] < 1
        or counts["accelerator_intermediate2_forward"] < 1
        or counts["accelerator_grid1_forward"] > launched
        or counts["accelerator_intermediate2_forward"]
        > counts["accelerator_grid1_forward"]
        or counts["local_accelerator_exit"]
        > counts["accelerator_intermediate2_forward"]
        or counts["detector_crossing"] > counts["local_accelerator_exit"]
        or counts["local_accelerator_exit"] < 0
        or counts["detector_crossing"] < 0
    ):
        raise ValueError("three-zone intermediate2 checkpoint census differs")
PULSE_PATTERN = re.compile(
    r"TRACE: handoff_pulse_on(?: ion=(?P<ion>\d+))? "
    r"instrument_time_us=(?P<t>[-+0-9.eE]+)"
)
COLUMNS = [
    "particle_id", "event", "instrument_time_us", "x_mm", "y_mm", "z_mm",
    "vx_mm_per_us", "vy_mm_per_us", "vz_mm_per_us", "kinetic_energy_eV",
    "pulse_eligibility", "pulse_effective_elapsed_us", "survival_status",
    "checkpoint_provenance",
]

POST_FOCUS_EVENTS = (
    "accelerator_focus_forward",
    "reflectron_entrance_forward",
    "reflectron_midgrid_forward",
    "reflectron_turning_point",
    "reflectron_exit_return",
    "detector_crossing",
)


def _ordered_integer_id_sha256(ids: Sequence[int]) -> str:
    payload = json.dumps(list(ids), separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def _observed_id_set(ids: Sequence[int]) -> dict[str, object]:
    """Publish one observed ordered-ID set without making it an input authority."""

    ordered_ids = sorted(set(ids))
    return {
        "ordered_particle_ids": ordered_ids,
        "count": len(ordered_ids),
        "ordered_particle_id_sha256": _ordered_integer_id_sha256(ordered_ids),
    }


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


def _validate_logged_pre_pulse_restart_state(
    rows: list[dict[str, object]],
    initial_rows: list[dict[str, str]],
    ordered_particle_ids: Sequence[int],
    *,
    position_tolerance_mm: float,
    velocity_tolerance_m_per_s: float,
    clock_tolerance_us: float,
    energy_tolerance_eV: float,
) -> bool:
    """Accept one logged restart checkpoint only when it matches frozen state."""
    logged = [row for row in rows if row["event"] == "pre_pulse_state"]
    if not logged:
        return False
    expected_ids = set(ordered_particle_ids)
    logged_by_id = {int(row["particle_id"]): row for row in logged}
    if len(logged_by_id) != len(logged) or set(logged_by_id) != expected_ids:
        raise ValueError("logged pre-pulse restart checkpoints differ from the frozen particle row map")
    initial_by_id = {int(row["particle_id"]): row for row in initial_rows}
    for particle_id in ordered_particle_ids:
        actual = logged_by_id[particle_id]
        expected = initial_by_id[particle_id]
        position_error = max(
            abs(float(actual[f"{axis}_mm"]) - float(expected[f"position_{axis}_mm"]))
            for axis in "xyz"
        )
        velocity_error = max(
            abs(1000.0 * float(actual[f"v{axis}_mm_per_us"]) - float(expected[f"velocity_{axis}_m_s"]))
            for axis in "xyz"
        )
        clock_error = abs(float(actual["instrument_time_us"]) - float(expected["instrument_time_us"]))
        energy_error = abs(
            float(actual["kinetic_energy_eV"]) - float(expected["kinetic_energy_eV"])
        )
        if (
            position_error > position_tolerance_mm
            or velocity_error > velocity_tolerance_m_per_s
            or clock_error > clock_tolerance_us
            or energy_error > energy_tolerance_eV
        ):
            raise ValueError("logged pre-pulse restart checkpoint differs from the frozen pre-pulse state")
        actual["checkpoint_provenance"] = "pre_pulse_restart_logged_canonical_state"
    return True


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
    mass_amu: float,
    population_contract: dict[str, object],
    geometry_path: Path | None = None,
    pulse_time_us: float | None = None,
    clock_basis: str = "canonical_instrument_time_us",
    batch_particle_counts: Sequence[int] | None = None,
    initial_global_state_path: Path | None = None,
    spatial_window_profile: dict[str, object] | None = None,
    initial_global_state_sha256: str | None = None,
    source_run_manifest_path: Path | None = None,
    post_selection_detector_metrics: bool = False,
    restart_position_tolerance_mm: float | None = None,
    restart_velocity_tolerance_m_per_s: float | None = None,
    restart_clock_tolerance_us: float | None = None,
    restart_energy_tolerance_eV: float | None = None,
    restart_validation_contract_sha256: str | None = None,
    particle_row_map_path: Path | None = None,
    source_region_diagnostic_profile: dict[str, object] | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    if population_contract.get("role") != "rf_oatof_resolved_population_contract":
        raise ValueError("resolved population contract identity differs")
    execution_population = population_contract["execution_population"]
    denominators = population_contract["denominators"]
    randomness = population_contract["analysis_randomness"]
    launched = int(execution_population["particle_count"])
    population_denominator_count = int(denominators["population_count"])
    paired_cohort = population_contract.get("paired_cohort_authority")
    cohort_authority_mode = population_contract.get("cohort_authority_mode")
    if cohort_authority_mode == "establish_observed_authority" and paired_cohort is not None:
        raise ValueError("baseline observed authority must not consume a frozen cohort")
    if cohort_authority_mode == "require_frozen_baseline_authority" and paired_cohort is None:
        raise ValueError("paired candidate requires frozen baseline cohort authority")
    eligible_population_count = (
        len(paired_cohort["pulse_eligible"]["ordered_particle_ids"])
        if paired_cohort is not None
        else int(denominators.get("eligible_population_count", launched))
    )
    bootstrap_resamples = int(randomness["bootstrap_resample_count"])
    bootstrap_seed = int(randomness["bootstrap_seed"])
    source_release_mode = str(population_contract["source_release_mode"])
    if clock_basis != "canonical_instrument_time_us":
        raise ValueError("new single-flight analysis requires canonical instrument time")
    if bootstrap_resamples < 0:
        raise ValueError("bootstrap resamples must be non-negative")
    if source_release_mode not in {
        "continuous_frontend", "pre_pulse_restart", "staged_grid2_restart"
    }:
        raise ValueError("unknown single-flight source release mode")
    if particle_row_map_path is None:
        if source_release_mode == "staged_grid2_restart":
            raise ValueError("staged grid2 analysis requires the frozen particle row map")
        ordered_particle_ids = list(range(1, launched + 1))
    else:
        with particle_row_map_path.open(encoding="utf-8-sig", newline="") as handle:
            row_map_reader = csv.DictReader(handle)
            if row_map_reader.fieldnames != [
                "simulation_particle_id", "source_particle_id"
            ]:
                raise ValueError("single-flight particle row-map columns differ")
            row_map_rows = list(row_map_reader)
        if [int(row["simulation_particle_id"]) for row in row_map_rows] != list(
            range(1, launched + 1)
        ):
            raise ValueError("single-flight simulation particle row map is not exact")
        ordered_particle_ids = [int(row["source_particle_id"]) for row in row_map_rows]
    expected_particle_ids = set(ordered_particle_ids)
    if (
        len(ordered_particle_ids) != launched
        or any(value <= 0 for value in ordered_particle_ids)
        or len(expected_particle_ids) != launched
    ):
        raise ValueError("single-flight canonical source particle row map is invalid")
    log_paths = [log_path] if isinstance(log_path, Path) else list(log_path)
    reanalysis_provenance = None
    if source_run_manifest_path is not None:
        manifest = json.loads(source_run_manifest_path.read_text(encoding="utf-8-sig"))
        bound_outputs = {
            str(Path(item["path"]).resolve()): str(item["sha256"]).upper()
            for item in manifest.get("outputs", [])
            if item.get("exists") is True and item.get("sha256")
        }
        log_records = []
        for path in log_paths:
            resolved = str(path.resolve())
            digest = file_sha256(path)
            if bound_outputs.get(resolved) != digest:
                raise ValueError("reanalysis log is not bound by the source run manifest")
            log_records.append({"path": resolved, "sha256": digest})
        reanalysis_provenance = {
            "role": "manifest_bound_single_flight_spatial_reanalysis",
            "source_run_id": manifest["run_id"],
            "source_run_status": manifest["status"],
            "source_run_manifest": {
                "path": str(source_run_manifest_path.resolve()),
                "sha256": file_sha256(source_run_manifest_path),
            },
            "source_logs": log_records,
            "analyzer": {
                "path": str(Path(__file__).resolve()),
                "sha256": file_sha256(Path(__file__)),
            },
            "claim_limit": "detector_blind_spatial_selection_only",
        }
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
                "accelerator_intermediate2_forward": "accelerator_intermediate2_forward",
                "accelerator_focus_forward": "accelerator_focus_forward",
                "reflectron_entrance_forward": "reflectron_entrance_forward",
                "reflectron_midgrid_forward": "reflectron_midgrid_forward",
                "reflectron_turning_point": "reflectron_turning_point",
                "reflectron_exit_return": "reflectron_exit_return",
            }[match["event"]]
            local_id = int(match["ion"])
            if not 1 <= local_id <= batch_count:
                raise ValueError("logged particle identity is outside its batch")
            source_row = local_id + particle_offset
            global_id = ordered_particle_ids[source_row - 1]
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
                "pulse_effective_elapsed_us": (
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
            source_row = local_id + particle_offset
            key = (ordered_particle_ids[source_row - 1], "detector_crossing")
            if key in seen:
                raise ValueError(f"duplicate detector crossing: particle={key[0]}")
            seen.add(key)
            rows.append({
                "particle_id": key[0], "event": key[1],
                "solver_local_elapsed_us": float(match["t"]),
                "instrument_time_us": "",
                "x_mm": float(match["x"]), "y_mm": float(match["y"]), "z_mm": float(match["z"]),
                "vx_mm_per_us": "", "vy_mm_per_us": "", "vz_mm_per_us": "",
                "kinetic_energy_eV": "",
                "pulse_eligibility": "",
                "pulse_effective_elapsed_us": "",
                "survival_status": "detected",
            })
            continue
        match = PULSE_PATTERN.search(line)
        if match:
            pulse_times.append(float(match["t"]))
    pre_pulse_state_provenance = None
    restart_source_release_validation = None
    if initial_global_state_path is not None:
        if source_release_mode in {"pre_pulse_restart", "staged_grid2_restart"}:
            if initial_global_state_sha256 is None:
                raise ValueError("pre-pulse restart analysis requires the manifest-bound initial-state SHA256")
            actual_sha256 = file_sha256(initial_global_state_path)
            if actual_sha256.lower() != initial_global_state_sha256.lower():
                raise ValueError("initial global state SHA256 differs from the manifest-bound identity")
            if source_release_mode == "pre_pulse_restart" and pulse_time_us is None:
                raise ValueError("pre-pulse restart analysis requires the effective pulse time")
        with initial_global_state_path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            initial_rows = list(reader)
        if len(initial_rows) != launched:
            raise ValueError("initial global state row count differs from launched particles")
        if [int(row["particle_id"]) for row in initial_rows] != ordered_particle_ids:
            raise ValueError("initial global state differs from the frozen particle row map")
        traced_release_ids = {
            int(row["particle_id"])
            for row in rows
            if row["event"] == "source_release"
        }
        if source_release_mode in {"pre_pulse_restart", "staged_grid2_restart"}:
            resolved_release_validation = population_contract.get(
                "source_release_validation"
            )
            staged_validation = source_release_mode == "staged_grid2_restart"
            if staged_validation:
                if (
                    population_contract.get("schema_version") != 2
                    or not isinstance(resolved_release_validation, dict)
                    or resolved_release_validation.get("role")
                    != "rf_oatof_resolved_source_release_validation"
                ):
                    raise ValueError(
                        "staged grid2 restart requires resolved population v2 validation"
                    )
                restart_validation_enabled = True
                restart_validation_contract_sha256 = resolved_release_validation[
                    "loader_authorization_budget"
                ]["sha256"]
            else:
                restart_validation_enabled = (
                    restart_validation_contract_sha256 is not None
                )
            if (
                restart_validation_enabled
                and not staged_validation
                and (
                restart_position_tolerance_mm is None
                or restart_velocity_tolerance_m_per_s is None
                or restart_clock_tolerance_us is None
                or restart_energy_tolerance_eV is None
                or not math.isfinite(restart_position_tolerance_mm)
                or not math.isfinite(restart_velocity_tolerance_m_per_s)
                or not math.isfinite(restart_clock_tolerance_us)
                or not math.isfinite(restart_energy_tolerance_eV)
                or restart_position_tolerance_mm <= 0
                or restart_velocity_tolerance_m_per_s <= 0
                or restart_clock_tolerance_us <= 0
                or restart_energy_tolerance_eV <= 0
                )
            ):
                raise ValueError("pre-pulse restart requires positive frozen source-release tolerances")
            if restart_validation_enabled and traced_release_ids != expected_particle_ids:
                raise ValueError("restart requires actual source_release checkpoints for every particle")
            traced_by_id = {
                int(row["particle_id"]): row
                for row in rows if row["event"] == "source_release"
            }
            maximum_position_error = 0.0
            maximum_velocity_error = 0.0
            maximum_clock_error = 0.0
            maximum_energy_error = 0.0
            maximum_velocity_relative_to_speed = 0.0
            maximum_energy_relative = 0.0
            exact_position_passed = True
            exact_clock_passed = True
            for initial in (initial_rows if restart_validation_enabled else []):
                particle_id = int(initial["particle_id"])
                actual = traced_by_id[particle_id]
                position_error = max(
                    abs(float(actual[f"{axis}_mm"]) - float(initial[f"position_{axis}_mm"]))
                    for axis in "xyz"
                )
                velocity_error = max(
                    abs(1000.0 * float(actual[f"v{axis}_mm_per_us"]) - float(initial[f"velocity_{axis}_m_s"]))
                    for axis in "xyz"
                )
                clock_error = abs(
                    float(actual["instrument_time_us"])
                    - float(initial["instrument_time_us"])
                )
                energy_error = abs(
                    kinetic_energy_ev(
                        float(initial["mass_amu"]),
                        *(1000.0 * float(actual[f"v{axis}_mm_per_us"]) for axis in "xyz"),
                    ) - float(initial["kinetic_energy_eV"])
                )
                expected_velocity = tuple(
                    float(initial[f"velocity_{axis}_m_s"]) for axis in "xyz"
                )
                expected_speed = math.sqrt(sum(
                    value * value for value in expected_velocity
                ))
                expected_energy = float(initial["kinetic_energy_eV"])
                velocity_relative = (
                    velocity_error / expected_speed
                    if expected_speed > 0 else 0.0
                )
                energy_relative = (
                    energy_error / expected_energy
                    if expected_energy > 0 else 0.0
                )
                maximum_position_error = max(maximum_position_error, position_error)
                maximum_velocity_error = max(maximum_velocity_error, velocity_error)
                maximum_clock_error = max(maximum_clock_error, clock_error)
                maximum_energy_error = max(maximum_energy_error, energy_error)
                maximum_velocity_relative_to_speed = max(
                    maximum_velocity_relative_to_speed, velocity_relative
                )
                maximum_energy_relative = max(
                    maximum_energy_relative, energy_relative
                )
                exact_position_passed = exact_position_passed and position_error == 0
                exact_clock_passed = exact_clock_passed and clock_error == 0
                if staged_validation:
                    velocity_contract = resolved_release_validation["velocity"]
                    energy_contract = resolved_release_validation["derived_energy"]
                    actual_velocity = tuple(
                        1000.0 * float(actual[f"v{axis}_mm_per_us"])
                        for axis in "xyz"
                    )
                    velocity_passed = (
                        actual_velocity == (0.0, 0.0, 0.0)
                        if expected_speed == 0
                        else velocity_error
                        <= float(velocity_contract["relative_bound"]) * expected_speed
                    )
                    energy_passed = (
                        energy_error == 0
                        if expected_energy == 0
                        else energy_error
                        <= float(energy_contract["relative_bound"]) * expected_energy
                    )
                    if not (
                        position_error == 0
                        and clock_error == 0
                        and velocity_passed
                        and energy_passed
                    ):
                        raise ValueError(
                            "actual source_release checkpoint differs from the "
                            "resolved loader-characterized contract"
                        )
            if (
                restart_validation_enabled
                and not staged_validation
                and (
                maximum_position_error > restart_position_tolerance_mm
                or maximum_velocity_error > restart_velocity_tolerance_m_per_s
                or maximum_clock_error > restart_clock_tolerance_us
                or maximum_energy_error > restart_energy_tolerance_eV
                )
            ):
                raise ValueError("actual source_release checkpoint differs from the frozen pre-pulse state")
            restart_source_release_validation = ({
                "status": "PASS",
                "checkpoint": "source_release",
                "particle_count": launched,
                "validation_contract_sha256": restart_validation_contract_sha256,
                "ordered_particle_ids_exact": True,
                "identity_position_clock_policy": (
                    "ordered_id_row_map_position_clock_exact"
                    if staged_validation else "legacy_absolute_tolerances"
                ),
                "position_exact_passed": exact_position_passed,
                "clock_exact_passed": exact_clock_passed,
                "position_rowwise_abs_tolerance_mm": (
                    None if staged_validation else restart_position_tolerance_mm
                ),
                "velocity_rowwise_abs_tolerance_m_per_s": (
                    None if staged_validation else restart_velocity_tolerance_m_per_s
                ),
                "velocity_relative_to_expected_speed_bound": (
                    resolved_release_validation["velocity"]["relative_bound"]
                    if staged_validation else None
                ),
                "clock_abs_tolerance_us": (
                    None if staged_validation else restart_clock_tolerance_us
                ),
                "energy_abs_tolerance_eV": (
                    None if staged_validation else restart_energy_tolerance_eV
                ),
                "derived_energy_relative_to_expected_energy_bound": (
                    resolved_release_validation["derived_energy"]["relative_bound"]
                    if staged_validation else None
                ),
                "maximum_position_rowwise_abs_error_mm": maximum_position_error,
                "maximum_velocity_rowwise_abs_error_m_per_s": maximum_velocity_error,
                "maximum_velocity_relative_to_expected_speed":
                    maximum_velocity_relative_to_speed,
                "maximum_clock_abs_error_us": maximum_clock_error,
                "maximum_energy_abs_error_eV": maximum_energy_error,
                "maximum_energy_relative_to_expected_energy": maximum_energy_relative,
                "native_ion_ke_role": (
                    resolved_release_validation["native_ion_ke_role"]
                    if staged_validation else None
                ),
            } if restart_validation_enabled else None)
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
                "pulse_effective_elapsed_us": "",
                "survival_status": "alive",
            })
        if source_release_mode == "pre_pulse_restart":
            if any(abs(float(row["instrument_time_us"]) - pulse_time_us) > 1e-9 for row in initial_rows):
                raise ValueError("pre-pulse restart initial-state clock differs from the pulse time")
            has_logged_checkpoint = any(
                row["event"] == "pre_pulse_state" for row in rows
            )
            if has_logged_checkpoint:
                if not restart_validation_enabled:
                    raise ValueError(
                        "logged pre-pulse restart checkpoints require frozen "
                        "source-release validation"
                    )
                _validate_logged_pre_pulse_restart_state(
                    rows,
                    initial_rows,
                    ordered_particle_ids,
                    position_tolerance_mm=restart_position_tolerance_mm,
                    velocity_tolerance_m_per_s=restart_velocity_tolerance_m_per_s,
                    clock_tolerance_us=restart_clock_tolerance_us,
                    energy_tolerance_eV=restart_energy_tolerance_eV,
                )
                pre_pulse_state_provenance = "pre_pulse_restart_logged_canonical_state"
            else:
                release_by_id = {
                    int(row["particle_id"]): row
                    for row in rows if row["event"] == "source_release"
                }
                for particle_id in ordered_particle_ids:
                    state = release_by_id[particle_id]
                    rows.append({
                        **state,
                        "event": "pre_pulse_state",
                        "pulse_effective_elapsed_us": 0.0,
                        "checkpoint_provenance": "pre_pulse_restart_initial_global_state",
                    })
                pre_pulse_state_provenance = "pre_pulse_restart_initial_global_state"
    rows.sort(key=lambda row: (int(row["particle_id"]), str(row["event"])))
    _validate_reflectron_event_order(rows)
    counts = {event: sum(row["event"] == event for row in rows) for event in (
        "source_release", "multipole_handoff", "pre_pulse_state",
        "accelerator_grid1_forward", "accelerator_intermediate2_forward",
        "local_accelerator_exit", "accelerator_focus_forward",
        "reflectron_entrance_forward", "reflectron_midgrid_forward",
        "reflectron_turning_point", "reflectron_exit_return", "detector_crossing",
    )}
    if launched < 1 or any(int(row["particle_id"]) not in expected_particle_ids for row in rows):
        raise ValueError("logged particle identity is outside the launched mother sample")
    effective_pulse_time_us = _resolve_pulse_time_us(pulse_time_us, pulse_times)
    detector_rows = [row for row in rows if row["event"] == "detector_crossing"]
    birth_times = {
        int(row["particle_id"]): float(row["instrument_time_us"])
        for row in rows if row["event"] == "source_release"
    }
    for row in detector_rows:
        particle_id = int(row["particle_id"])
        if particle_id not in birth_times:
            raise ValueError("detector canonical clock lacks source birth authority")
        row["instrument_time_us"] = (
            birth_times[particle_id] + float(row.pop("solver_local_elapsed_us"))
        )
    for row in rows:
        if effective_pulse_time_us is not None:
            computed = float(row["instrument_time_us"]) - effective_pulse_time_us
            reported = row["pulse_effective_elapsed_us"]
            if reported != "" and abs(float(reported) - computed) > 1e-8:
                raise ValueError("logged pulse-effective checkpoint time is inconsistent")
            row["pulse_effective_elapsed_us"] = computed
    injection_energy_validation = None
    pulse_capture = None
    geometry = None
    if geometry_path is not None:
        geometry = json.loads(geometry_path.read_text(encoding="utf-8-sig"))
    if geometry is not None and source_release_mode != "staged_grid2_restart":
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
        # This analyzer reports what this transport actually observed.  The
        # result registrar decides, from pulse_resolution_execution_mode,
        # whether those IDs establish a baseline authority or must reuse one.
        eligible_population_count = len(eligible_ids)
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
                binding = specification.get("center_binding")
                source_binding = f"particle_source.center_{axis}_mm"
                accelerator_binding = f"coordinate_convention.accelerator_axis_{axis}"
                if binding == source_binding:
                    center = float(geometry["particle_source"][f"center_{axis}_mm"])
                elif binding == accelerator_binding and axis in {"x", "y"}:
                    center = float(
                        geometry["coordinate_convention"].get(
                            f"accelerator_axis_{axis}", 0.0
                        )
                    )
                else:
                    raise ValueError("spatial-window center binding is invalid")
                expected_binding = str(binding)
                width_binding = specification.get("full_width_binding")
                if width_binding == "geometry_mm.accelerator_bore_diameter":
                    width = 2.0 * float(geometry["geometry_mm"]["accelerator_bore_half"])
                elif width_binding is None:
                    width = float(specification["full_width_mm"])
                else:
                    raise ValueError("spatial-window width binding is invalid")
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
        population_basis = str(
            spatial_window_profile.get("population_basis", "pulse_eligible")
        )
        if population_basis not in {"pulse_eligible", "all_event_particles"}:
            raise ValueError("spatial-window population basis is invalid")
        event_rows = [
            row for row in rows
            if row["event"] == event
            and (
                population_basis == "all_event_particles"
                or int(row["particle_id"]) in pulse_eligible_ids
            )
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
        transverse_axes = [axis for axis in ("x", "y") if axis in bounds]
        selected_event_rows = [
            row for row in event_rows if int(row["particle_id"]) in selected_ids
        ]
        selection_metrics = None
        if transverse_axes and selected_event_rows:
            centroid_terms = []
            for axis in transverse_axes:
                bound = bounds[axis]
                centroid = float(np.mean([
                    float(row[f"{axis}_mm"]) for row in selected_event_rows
                ]))
                half_width = float(bound["full_width_mm"]) / 2.0
                centroid_terms.append(
                    ((centroid - float(bound["center_mm"])) / half_width) ** 2
                )
            margins = np.asarray([
                min(
                    min(
                        float(row[f"{axis}_mm"]) - float(bounds[axis]["minimum_mm"]),
                        float(bounds[axis]["maximum_mm"]) - float(row[f"{axis}_mm"]),
                    ) / (float(bounds[axis]["full_width_mm"]) / 2.0)
                    for axis in transverse_axes
                )
                for row in selected_event_rows
            ])
            selection_metrics = {
                "population_basis": population_basis,
                "accepted_count": len(selected_ids),
                "normalized_2d_centroid_distance": float(np.sqrt(sum(centroid_terms))),
                "minimum_normalized_edge_margin": float(np.min(margins)),
                "normalized_edge_margin_quantile": 0.05,
                "quantile_normalized_edge_margin": float(np.quantile(margins, 0.05)),
                "detector_results_used": False,
            }
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
            "population_basis": population_basis,
            "selected_count": len(selected_ids),
            "pulse_eligible_coverage_fraction": coverage,
            "selected_fraction_of_event_population": (
                len(selected_ids) / len(event_rows) if event_rows else None
            ),
            "is_causal_counterfactual": False,
            "detector_blind_selection_metrics": selection_metrics,
        }
    observed_cohort_ids = {
        "source_release": sorted({
            int(row["particle_id"])
            for row in rows if row["event"] == "source_release"
        }),
        "pre_pulse_state": sorted({
            int(row["particle_id"])
            for row in rows if row["event"] == "pre_pulse_state"
        }),
        "pulse_eligible": sorted({
            int(row["particle_id"])
            for row in rows
            if row["event"] == "pre_pulse_state"
            and row["pulse_eligibility"] == "eligible"
        }),
        "outside_transverse_bore": sorted({
            int(row["particle_id"])
            for row in rows
            if row["event"] == "pre_pulse_state"
            and row["pulse_eligibility"] == "outside_transverse_bore"
        }),
    }
    observed_cohort_authority = {
        "role": "rf_oatof_observed_paired_cohort_authority",
        **{
            name: _observed_id_set(ids)
            for name, ids in observed_cohort_ids.items()
        },
    }
    observed_handoff = _observed_id_set([
        int(row["particle_id"])
        for row in rows if row["event"] == "multipole_handoff"
    ])
    full_candidate_population_simulated = launched == population_denominator_count
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
    if geometry is None or source_release_mode == "staged_grid2_restart":
        eligible_ids = expected_particle_ids
    source_region_diagnostic = None
    if source_region_diagnostic_profile is not None:
        if geometry is None:
            raise ValueError("source-region diagnostic requires resolved geometry")
        profile = source_region_diagnostic_profile
        axes = profile.get("axes")
        if (
            profile.get("role") != "layout_resolved_source_region_diagnostic"
            or profile.get("claim_status") != "PROVISIONAL_DIAGNOSTIC_ONLY"
            or profile.get("event") != "pre_pulse_state"
            or profile.get("population_basis") != "pulse_eligible"
            or profile.get("selection_uses_detector_outcome") is not False
            or not isinstance(axes, dict)
            or set(axes) != {"x", "y", "z"}
        ):
            raise ValueError("source-region diagnostic profile identity differs")
        bounds: dict[str, dict[str, float | str]] = {}
        for axis in ("x", "y", "z"):
            specification = axes[axis]
            if (
                not isinstance(specification, dict)
                or specification.get("center_binding")
                != f"particle_source.center_{axis}_mm"
            ):
                raise ValueError("source-region diagnostic axis binding differs")
            center = float(geometry["particle_source"][f"center_{axis}_mm"])
            if axis == "z":
                if specification.get("full_width_binding") != (
                    "particle_source.size_z_mm"
                ):
                    raise ValueError(
                        "source-region diagnostic axial width binding differs"
                    )
                width = float(geometry["particle_source"]["size_z_mm"])
            else:
                if specification.get("full_width_binding") is not None:
                    raise ValueError(
                        "source-region diagnostic transverse width binding differs"
                    )
                width = float(specification.get("full_width_mm", 0.0))
            if width <= 0:
                raise ValueError("source-region diagnostic width must be positive")
            bounds[axis] = {
                "center_binding": str(specification["center_binding"]),
                "center_mm": center,
                "full_width_binding": specification.get("full_width_binding"),
                "full_width_mm": width,
                "minimum_mm": center - width / 2.0,
                "maximum_mm": center + width / 2.0,
            }
        eligible_event_rows = [
            row for row in rows
            if row["event"] == "pre_pulse_state"
            and int(row["particle_id"]) in eligible_ids
        ]
        selected_ids = sorted({
            int(row["particle_id"])
            for row in eligible_event_rows
            if all(
                float(bounds[axis]["minimum_mm"])
                <= float(row[f"{axis}_mm"])
                <= float(bounds[axis]["maximum_mm"])
                for axis in ("x", "y", "z")
            )
        })
        selected_id_set = set(selected_ids)
        selected_detector_rows = [
            row for row in detector_rows
            if int(row["particle_id"]) in selected_id_set
        ]
        detected_ids = sorted({
            int(row["particle_id"]) for row in selected_detector_rows
        })
        if effective_pulse_time_us is None:
            source_region_peak = None
            source_region_bootstrap = {
                "resamples_requested": bootstrap_resamples,
                "seed": bootstrap_seed,
                "status": "not_computed",
                "reason": "pulse_effective_time_unavailable",
            }
        else:
            source_region_peak, source_region_bootstrap = _peak_summary(
                np.asarray([
                    float(row["pulse_effective_elapsed_us"])
                    for row in selected_detector_rows
                ], dtype=float),
                mass_amu,
                bootstrap_resamples=bootstrap_resamples,
                bootstrap_seed=bootstrap_seed,
            )
        source_region_diagnostic = {
            "profile_id": profile["profile_id"],
            "role": profile["role"],
            "claim_status": profile["claim_status"],
            "qualification_eligible": False,
            "event": profile["event"],
            "population_basis": profile["population_basis"],
            "selection_uses_detector_outcome": False,
            "bounds": bounds,
            "eligible_particle_ids": sorted(eligible_ids),
            "eligible_count": len(eligible_ids),
            "selected_particle_ids": selected_ids,
            "selected_count": len(selected_ids),
            "detected_particle_ids": detected_ids,
            "detected_count": len(detected_ids),
            "occupancy_fraction": (
                len(selected_ids) / len(eligible_ids) if eligible_ids else None
            ),
            "pulse_effective_peak": source_region_peak,
            "peak_status": (
                "computed" if source_region_peak is not None else "not_computed"
            ),
            "peak_reason": (
                None if source_region_peak is not None
                else source_region_bootstrap.get("reason")
            ),
            "bootstrap": source_region_bootstrap,
        }
    eligible_detector_tof = np.asarray(
        [
            float(row["pulse_effective_elapsed_us"])
            for row in detector_rows
            if int(row["particle_id"]) in eligible_ids
        ],
        dtype=float,
    ) if effective_pulse_time_us is not None else np.asarray([], dtype=float)
    detector_blind_spatial_selection = (
        spatial_window_profile is not None and not post_selection_detector_metrics
    )
    frozen_eligible_complete = (
        paired_cohort is None
        or eligible_ids.issubset({int(row["particle_id"]) for row in detector_rows})
    )
    if detector_blind_spatial_selection or not frozen_eligible_complete:
        pulse_effective_peak = None
        full_bootstrap = None
    else:
        pulse_effective_peak, full_bootstrap = _peak_summary(
            eligible_detector_tof,
            mass_amu,
            bootstrap_resamples=bootstrap_resamples,
            bootstrap_seed=bootstrap_seed,
        )
    segment_diagnostics = _segment_diagnostics(rows, eligible_ids)
    detected_eligible_count = len(
        eligible_ids & {int(row["particle_id"]) for row in detector_rows}
    )
    complete_eligible_population_simulated = (
        full_candidate_population_simulated
        or (
            launched == eligible_population_count
            and eligible_ids == expected_particle_ids
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
        "observed_cohort_authority": observed_cohort_authority,
        "observed_handoff": observed_handoff,
        "pulse_first_observed_us": min(pulse_times) if pulse_times else None,
        "pulse_effective_time_us": effective_pulse_time_us,
        "clock_basis": clock_basis,
        "analysis_scope": (
            "downstream_only_from_local_accelerator_exit"
            if source_release_mode == "staged_grid2_restart"
            else "full_single_flight_with_pulse_eligibility"
        ),
        "pulse_eligibility_validation_applied": (
            source_release_mode != "staged_grid2_restart"
        ),
        "injection_energy_validation_applied": (
            geometry is not None and source_release_mode != "staged_grid2_restart"
        ),
        "resolution_time_basis": (
            None
            if source_release_mode == "staged_grid2_restart"
            else "detector_time_minus_pulse_effective_time"
        ),
        "pulse_effective_peak": pulse_effective_peak,
        "full_pulse_eligible_bootstrap": full_bootstrap,
        "detector_clock_diagnostic": {
            "basis": (
                "canonical_instrument_time_us"
                if source_release_mode == "staged_grid2_restart"
                else "detector_time_minus_pulse_effective_time"
            ),
            "sample_count": (
                len(detector_rows)
                if source_release_mode == "staged_grid2_restart"
                else int(eligible_detector_tof.size)
            ),
            "nonpositive_count": (
                None
                if source_release_mode == "staged_grid2_restart"
                else int(np.count_nonzero(eligible_detector_tof <= 0))
            ),
            "used_for_spatial_selection": False,
            "peak_metrics_computed": (
                source_release_mode != "staged_grid2_restart"
                and not detector_blind_spatial_selection
            ),
        },
        "reanalysis_provenance": reanalysis_provenance,
        "detector_time_basis": "canonical_instrument_time_us",
        "detector_pulse_effective_time_basis": "pulse_effective_elapsed_us",
        "pre_pulse_state_provenance": pre_pulse_state_provenance,
        "pre_pulse_restart_source_release_validation": (
            restart_source_release_validation
            if source_release_mode == "pre_pulse_restart" else None
        ),
        "staged_grid2_restart_source_release_validation": (
            restart_source_release_validation
            if source_release_mode == "staged_grid2_restart" else None
        ),
        "particle_row_map": {
            "path": str(particle_row_map_path) if particle_row_map_path else None,
            "sha256": file_sha256(particle_row_map_path) if particle_row_map_path else None,
            "simulation_rows": launched,
            "canonical_source_ids_are_contiguous": ordered_particle_ids
            == list(range(1, launched + 1)),
        },
        "injection_energy_validation": injection_energy_validation,
        "pulse_capture": pulse_capture,
        "spatial_window_peak": spatial_window_peak,
        "source_region_diagnostic": source_region_diagnostic,
        "post_focus_common_cohort": segment_diagnostics,
        "spatial_six_panel": "results/single_flight_spatial_six_panel.png",
        "formal_gate_passed": False,
    }
    return rows, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", required=True, action="append", type=Path)
    parser.add_argument("--batch-particle-count", action="append", type=int)
    parser.add_argument("--mass-amu", type=float)
    parser.add_argument("--resolved-population-contract", required=True, type=Path)
    parser.add_argument("--resolved-population-contract-sha256", required=True)
    parser.add_argument("--geometry", type=Path)
    parser.add_argument("--pulse-time-us", type=float)
    parser.add_argument("--initial-global-state", type=Path)
    parser.add_argument("--initial-global-state-sha256")
    parser.add_argument("--particle-row-map", required=True, type=Path)
    parser.add_argument("--restart-position-tolerance-mm", type=float)
    parser.add_argument("--restart-velocity-tolerance-m-per-s", type=float)
    parser.add_argument("--restart-clock-tolerance-us", type=float)
    parser.add_argument("--restart-energy-tolerance-eV", type=float)
    parser.add_argument("--restart-validation-contract-sha256")
    parser.add_argument("--source-run-manifest", type=Path)
    parser.add_argument("--post-selection-detector-metrics", action="store_true")
    parser.add_argument("--configuration", type=Path)
    parser.add_argument("--spatial-window-profile-id")
    parser.add_argument("--source-region-diagnostic-profile-id")
    parser.add_argument(
        "--clock-basis",
        default="canonical_instrument_time_us",
        choices=("canonical_instrument_time_us",),
    )
    parser.add_argument("--checkpoints", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--require-resolution-qualification", action="store_true")
    parser.add_argument("--require-three-zone-checkpoint-census", action="store_true")
    args = parser.parse_args()
    if file_sha256(args.resolved_population_contract) != \
            args.resolved_population_contract_sha256:
        parser.error("resolved population contract SHA differs")
    population_contract = json.loads(
        args.resolved_population_contract.read_text(encoding="utf-8-sig")
    )
    if args.initial_global_state is None:
        parser.error("initial-global-state is required to resolve analysis mass")
    try:
        resolved_mass_amu = resolve_analysis_mass_amu(args.initial_global_state)
    except ValueError as exc:
        parser.error(str(exc))
    if args.mass_amu is not None and not math.isclose(
        args.mass_amu, resolved_mass_amu, rel_tol=0.0, abs_tol=0.0
    ):
        parser.error("mass-amu differs from frozen initial global state")
    args.mass_amu = resolved_mass_amu
    configuration = None
    if (
        args.spatial_window_profile_id is not None
        or args.source_region_diagnostic_profile_id is not None
    ):
        if args.configuration is None:
            parser.error("profile selection requires --configuration")
        configuration = json.loads(
            args.configuration.read_text(encoding="utf-8-sig")
        )
    spatial_window_profile = None
    if args.spatial_window_profile_id is not None:
        assert configuration is not None
        matches = [
            profile for profile in configuration.get("spatial_window_profiles", [])
            if profile.get("profile_id") == args.spatial_window_profile_id
        ]
        if len(matches) != 1:
            parser.error("spatial-window profile must resolve exactly once")
        spatial_window_profile = matches[0]
    source_region_diagnostic_profile = None
    if args.source_region_diagnostic_profile_id is not None:
        assert configuration is not None
        matches = [
            profile
            for profile in configuration.get(
                "source_region_diagnostic_profiles", []
            )
            if profile.get("profile_id")
            == args.source_region_diagnostic_profile_id
        ]
        if len(matches) != 1:
            parser.error(
                "source-region diagnostic profile must resolve exactly once"
            )
        source_region_diagnostic_profile = matches[0]
    rows, summary = analyze(
        args.log,
        args.mass_amu,
        population_contract,
        args.geometry,
        args.pulse_time_us,
        args.clock_basis,
        args.batch_particle_count,
        args.initial_global_state,
        spatial_window_profile,
        args.initial_global_state_sha256,
        args.source_run_manifest,
        args.post_selection_detector_metrics,
        args.restart_position_tolerance_mm,
        args.restart_velocity_tolerance_m_per_s,
        args.restart_clock_tolerance_us,
        args.restart_energy_tolerance_eV,
        args.restart_validation_contract_sha256,
        args.particle_row_map,
        source_region_diagnostic_profile,
    )
    args.checkpoints.parent.mkdir(parents=True, exist_ok=True)
    with args.checkpoints.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    args.summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    if args.require_resolution_qualification:
        validate_resolution_qualification(summary)
    if args.require_three_zone_checkpoint_census:
        validate_three_zone_checkpoint_census(summary)
    print(f"SINGLE_FLIGHT_ANALYSIS=PASS HANDOFF={summary['census']['multipole_handoff']} DETECTOR={summary['census']['detector_crossing']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
