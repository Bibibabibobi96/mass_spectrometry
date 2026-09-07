"""Select a detector-blind pulse time directly from native SIMION TRACE logs.

This is the compact alternative to materializing the complete native-RF state
archive.  It reads the immutable trace only, retains pulse-ranking aggregates,
and writes no trajectory payload.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Iterator

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError, validate_schema
from common.contracts.particle_physics import kinetic_energy_ev
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.select_real_field_pulse_time import (
    _select_source_region_profile,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.materialize_pre_pulse_time_series import (
    TRACE_PATTERN,
    TERMINAL_PATTERN,
    TERMINAL_PREFIX,
    SOURCE_RELEASE_PATTERN,
    resolve_natural_archive_sample_index,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_layout import (
    SELECTION_ORDER,
    _natural_archive_ids,
    select_detector_blind_natural_archive_pulse_time,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source import (
    GLOBAL_COLUMNS,
)


HANDOFF_RECEIPT_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "schemas"
    / "rf_oatof_compact_pre_pulse_handoff_receipt.schema.json"
)


def _load_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"pulse scan input is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"pulse scan input is not an object: {path}")
    return value


def _trace_rows(
    log_paths: list[Path],
    *,
    grid_origin_us: float | None = None,
    grid_step_us: float | None = None,
    token_repairs_out: list[dict[str, object]] | None = None,
) -> Iterator[dict[str, str]]:
    for path in log_paths:
        try:
            with path.open(encoding="utf-8", errors="strict") as handle:
                for raw_line in handle:
                    match = TRACE_PATTERN.fullmatch(raw_line.rstrip("\r\n"))
                    if match is None:
                        if raw_line.startswith("TRACE: pre_pulse_time_series_state "):
                            raise ContractError("compact pulse state TRACE is malformed")
                        continue
                    fields = match.groupdict()
                    sample_index = fields["sample_index"]
                    if grid_origin_us is not None or grid_step_us is not None:
                        if grid_origin_us is None or grid_step_us is None:
                            raise ContractError("compact pulse native-grid identity is incomplete")
                        try:
                            canonical_index, repair = resolve_natural_archive_sample_index(
                                reported_token=sample_index,
                                instrument_time_us=float(fields["instrument_time"]),
                                grid_origin_us=grid_origin_us,
                                grid_step_us=grid_step_us,
                            )
                        except ValueError as exc:
                            raise ContractError("compact pulse state TRACE is malformed") from exc
                        sample_index = str(canonical_index)
                        if repair is not None and token_repairs_out is not None:
                            token_repairs_out.append(repair)
                    yield {
                        "event": "pre_pulse_time_series_state",
                        "survival_status": fields["status"],
                        "particle_id": fields["particle_id"],
                        "sample_index": sample_index,
                        "instrument_time_us": fields["instrument_time"],
                        "actual_instrument_time_us": fields["actual_time"],
                        "x_mm": fields["x"], "y_mm": fields["y"], "z_mm": fields["z"],
                        "vx_mm_per_us": fields["vx"], "vy_mm_per_us": fields["vy"],
                        "vz_mm_per_us": fields["vz"],
                    }
        except (OSError, UnicodeError) as exc:
            raise ContractError(f"pulse scan TRACE is unreadable: {path}") from exc


def _write_selected_handoff(
    *, run_dir: Path, trace_paths: list[Path], sample_index: int,
    pulse_time_us: float, selected_ids: list[int], output_path: Path,
    grid_origin_us: float, grid_step_us: float,
) -> None:
    """Extract only the selected native-RF state into the global restart schema."""
    initial = run_dir / "inputs" / "single_flight_initial_global_state.csv"
    with initial.open(encoding="utf-8-sig", newline="") as handle:
        source_by_id = {int(row["particle_id"]): row for row in csv.DictReader(handle)}
    selected = set(selected_ids)
    state_by_id: dict[int, dict[str, str]] = {}
    for row in _trace_rows(
        trace_paths,
        grid_origin_us=grid_origin_us,
        grid_step_us=grid_step_us,
    ):
        particle_id = int(row["particle_id"])
        if particle_id in selected and int(row["sample_index"]) == sample_index:
            if particle_id in state_by_id:
                raise ContractError("pulse handoff TRACE state is duplicated")
            state_by_id[particle_id] = row
    if sorted(state_by_id) != selected_ids or any(pid not in source_by_id for pid in selected_ids):
        raise ContractError("pulse handoff TRACE cohort differs from the selected cohort")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", delete=False,
            dir=output_path.parent, prefix=f".{output_path.name}.", suffix=".tmp",
        ) as handle:
            temporary_path = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=GLOBAL_COLUMNS, lineterminator="\n")
            writer.writeheader()
            for particle_id in selected_ids:
                source, state = source_by_id[particle_id], state_by_id[particle_id]
                velocity = tuple(float(state[f"v{axis}_mm_per_us"]) * 1e3 for axis in "xyz")
                writer.writerow({
                    "particle_id": particle_id,
                    "instrument_time_us": format(pulse_time_us, ".17g"),
                    "mass_amu": source["mass_amu"],
                    "charge_state": source["charge_state"],
                    "position_x_mm": state["x_mm"], "position_y_mm": state["y_mm"],
                    "position_z_mm": state["z_mm"],
                    **{f"velocity_{axis}_m_s": format(value, ".17g") for axis, value in zip("xyz", velocity, strict=True)},
                    "kinetic_energy_eV": format(kinetic_energy_ev(float(source["mass_amu"]), *velocity), ".17g"),
                })
        os.replace(temporary_path, output_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _binding(path: Path) -> dict[str, object]:
    """Bind the few immutable files needed to reproduce a compact handoff.

    The digests are deliberately limited to the raw TRACE inputs, frozen
    contract, and selected state.  They prevent a later post-pulse run from
    silently consuming a different trajectory; no per-row or derived-value
    hashes are introduced.
    """

    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def _trace_completed(path: Path) -> bool:
    """Check SIMION's terminal marker without re-reading a large TRACE log."""

    try:
        with path.open("rb") as handle:
            handle.seek(max(0, path.stat().st_size - 16 * 1024))
            return b"Fly completed." in handle.read()
    except OSError as exc:
        raise ContractError(f"compact pulse handoff TRACE is unreadable: {path}") from exc


def extract_natural_terminal_states(
    *, trace_paths: list[Path], frozen_particle_ids: list[int], output_path: Path,
) -> dict[str, object]:
    """Retain a terminal or explicitly censored last observation per mother ion.

    Completed continuation logs must collectively observe every canonical ID.
    Missing terminal events remain censored, never invented collisions.
    Repeated terminal events are ambiguous and rejected, even
    when their values agree; callers must not supply overlapping trace inputs.
    """
    frozen = set(frozen_particle_ids)
    if not frozen or len(frozen) != len(frozen_particle_ids):
        raise ContractError("natural terminal mother identity is invalid")
    if not trace_paths or any(not _trace_completed(path) for path in trace_paths):
        raise ContractError("natural terminal TRACE logs are incomplete")
    records: dict[int, dict[str, object]] = {}
    observed: dict[int, dict[str, object]] = {}
    names = ("instrument_time", "x", "y", "z", "vx", "vy", "vz")
    columns = ("instrument_time_us", "x_mm", "y_mm", "z_mm",
               "vx_mm_per_us", "vy_mm_per_us", "vz_mm_per_us")
    for path in trace_paths:
        with path.open(encoding="utf-8", errors="strict") as handle:
            for raw in handle:
                line = raw.rstrip("\r\n")
                if not line.startswith(TERMINAL_PREFIX):
                    state = TRACE_PATTERN.fullmatch(line) or SOURCE_RELEASE_PATTERN.fullmatch(line)
                    if state is None and line.startswith(("TRACE: pre_pulse_time_series_state ", "TRACE: source_release ")):
                        raise ContractError("natural observed TRACE is malformed")
                    if state is not None:
                        particle_id = int(state["particle_id"])
                        if particle_id not in frozen:
                            raise ContractError("natural observed particle identity differs")
                        values = [float(state[name]) for name in names]
                        if not all(math.isfinite(value) for value in values):
                            raise ContractError("natural observed TRACE contains a non-finite number")
                        kind = "source_release" if line.startswith("TRACE: source_release ") else "last_observed_alive"
                        prior = observed.get(particle_id)
                        if prior is None or values[0] >= float(prior["instrument_time_us"]):
                            observed[particle_id] = {
                                "particle_id": particle_id,
                                **dict(zip(columns, (state[name] for name in names), strict=True)),
                                "state_kind": kind, "terminal_reason": "unobserved_terminal",
                            }
                    continue
                match = TERMINAL_PATTERN.fullmatch(line)
                if match is None:
                    raise ContractError("natural terminal TRACE is malformed")
                particle_id = int(match["particle_id"])
                if particle_id not in frozen:
                    raise ContractError("natural terminal particle identity differs")
                if particle_id in records:
                    raise ContractError("natural terminal particle is duplicated")
                if match["reason"] not in {"splat", "geometry_collision", "outside_pa_termination"}:
                    raise ContractError("natural terminal event is not a native termination")
                values = [float(match[name]) for name in names]
                if not all(math.isfinite(value) for value in values):
                    raise ContractError("natural terminal TRACE contains a non-finite number")
                records[particle_id] = {
                    "particle_id": particle_id,
                    **dict(zip(columns, (match[name] for name in names), strict=True)),
                    "terminal_reason": match["reason"],
                    "state_kind": "terminal",
                }
    if set(records) | set(observed) != frozen:
        raise ContractError("natural observation census differs from the frozen cohort")
    unknown = frozen - set(records)
    combined = {**observed, **records}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", delete=False,
            dir=output_path.parent, prefix=f".{output_path.name}.", suffix=".tmp",
        ) as handle:
            temporary_path = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=("particle_id", *columns, "terminal_reason", "state_kind"), lineterminator="\n")
            writer.writeheader()
            writer.writerows(combined[pid] for pid in frozen_particle_ids)
        os.replace(temporary_path, output_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return {
        "mother_population_count": len(frozen),
        "terminal_particle_count": len(records), "complete": not unknown,
        "unknown_terminal_count": len(unknown),
        "accounted_particle_count": len(combined),
        "by_reason": {reason: sum(row["terminal_reason"] == reason for row in records.values())
                      for reason in ("geometry_collision", "splat", "outside_pa_termination")},
        "terminal_state": _binding(output_path),
    }


def pulse_population_partition(*, mother_count: int, alive_count: int, eligible_count: int) -> dict[str, int]:
    """Partition the mother at the selected pulse, not at natural termination."""
    if not 0 < eligible_count <= alive_count <= mother_count:
        raise ContractError("compact pulse population partition is invalid")
    return {"not_observed_alive": mother_count - alive_count,
            "alive_not_eligible": alive_count - eligible_count,
            "eligible": eligible_count}


def _write_receipt(
    *, run_dir: Path, trace_paths: list[Path], result: dict[str, object],
    handoff_path: Path, receipt_path: Path,
) -> None:
    """Publish compact, detector-blind provenance for one selected handoff."""

    if not trace_paths or any(not _trace_completed(path) for path in trace_paths):
        raise ContractError("compact pulse handoff TRACE logs are incomplete")
    selected_ids = result["pulse_eligible_particle_ids"]
    if not isinstance(selected_ids, list) or not selected_ids:
        raise ContractError("compact pulse handoff selection is empty")
    with (run_dir / "inputs" / "single_flight_particle_row_map.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        mother_count = sum(1 for _ in csv.DictReader(handle))
    if mother_count < len(selected_ids):
        raise ContractError("compact pulse handoff mother population is invalid")
    selected_identity = hashlib.sha256(
        json.dumps(selected_ids, separators=(",", ":")).encode("utf-8")
    ).hexdigest().upper()
    receipt = {
        "schema_version": 1,
        "role": "rf_oatof_compact_pre_pulse_trace_handoff_receipt",
        "status": "success",
        "method": "native_trace_detector_blind_pulse_selection_v2",
        "selection_uses_detector_outcome": False,
        "detector_results_used": False,
        "pulse_disabled": True,
        "producer": {
            "screening_contract": _binding(
                run_dir / "inputs" / "pre_pulse_time_series_screening_contract.json"
            ),
            # TRACE files are transient scan inputs: retaining their bindings
            # would make the compact handoff claim a durable multi-GiB
            # trajectory archive.  The selected state and frozen contracts
            # are the downstream authority; a new timing policy reruns the
            # upstream pre-pulse scan explicitly.
            "transient_trace_log_count": len(trace_paths),
            "native_sample_index_repairs": result[
                "native_sample_index_repairs"
            ],
        },
        "selection": {
            "sample_index": result["sample_index"],
            "pulse_effective_time_us": result["selected_time_us"],
            "ballistic_seed_time_us": result["ballistic_seed_time_us"],
            "mother_population_count": mother_count,
            "alive_count": result["alive_count"],
            "pulse_eligible_count": result["pulse_eligible_count"],
            "pulse_eligible_particle_ids": selected_ids,
            # The compact handoff is exactly the detector-blind eligible set;
            # downstream transport may classify losses but must never choose a
            # smaller favourable population.
            "postselection_prohibited": True,
            "pulse_population_partition": result["pulse_population_partition"],
            "ranking": result["ranking"],
        },
        "natural_terminal_census": result["natural_terminal_census"],
        "pulse_target_state": {
            **_binding(handoff_path),
            "particle_count": len(selected_ids),
            "ordered_particle_id_sha256": selected_identity,
            "source_state_epoch": "pulse_effective_time",
            "coordinate_frame": "oatof_global_cartesian",
            "clock_basis": "canonical_instrument_time_us",
            "clock_authority": "detector_blind_native_trace_selection",
            "pulse_effective_time_us": result["selected_time_us"],
        },
        "claim_limit": "DETECTOR_BLIND_PRE_PULSE_HANDOFF_ONLY",
    }
    validate_schema(receipt, HANDOFF_RECEIPT_SCHEMA_PATH)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


def scan(
    run_dir: Path, *, handoff_output: Path | None = None,
    receipt_output: Path | None = None, trace_paths: list[Path] | None = None,
) -> dict[str, object]:
    """Return the best natural-trajectory pulse candidate without state export."""
    run_dir = run_dir.resolve()
    inputs = run_dir / "inputs"
    contract = _load_object(inputs / "pre_pulse_time_series_screening_contract.json")
    grid = contract.get("rf_time_grid")
    identities = contract.get("identities")
    if not isinstance(grid, dict) or not isinstance(identities, dict):
        raise ContractError("pulse scan pre-pulse contract is incomplete")
    if contract.get("schema_version") != 7:
        raise ContractError("compact pulse scan requires natural-archive contract schema 7")
    if contract.get("selection_order") != SELECTION_ORDER:
        raise ContractError("compact pulse scan selection order differs from the frozen contract")
    with (inputs / "single_flight_particle_row_map.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        particle_ids = [
            int(row["source_particle_id"]) for row in csv.DictReader(handle)
        ]
    logs = (
        sorted(path.resolve() for path in trace_paths)
        if trace_paths is not None
        else sorted((run_dir / "logs").glob("simion__batch*.trace.log"))
    )
    if not logs:
        raise ContractError("pulse scan has no SIMION batch TRACE logs")
    geometry = _load_object(inputs / "oatof_resolved_geometry.json")
    configuration = _load_object(inputs / "simion_single_flight.json")
    schedule = _load_object(inputs / "resolved_single_flight_pulse_schedule.json")
    spatial_profile_id = identities.get("spatial_window_profile_id")
    if not isinstance(spatial_profile_id, str):
        raise ContractError("pulse scan spatial profile identity is invalid")
    grid_origin_us = float(grid["grid_origin_us"])
    grid_step_us = float(grid["step_us"])
    token_repairs: list[dict[str, object]] = []
    result = select_detector_blind_natural_archive_pulse_time(
        _trace_rows(
            logs,
            grid_origin_us=grid_origin_us,
            grid_step_us=grid_step_us,
            token_repairs_out=token_repairs,
        ), geometry,
        _select_source_region_profile(configuration, spatial_profile_id),
        frozen_particle_ids=particle_ids,
        ballistic_seed_time_us=float(schedule["pulse_effective_time_us"]),
        grid_origin_us=grid_origin_us,
        grid_step_us=grid_step_us,
        retain_all_candidates=False,
    )
    best = result["candidates_ranked"][0]
    selected_ids = _natural_archive_ids(
        best["_natural_id_masks"]["pulse_eligible_ids"], particle_ids
    )
    if receipt_output is not None and handoff_output is None:
        raise ContractError("compact pulse receipt requires a selected handoff output")
    if handoff_output is not None:
        _write_selected_handoff(
            run_dir=run_dir, trace_paths=logs, sample_index=int(best["sample_index"]),
            pulse_time_us=float(result["selected_time_us"]),
            selected_ids=selected_ids, output_path=handoff_output.resolve(),
            grid_origin_us=grid_origin_us, grid_step_us=grid_step_us,
        )
    compact_result = {
        "selected_time_us": result["selected_time_us"],
        "ballistic_seed_time_us": result["ballistic_seed_time_us"],
        "sample_index": best["sample_index"],
        "alive_count": best["alive_count"],
        "pulse_eligible_count": best["pulse_eligible_count"],
        "transverse_bore_count": best["transverse_bore_count"],
        "source_region_count": best["source_region_count"],
        # Keep the winning score and its physical normalization, not a second
        # trajectory archive. This makes the selected instant auditable after
        # transient TRACE retention has removed the native observations.
        "ranking": {
            "selection_order": result["selection_order"],
            "metric_population_basis": result["metric_population_basis"],
            "normalization_bounds": result["normalization_bounds"],
            **{name: best[name] for name in (
                "normalized_xyz_spread", "normalized_xyz_spread_norm",
                "normalized_xyz_centroid", "normalized_xyz_centroid_distance",
            )},
        },
        "pulse_eligible_particle_ids": selected_ids,
        "native_sample_index_repairs": token_repairs,
        "pulse_population_partition": pulse_population_partition(
            mother_count=len(particle_ids), alive_count=int(best["alive_count"]),
            eligible_count=len(selected_ids),
        ),
    }
    if receipt_output is not None:
        if not len(selected_ids) <= int(best["alive_count"]) <= len(particle_ids):
            raise ContractError("compact pulse population partition is invalid")
        compact_result["natural_terminal_census"] = extract_natural_terminal_states(
            trace_paths=logs, frozen_particle_ids=particle_ids,
            output_path=handoff_output.resolve().parent / "pre_pulse_particle_terminal_states.csv",
        )
        _write_receipt(
            run_dir=run_dir, trace_paths=logs, result=compact_result,
            handoff_path=handoff_output.resolve(), receipt_path=receipt_output.resolve(),
        )
    return compact_result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--handoff-output", type=Path)
    parser.add_argument("--receipt-output", type=Path)
    parser.add_argument("--trace-log", action="append", type=Path,
                        help="Completed TRACE log; repeat for resumed batches.")
    arguments = parser.parse_args()
    result = scan(
        arguments.run_dir, handoff_output=arguments.handoff_output,
        receipt_output=arguments.receipt_output, trace_paths=arguments.trace_log,
    )
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(encoded, encoding="utf-8", newline="\n")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
