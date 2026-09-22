"""Diagnose source-z transfer through one complete MR-TOF flight run.

The analysis is read-only and descriptive.  Safe-exit metrics use the complete
frozen cohort.  Downstream stage metrics use every detector hit with a complete
event chain; terminal losses remain in the accounting and are never filtered
from the source cohort or reclassified as detector hits.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
from typing import Any, Iterable

from common.contracts.particle_physics import kinetic_energy_ev
from common.contracts.verify_run_manifest import record_path, verify_record
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.bunch_source_and_schedule import (
    resolve_bunch_source_interval,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import (
    FLY_COMPLETED,
    _fwhm,
    parse_events,
)


_PROJECT = "parallel_mirror_dual_stripe_mr_tof"
_MODE = "finite_3d_two_prism_voltage_trial"
_CHAIN = (
    ("target_k", "target_k_phase_sample"),
    ("return_p2_entry", "return_p2_entry"),
    ("return_p2_pass", "return_p2_pass"),
    ("return_positive_mirror_turn", "return_positive_mirror_turn"),
    ("detector", "detector"),
)
_SELECTED_EVENT_KINDS = {
    "accelerator_safe_exit", "terminal", "detector_plane",
    "central_plane_directional",
    *(kind for _, kind in _CHAIN),
}

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CandidateContractError(f"{label} is unreadable: {path}") from error
    if not isinstance(value, dict):
        raise CandidateContractError(f"{label} must be an object: {path}")
    return value


def _verify_manifest(manifest: dict[str, Any], manifest_path: Path) -> None:
    try:
        verify_record("run_config", manifest["run_config"], base_dir=manifest_path.parent)
        inputs, outputs = manifest.get("inputs"), manifest.get("outputs")
        if not isinstance(inputs, dict) or not isinstance(outputs, list):
            raise AssertionError("manifest inputs/outputs have invalid containers")
        for name, record in inputs.items():
            verify_record(f"input {name}", record, base_dir=manifest_path.parent)
        for index, record in enumerate(outputs, start=1):
            verify_record(f"output {index}", record, base_dir=manifest_path.parent)
    except (AssertionError, KeyError, TypeError) as error:
        raise CandidateContractError(f"manifest record verification failed: {error}") from error


def _unique_output(manifest: dict[str, Any], path: Path, label: str) -> dict[str, Any]:
    target = path.resolve()
    matches = [
        record for record in manifest.get("outputs", [])
        if isinstance(record, dict) and isinstance(record.get("path"), str)
        and Path(record["path"]).resolve() == target
    ]
    if len(matches) != 1:
        raise CandidateContractError(f"{label} is not a unique manifest output")
    return matches[0]


def _load_source_rows(
    *, run_dir: Path, manifest: dict[str, Any], expected_count: int,
) -> tuple[dict[int, dict[str, float]], dict[str, Any]]:
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict):
        raise CandidateContractError("flight manifest inputs are missing")
    try:
        receipt_path = record_path(inputs["bunch_source_receipt"], base_dir=run_dir)
        source_manifest_path = record_path(inputs["bunch_source_run_manifest"], base_dir=run_dir)
    except (AssertionError, KeyError, TypeError) as error:
        raise CandidateContractError("flight manifest lacks frozen bunch-source inputs") from error
    receipt = _load_object(receipt_path, "bunch-source receipt")
    expected_ids = list(range(1, expected_count + 1))
    expected_ids_sha256 = hashlib.sha256(
        json.dumps(expected_ids, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if (
        receipt.get("role") != "mrtof_deterministic_ideal_bunch_source"
        or receipt.get("status") != "materialized"
    ):
        raise CandidateContractError("source receipt identity differs from the flight run")
    source_manifest = _load_object(source_manifest_path, "bunch-source run manifest")
    if (
        source_manifest.get("project") != _PROJECT
        or source_manifest.get("mode") != "deterministic_bunch_source_materialization"
        or source_manifest.get("status") != "success"
    ):
        raise CandidateContractError("bunch-source run manifest is not successful")
    _verify_manifest(source_manifest, source_manifest_path)
    receipt_matches = [
        record for record in source_manifest.get("outputs", [])
        if isinstance(record, dict)
        and str(record.get("sha256", "")).lower() == _sha256(receipt_path).lower()
        and Path(str(record.get("path", ""))).name == "bunch_source_receipt.json"
    ]
    if len(receipt_matches) != 1:
        raise CandidateContractError("copied source receipt is not uniquely bound to its source run")
    try:
        verify_record("source state table receipt", receipt["state_table"])
        verify_record("source Fly2 receipt", receipt["fly2"])
    except (AssertionError, KeyError, TypeError) as error:
        raise CandidateContractError("bunch-source receipt records failed verification") from error
    state_path = Path(str(receipt["state_table"]["path"])).resolve()
    _unique_output(source_manifest, state_path, "source state table")
    with state_path.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    ids = [int(row["particle_id"]) for row in rows]
    run_config_path = record_path(manifest["run_config"], base_dir=run_dir)
    run_config = _load_object(run_config_path, "flight run config")
    parameters = run_config.get("parameters")
    selection = parameters.get("source_selection") if isinstance(parameters, dict) else None
    if selection is None:
        if (
            receipt.get("particle_count") != expected_count
            or receipt.get("expected_particle_ids") != expected_ids
            or str(receipt.get("expected_particle_ids_sha256", "")).lower()
            != expected_ids_sha256
            or ids != expected_ids
        ):
            raise CandidateContractError(
                "source receipt identity or particle cohort differs from the flight run"
            )
        selected_rows = rows
    else:
        if not isinstance(selection, dict):
            raise CandidateContractError("source selection must be an object")
        try:
            particle_id_min = int(selection["particle_id_min"])
            particle_id_max = int(selection["particle_id_max"])
        except (KeyError, TypeError, ValueError) as error:
            raise CandidateContractError("source selection interval is incomplete") from error
        resolved = resolve_bunch_source_interval(
            receipt_path=receipt_path,
            particle_id_min=particle_id_min,
            particle_id_max=particle_id_max,
        )
        resolved_selection = resolved["source_cohort"]["selection"]
        if (
            len(resolved["particle_ids"]) != expected_count
            or selection != resolved_selection
            or parameters.get("source_cohort") != resolved["source_cohort"]
        ):
            raise CandidateContractError(
                "source selection identity or particle cohort differs from the flight run"
            )
        selected_rows = rows[particle_id_min - 1:particle_id_max]
    parsed: dict[int, dict[str, float]] = {}
    for ion, row in zip(expected_ids, selected_rows, strict=True):
        try:
            values = {name: float(row[name]) for name in ("z_mm", "mass_th")}
        except (KeyError, TypeError, ValueError) as error:
            raise CandidateContractError(f"source state for ion {ion} is incomplete") from error
        if not all(math.isfinite(value) for value in values.values()) or values["mass_th"] <= 0.0:
            raise CandidateContractError(f"source state for ion {ion} is nonphysical")
        parsed[ion] = values
    return parsed, {
        "source_run_manifest": {"path": str(source_manifest_path), "sha256": _sha256(source_manifest_path)},
        "source_state_table": receipt["state_table"],
    }


def _manifest_output_matches(manifest: dict[str, Any], path: Path, sha256: str, label: str) -> None:
    record = _unique_output(manifest, path, label)
    if str(record.get("sha256", "")).lower() != sha256.lower():
        raise CandidateContractError(f"{label} receipt identity differs from the flight manifest")


def _event_batches(
    *, run_dir: Path, manifest: dict[str, Any], particle_count: int,
) -> list[tuple[Path, int, int]]:
    inputs = manifest.get("inputs")
    if isinstance(inputs, dict) and "batch_log_merge_receipt" in inputs:
        receipt_path = record_path(inputs["batch_log_merge_receipt"], base_dir=run_dir)
        receipt = _load_object(receipt_path, "batch-log merge receipt")
        if (
            receipt.get("role") != "mrtof_rebased_batch_log_merge"
            or receipt.get("status") != "success"
            or receipt.get("particle_count") != particle_count
            or receipt.get("global_particle_ids") != [1, particle_count]
            or receipt.get("all_batch_losses_retained") is not True
        ):
            raise CandidateContractError("batch-log merge receipt does not cover the complete cohort")
        batches = receipt.get("batches")
        if not isinstance(batches, list) or not batches:
            raise CandidateContractError("batch-log merge receipt has no batches")
        result: list[tuple[Path, int, int]] = []
        covered: list[int] = []
        for index, batch in enumerate(batches, start=1):
            if not isinstance(batch, dict):
                raise CandidateContractError("batch-log merge receipt has an invalid batch")
            try:
                path = Path(str(batch["path"])).resolve()
                offset, count = int(batch["offset"]), int(batch["count"])
                sha256 = str(batch["sha256"])
            except (KeyError, TypeError, ValueError) as error:
                raise CandidateContractError("batch-log merge receipt has an incomplete batch") from error
            if offset < 0 or count < 1:
                raise CandidateContractError("batch-log offset/count is invalid")
            _manifest_output_matches(manifest, path, sha256, f"native batch log {index}")
            covered.extend(range(offset + 1, offset + count + 1))
            result.append((path, offset, count))
        if covered != list(range(1, particle_count + 1)):
            raise CandidateContractError("batch logs do not cover the cohort exactly once")
        return result
    path = run_dir / "logs" / "native_two_prism_flight.log"
    _unique_output(manifest, path, "merged native flight log")
    return [(path, 0, particle_count)]


def _load_selected_events(
    batches: Iterable[tuple[Path, int, int]],
) -> tuple[dict[tuple[str, int], list[dict[str, Any]]], list[dict[str, Any]]]:
    selected: dict[tuple[str, int], list[dict[str, Any]]] = {}
    evidence: list[dict[str, Any]] = []
    for path, offset, count in batches:
        text = path.read_text(encoding="utf-8-sig")
        completions = list(FLY_COMPLETED.finditer(text))
        if len(completions) != 1 or int(completions[0].group("splats")) != count:
            raise CandidateContractError(f"native log completion differs from its batch plan: {path}")
        for event in parse_events(text):
            local_id = int(event.get("ion", -1))
            if not 1 <= local_id <= count:
                raise CandidateContractError(f"native log event ID is outside its batch: {path}")
            if event["kind"] not in _SELECTED_EVENT_KINDS:
                continue
            event = dict(event)
            event["ion"] = local_id + offset
            selected.setdefault((event["kind"], int(event["ion"])), []).append(event)
        evidence.append({"path": str(path), "sha256": _sha256(path), "offset": offset, "count": count})
    return selected, evidence


def _one(
    events: dict[tuple[str, int], list[dict[str, Any]]], kind: str, ion: int,
) -> dict[str, Any]:
    matches = events.get((kind, ion), [])
    if len(matches) != 1:
        raise CandidateContractError(f"ion {ion} does not have exactly one {kind} event")
    return matches[0]


def _association(xs: list[float], ys: list[float], slope_unit: str) -> dict[str, Any]:
    if len(xs) != len(ys) or len(xs) < 2:
        raise CandidateContractError("diagnostic vectors must contain at least two paired values")
    if not all(math.isfinite(value) for value in (*xs, *ys)):
        raise CandidateContractError("diagnostic vectors contain a non-finite value")
    if min(xs) == max(xs):
        return {
            "status": "invariant_initial_z__association_not_defined",
            "slope": None,
            "slope_unit": slope_unit,
            "pearson_r": None,
            "r_squared": None,
        }
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    variance = sum((value - mx) ** 2 for value in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / variance
    correlation = _pearson(xs, ys)
    return {
        "status": "descriptive_linear_association",
        "slope": slope,
        "slope_unit": slope_unit,
        "pearson_r": correlation,
        "r_squared": None if correlation is None else correlation * correlation,
    }


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Return the descriptive Pearson coefficient for finite paired values."""
    if len(xs) != len(ys) or len(xs) < 3:
        raise CandidateContractError("correlation vectors are incomplete")
    if min(xs) == max(xs) or min(ys) == max(ys):
        return None
    mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
    covariance = sum(
        (x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)
    )
    variance_x = sum((x - mean_x) ** 2 for x in xs)
    variance_y = sum((y - mean_y) ** 2 for y in ys)
    if variance_x == 0.0 or variance_y == 0.0:
        return None
    return covariance / math.sqrt(variance_x * variance_y)


def _distribution(
    xs: list[float], ys: list[float], *, value_unit: str, slope_unit: str,
) -> dict[str, Any]:
    return {
        "sample_count": len(ys),
        "median": statistics.median(ys),
        "value_unit": value_unit,
        "fwhm": _fwhm(ys),
        "range": [min(ys), max(ys)],
        "initial_z_association": _association(xs, ys, slope_unit),
    }


def _event_values(
    events: dict[tuple[str, int], list[dict[str, Any]]],
    kind: str,
    ids: list[int],
    field: str,
) -> list[float]:
    try:
        values = [float(_one(events, kind, ion)[field]) for ion in ids]
    except (KeyError, TypeError, ValueError) as error:
        raise CandidateContractError(f"{kind} lacks finite numeric field {field}") from error
    if not all(math.isfinite(value) for value in values):
        raise CandidateContractError(f"{kind}.{field} contains a non-finite value")
    return values


def _one_terminal_plane_event(
    events: dict[tuple[str, int], list[dict[str, Any]]],
    *,
    ion: int,
    kind: str,
    after_time_us: float,
) -> dict[str, Any]:
    matches = []
    for event in events.get((kind, ion), []):
        if float(event["t_us"]) <= after_time_us:
            continue
        if kind == "detector_plane" and event.get("direction_z") != -1:
            continue
        matches.append(event)
    if len(matches) != 1:
        raise CandidateContractError(
            f"ion {ion} does not have exactly one terminal {kind} event after the positive mirror turn"
        )
    return matches[0]


def _terminal_plane_diagnostic(
    *,
    events: dict[tuple[str, int], list[dict[str, Any]]],
    hit_ids: list[int],
    hit_source_z: list[float],
) -> dict[str, Any]:
    turns = [_one(events, "return_positive_mirror_turn", ion) for ion in hit_ids]
    detector_plane = [
        _one_terminal_plane_event(
            events,
            ion=ion,
            kind="detector_plane",
            after_time_us=float(turn["t_us"]),
        )
        for ion, turn in zip(hit_ids, turns, strict=True)
    ]
    turn_times = [float(event["t_us"]) for event in turns]
    detector_times = [float(event["t_us"]) for event in detector_plane]
    detector_z = [float(event["z_mm"]) for event in detector_plane]
    if max(detector_z) - min(detector_z) > 1e-3:
        raise CandidateContractError("detector diagnostic plane is not a fixed physical z plane")
    actual_detector_z = statistics.median(detector_z)
    return {
        "qualification": (
            "observed_positive_mirror_turn_and_detector_plane__"
            "diagnostic_only__not_detector_relocation_authority"
        ),
        "positive_mirror_turn": {
            "z": _distribution(
                hit_source_z,
                [float(event["z_mm"]) for event in turns],
                value_unit="mm",
                slope_unit="mm/mm",
            ),
            "absolute_time": _distribution(
                hit_source_z, turn_times, value_unit="us", slope_unit="us/mm",
            ),
        },
        "detector_plane": {
            "z_mm": actual_detector_z,
            "absolute_time": _distribution(
                hit_source_z, detector_times, value_unit="us", slope_unit="us/mm",
            ),
            "increment_from_positive_mirror_turn": _distribution(
                hit_source_z,
                [value - start for value, start in zip(detector_times, turn_times, strict=True)],
                value_unit="us",
                slope_unit="us/mm",
            ),
        },
    }


def _central_plane_focus_history(
    *,
    events: dict[tuple[str, int], list[dict[str, Any]]],
    hit_ids: list[int],
    hit_source_z: list[float],
) -> dict[str, Any]:
    groups: dict[tuple[int, int], dict[int, dict[str, Any]]] = {}
    for ion in hit_ids:
        for event in events.get(("central_plane_directional", ion), []):
            identity = (int(event["n"]), int(event["direction_z"]))
            if ion in groups.setdefault(identity, {}):
                raise CandidateContractError(
                    f"ion {ion} has duplicate central-plane identity {identity}"
                )
            groups[identity][ion] = event
    complete = []
    for (index, direction), group in sorted(groups.items()):
        if len(group) != len(hit_ids):
            continue
        times = [float(group[ion]["t_us"]) for ion in hit_ids]
        complete.append({
            "crossing_index": index,
            "direction_z": direction,
            "absolute_time": _distribution(
                hit_source_z, times, value_unit="us", slope_unit="us/mm",
            ),
        })
    if not complete:
        return {
            "status": "unavailable",
            "reason": "no_central_plane_directional_identity_covers_every_detector_hit",
        }
    return {
        "status": "observed",
        "plane_z_mm": 0.0,
        "complete_crossing_count": len(complete),
        "last_complete_crossing": complete[-1],
        "last_ten_complete_crossings": complete[-10:],
        "qualification": (
            "observed_pre_extraction_central_plane_history__supports_but_does_not_replace_"
            "a_transparent_terminal_plane_counterfactual"
        ),
    }


def analyze_source_z_energy_timing(run_dir: Path) -> dict[str, Any]:
    """Validate and analyze one complete N>1 MR-TOF flight run."""
    run_dir = run_dir.resolve()
    manifest_path = run_dir / "run_manifest.json"
    manifest = _load_object(manifest_path, "flight run manifest")
    if (
        manifest.get("project") != _PROJECT or manifest.get("mode") != _MODE
        or manifest.get("status") != "success"
    ):
        raise CandidateContractError("input is not a successful complete MR-TOF flight run")
    _verify_manifest(manifest, manifest_path)
    observation_path = run_dir / "results" / "two_prism_trial_observation.json"
    _unique_output(manifest, observation_path, "flight observation")
    observation = _load_object(observation_path, "flight observation")
    cohort = observation.get("cohort_analysis")
    if not isinstance(cohort, dict) or cohort.get("event_integrity_passed") is not True:
        raise CandidateContractError("flight observation did not pass event integrity")
    try:
        particle_count = int(cohort["expected_particle_count"])
    except (KeyError, TypeError, ValueError) as error:
        raise CandidateContractError("flight observation lacks the expected particle count") from error
    expected_ids = list(range(1, particle_count + 1))
    if particle_count <= 1 or cohort.get("observed_particle_ids") != expected_ids:
        raise CandidateContractError("diagnostic requires one complete ordered N>1 cohort")
    source_rows, source_evidence = _load_source_rows(
        run_dir=run_dir, manifest=manifest, expected_count=particle_count,
    )
    batches = _event_batches(run_dir=run_dir, manifest=manifest, particle_count=particle_count)
    events, log_evidence = _load_selected_events(batches)

    terminal_codes: dict[int, int] = {}
    for ion in expected_ids:
        terminal = _one(events, "terminal", ion)
        code = int(terminal.get("splat", 0))
        if code not in (-1, 1):
            raise CandidateContractError(f"ion {ion} has unsupported terminal class {code}")
        terminal_codes[ion] = code
        _one(events, "accelerator_safe_exit", ion)
    hit_ids = [ion for ion in expected_ids if terminal_codes[ion] == 1]
    loss_ids = [ion for ion in expected_ids if terminal_codes[ion] == -1]
    if len(hit_ids) < 2:
        raise CandidateContractError("at least two detector hits are required for z-transfer metrics")
    if (
        len(loss_ids) != cohort.get("electrode_collision_count")
        or len(hit_ids) != cohort.get("detector_hit_count")
    ):
        raise CandidateContractError("raw terminal classes disagree with the flight observation")
    for ion in hit_ids:
        for _, kind in _CHAIN:
            _one(events, kind, ion)
    for ion in loss_ids:
        for _, kind in _CHAIN:
            if len(events.get((kind, ion), [])) > 1:
                raise CandidateContractError(f"loss ion {ion} has duplicate {kind} events")

    all_source_z = [source_rows[ion]["z_mm"] for ion in expected_ids]
    hit_source_z = [source_rows[ion]["z_mm"] for ion in hit_ids]
    safe_exit_time_all = _event_values(events, "accelerator_safe_exit", expected_ids, "t_us")
    safe_exit_axial_energy_all = [
        kinetic_energy_ev(
            source_rows[ion]["mass_th"], 0.0, 0.0,
            float(_one(events, "accelerator_safe_exit", ion)["vz_mm_us"]) * 1000.0,
        )
        for ion in expected_ids
    ]
    safe_exit_time_hits = _event_values(events, "accelerator_safe_exit", hit_ids, "t_us")

    detector_slope: float | None = None
    stages: dict[str, Any] = {}
    previous_label = "accelerator_safe_exit"
    previous_times = safe_exit_time_hits
    for label, kind in _CHAIN:
        times = _event_values(events, kind, hit_ids, "t_us")
        absolute = _distribution(
            hit_source_z, times, value_unit="us", slope_unit="us/mm",
        )
        increments = [value - previous for value, previous in zip(times, previous_times, strict=True)]
        increment = _distribution(
            hit_source_z, increments, value_unit="us", slope_unit="us/mm",
        )
        stages[label] = {
            "absolute_time": absolute,
            "increment_from_previous_event": {
                "previous_event": previous_label,
                **increment,
            },
        }
        previous_label, previous_times = label, times
        if label == "detector":
            detector_slope = absolute["initial_z_association"]["slope"]
    for stage in stages.values():
        incremental_slope = stage["increment_from_previous_event"]["initial_z_association"]["slope"]
        stage["increment_from_previous_event"]["signed_fraction_of_detector_dt_dz"] = (
            None if detector_slope in (None, 0.0) or incremental_slope is None
            else incremental_slope / detector_slope
        )

    p2_y = _event_values(events, "return_p2_pass", hit_ids, "y_mm")
    p2_vy = _event_values(events, "return_p2_pass", hit_ids, "vy_mm_us")
    p2_vz = _event_values(events, "return_p2_pass", hit_ids, "vz_mm_us")
    p2_angle = [math.degrees(math.atan2(vy, vz)) for vy, vz in zip(p2_vy, p2_vz, strict=True)]
    positive_turn_z = _event_values(events, "return_positive_mirror_turn", hit_ids, "z_mm")
    event_coverage = {
        kind: sum(len(events.get((kind, ion), [])) for ion in expected_ids)
        for kind in sorted(_SELECTED_EVENT_KINDS)
    }
    loss_ids_sha256 = hashlib.sha256(
        json.dumps(loss_ids, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    target_slope = stages["target_k"]["absolute_time"]["initial_z_association"]["slope"]
    downstream_fraction = (
        None if detector_slope in (None, 0.0) or target_slope is None
        else (detector_slope - target_slope) / detector_slope
    )
    terminal_plane_diagnostic = _terminal_plane_diagnostic(
        events=events,
        hit_ids=hit_ids,
        hit_source_z=hit_source_z,
    )
    central_plane_focus_history = _central_plane_focus_history(
        events=events,
        hit_ids=hit_ids,
        hit_source_z=hit_source_z,
    )
    return {
        "schema_version": 1,
        "role": "mrtof_source_z_energy_timing_diagnostic",
        "status": "candidate_diagnostic",
        "qualification": "descriptive_transfer_diagnostic_only__not_causal__not_resolution_qualification",
        "cohort": {
            "particle_count": particle_count,
            "detector_hit_count": len(hit_ids),
            "electrode_collision_count": len(loss_ids),
            "all_terminal_particles_retained": True,
            "loss_particle_ids_sha256": loss_ids_sha256,
            "safe_exit_metric_scope": "all_expected_particles",
            "downstream_metric_scope": "all_detector_hits_with_complete_event_chain",
            "source_or_peak_filtering": "none",
        },
        "safe_exit": {
            "time": _distribution(
                all_source_z, safe_exit_time_all, value_unit="us", slope_unit="us/mm",
            ),
            "axial_kinetic_energy": _distribution(
                all_source_z, safe_exit_axial_energy_all,
                value_unit="eV", slope_unit="eV/mm",
            ),
        },
        "stages": stages,
        "derived_transfer": {
            "fraction_of_detector_dt_dz_accumulated_after_target_k": downstream_fraction,
            "fraction_definition": "(detector absolute dt/dz - target-K absolute dt/dz) / detector absolute dt/dz",
        },
        "terminal_plane_diagnostic": terminal_plane_diagnostic,
        "central_plane_focus_history": central_plane_focus_history,
        "state_dispersion": {
            "return_p2_pass_y": _distribution(
                hit_source_z, p2_y, value_unit="mm", slope_unit="mm/mm",
            ),
            "return_p2_pass_angle": _distribution(
                hit_source_z, p2_angle, value_unit="deg", slope_unit="deg/mm",
            ),
            "return_p2_pass_vz": _distribution(
                hit_source_z, p2_vz, value_unit="mm/us", slope_unit="(mm/us)/mm",
            ),
            "return_positive_mirror_turn_depth": _distribution(
                hit_source_z, positive_turn_z, value_unit="mm", slope_unit="mm/mm",
            ),
        },
        "event_coverage": event_coverage,
        "evidence": {
            "flight_run_manifest": {"path": str(manifest_path), "sha256": _sha256(manifest_path)},
            "flight_observation": {"path": str(observation_path), "sha256": _sha256(observation_path)},
            "native_logs": log_evidence,
            **source_evidence,
        },
        "interpretation": (
            "Slopes, correlations, FWHM values, and signed incremental fractions describe the frozen run only. "
            "They do not identify a unique electrode or authorize source filtering, detrending, or a resolution claim."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze_source_z_energy_timing(args.run_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
