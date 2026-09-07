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


EVENT = re.compile(r"^MRTOF_EVENT\s+(?P<kind>\w+)\s+(?P<fields>.*)$")
FIELD = re.compile(r"(?P<key>[A-Za-z_]+)=(?P<value>[^\s]+)")
FLY_COMPLETED = re.compile(r"^status,Fly completed\.\s+(?P<splats>\d+) splats", re.MULTILINE)
SOURCE_COUNT_KEYS = {
    "center_fly2": "center_particle_count",
    "candidate_bunch_fly2": "candidate_bunch_particle_count",
    "accelerator_focus_center_fly2": "center_particle_count",
    "accelerator_focus_bunch_fly2": "candidate_bunch_particle_count",
    "first_prism_entry_center_fly2": "center_particle_count",
}
ELEMENTARY_CHARGE_C = 1.602176634e-19
ATOMIC_MASS_KG = 1.66053906660e-27
REQUIRED_FIELDS = {
    "turn": {"ion", "n", "t_us", "z_mm"},
    "fast_turn": {"ion", "n", "t_us", "x_mm", "y_mm", "z_mm"},
    "slow_turn": {"ion", "n", "t_us", "x_mm", "y_mm", "z_mm"},
    "p1_plane": {"ion", "n", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us"},
    "p2_to_stripe": {"ion", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us"},
    "stripe_plane": {"ion", "n", "direction_y", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us"},
    "central_plane": {"ion", "n", "t_us", "x_mm", "y_mm"},
    "central_plane_directional": {"ion", "n", "direction_z", "t_us", "x_mm", "y_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us"},
    "detector": {"ion", "t_us", "x_mm", "y_mm", "z_mm"},
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


def _event_error(event: dict[str, Any]) -> str | None:
    kind = event.get("kind")
    if kind not in REQUIRED_FIELDS or not REQUIRED_FIELDS[kind] <= event.keys():
        return "unknown_event_or_missing_fields"
    if any(type(value) not in (float, int) or not math.isfinite(value)
           for key, value in event.items() if key != "kind"):
        return "nonfinite_or_nonnumeric_event_field"
    if not _integer(event["ion"], minimum=1) or event["t_us"] < 0:
        return "invalid_particle_id_or_time"
    for key in ("turns", "central_crossings", "n", "k"):
        if key in event and not _integer(event[key], minimum=0):
            return "invalid_event_counter"
    for key in ("splat", "code"):
        if key in event and not _integer(event[key]):
            return "invalid_splat_code"
    for key in ("direction_y", "direction_z"):
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


def _effective_axial_width_mm(period_us: float, kinetic_energy_ev: float, mass_th: float) -> float:
    """Apply $W=T_0\sqrt{E/(2m)}$ to one full same-direction period."""
    if not all(math.isfinite(value) and value > 0.0 for value in (period_us, kinetic_energy_ev, mass_th)):
        raise ValueError("period, kinetic energy, and mass must be finite positive values")
    return period_us * 1.0e-6 * math.sqrt(
        kinetic_energy_ev * ELEMENTARY_CHARGE_C / (2.0 * mass_th * ATOMIC_MASS_KG)
    ) * 1.0e3


def summarize_events(
    events: list[dict[str, Any]], target_k: int, reported_splat_count: int | None = None,
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
    if not _integer(target_k, minimum=1):
        raise ValueError("target_k must be a positive integer")
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
    expected = set(expected_particle_ids or ())
    observed = {int(event["ion"]) for event in events}
    unknown = sorted(observed - expected) if expected_particle_ids is not None else []
    if unknown:
        errors.append("unknown_particle_ids")
    terminal = [event for event in events if event["kind"] == "terminal"]
    splat_events = [event for event in events if event["kind"] == "splat"]
    duplicates = {}
    for kind in ("terminal", "splat", "detector", "target_k"):
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
    if any(event["k"] != target_k for event in target_k_events):
        errors.append("target_k_event_differs_from_source_contract")
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
        "schema_version": 2,
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
        "target_k_count": sum(value == target_k for value in oscillations),
        "target_k_fraction": (
            sum(value == target_k for value in oscillations) / population_count
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
        "stripe_y0_crossing_count": sum(event["kind"] == "stripe_plane" for event in events),
        "stripe_y0_inbound_crossing_count": sum(
            event["kind"] == "stripe_plane" and event["direction_y"] < 0 for event in events
        ),
        "stripe_y0_outbound_crossing_count": sum(
            event["kind"] == "stripe_plane" and event["direction_y"] > 0 for event in events
        ),
        "P1_plane_crossing_count": sum(event["kind"] == "p1_plane" for event in events),
        "P2_to_Stripe_first_inbound_event_count": sum(event["kind"] == "p2_to_stripe" for event in events),
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
    if manifest.get("schema_version") != 2 or source_key not in SOURCE_COUNT_KEYS:
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
    target_k = contract["nominal"]["target_oscillation_count"]
    if not _integer(target_k, minimum=1):
        raise ValueError("source contract has invalid target oscillation count")
    species = contract.get("particle_source", {}).get("species")
    if not isinstance(species, dict):
        species = None
    elif not all(type(species.get(key)) in (int, float) and math.isfinite(float(species[key])) and float(species[key]) > 0.0
                 for key in ("mass_th", "kinetic_energy_ev")):
        raise ValueError("source contract species mass and kinetic energy must be finite positive values")
    return {"expected_particle_ids": tuple(particle_ids), "target_k": int(target_k), "species": species,
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
                               kinetic_energy_ev=(float(source["species"]["kinetic_energy_ev"]) if source["species"] else None),
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
