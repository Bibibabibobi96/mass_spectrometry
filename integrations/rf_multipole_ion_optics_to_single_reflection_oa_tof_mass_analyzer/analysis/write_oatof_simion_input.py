"""Write validated oaTOF SIMION inputs from canonical oatof_global state."""

from __future__ import annotations

import argparse
import csv
import json
import math
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from common.contracts.component_particle_state import (
    csv_columns,
    validate_component_particle_state_csv,
)
from common.contracts.file_identity import file_sha256
from projects.single_reflection_oa_tof_mass_analyzer.analysis.rf_handoff_adapter import (
    encode_simion_accelerator_velocity,
    ordered_solver_identity_map,
    validate_ion_velocity_adapter,
)


EXPECTED_FRAME_ID = "oatof_global"
ROW_MAP_COLUMNS = [
    "solver_row_index",
    "particle_id",
    "instrument_time_us",
    "lineage_age_us",
    "particle_age_us",
    "solver_birth_time_us",
    "azimuth_deg",
    "elevation_deg",
]


def _reference(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "sha256": file_sha256(path),
        "bytes": path.stat().st_size,
    }


def _read_exact_csv(
    path: Path,
    columns: Sequence[str],
    label: str,
) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != list(columns):
            raise ValueError(f"{label} columns differ from the required schema")
        rows = list(reader)
    if not rows:
        raise ValueError(f"{label} must contain at least one row")
    return rows


def _derived_solver_rows(
    canonical_rows: Sequence[Mapping[str, str]],
) -> tuple[list[list[str]], list[dict[str, object]]]:
    ion_rows: list[list[str]] = []
    row_map_rows: list[dict[str, object]] = []
    for solver_row, state in enumerate(canonical_rows, start=1):
        velocity = tuple(float(state[f"velocity_{axis}_m_s"]) for axis in "xyz")
        azimuth_deg, elevation_deg = encode_simion_accelerator_velocity(velocity)
        values = (
            float(state["instrument_time_us"]),
            float(state["mass_amu"]),
            int(state["charge_state"]),
            float(state["position_x_mm"]),
            float(state["position_y_mm"]),
            float(state["position_z_mm"]),
            azimuth_deg,
            elevation_deg,
            float(state["kinetic_energy_eV"]),
            1,
            3,
        )
        ion_rows.append(
            [
                str(value) if isinstance(value, int) else format(value, ".17g")
                for value in values
            ]
        )
        row_map_rows.append(
            {
                "solver_row_index": solver_row,
                "particle_id": int(state["particle_id"]),
                "instrument_time_us": state["instrument_time_us"],
                "lineage_age_us": state["lineage_age_us"],
                "particle_age_us": state["particle_age_us"],
                "solver_birth_time_us": state["instrument_time_us"],
                "azimuth_deg": format(azimuth_deg, ".17g"),
                "elevation_deg": format(elevation_deg, ".17g"),
            }
        )
    return ion_rows, row_map_rows


def _write_row_map(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=ROW_MAP_COLUMNS, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_ion11(path: Path, rows: Sequence[Sequence[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerows(rows)


def _validate_solver_projection(
    canonical_path: Path,
    ion_path: Path,
    row_map_path: Path,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    report = validate_component_particle_state_csv(canonical_path)
    canonical_rows = _read_exact_csv(
        canonical_path, csv_columns(), "canonical component state"
    )
    if {row["frame_id"] for row in canonical_rows} != {EXPECTED_FRAME_ID}:
        raise ValueError("canonical source frame must be oatof_global")
    row_map_rows = _read_exact_csv(row_map_path, ROW_MAP_COLUMNS, "row map")
    with ion_path.open("r", encoding="utf-8-sig", newline="") as handle:
        ion_rows = list(csv.reader(handle))
    if len(ion_rows) != len(canonical_rows):
        raise ValueError("canonical and ION particle counts differ")
    if any(len(row) != 11 for row in ion_rows):
        raise ValueError("every ION row must contain exactly 11 columns")

    ordered_solver_identity_map(canonical_rows, row_map_rows)
    for state, mapping, ion in zip(canonical_rows, row_map_rows, ion_rows):
        for field in (
            "instrument_time_us",
            "lineage_age_us",
            "particle_age_us",
        ):
            if not math.isclose(
                float(mapping[field]),
                float(state[field]),
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                raise ValueError(f"row-map clock differs from canonical {field}")
        if not math.isclose(
            float(mapping["solver_birth_time_us"]),
            float(state["instrument_time_us"]),
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError(
                "row-map solver birth time differs from shared instrument time"
            )
        if not math.isclose(
            float(ion[0]),
            float(state["instrument_time_us"]),
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("ION birth time differs from shared instrument time")
        expected_fields = (
            state["mass_amu"],
            state["charge_state"],
            state["position_x_mm"],
            state["position_y_mm"],
            state["position_z_mm"],
            state["kinetic_energy_eV"],
        )
        ion_fields = (ion[1], ion[2], ion[3], ion[4], ion[5], ion[8])
        if any(
            not math.isclose(
                float(actual), float(expected), rel_tol=1e-12, abs_tol=1e-12
            )
            for actual, expected in zip(ion_fields, expected_fields)
        ):
            raise ValueError("ION physical state differs from canonical state")
        if ion[9:] != ["1", "3"]:
            raise ValueError("ION row uses an unexpected CWF or instance")
        validate_ion_velocity_adapter(state, mapping, ion)
    return report, canonical_rows


def _require_distinct_paths(source: Path, outputs: Sequence[Path]) -> None:
    source_path = source.resolve()
    output_paths = [path.resolve() for path in outputs]
    if len(output_paths) != len(set(output_paths)):
        raise ValueError("oaTOF SIMION output paths must be distinct")
    if source_path in output_paths:
        raise ValueError("oaTOF SIMION outputs must not overwrite their source")


def write_oatof_simion_input(
    source_path: Path,
    canonical_output_path: Path,
    ion_output_path: Path,
    row_map_output_path: Path,
    metadata_output_path: Path,
) -> dict[str, Any]:
    """Validate one oatof_global state and publish its controlled solver bundle."""
    outputs = [
        canonical_output_path,
        ion_output_path,
        row_map_output_path,
        metadata_output_path,
    ]
    _require_distinct_paths(source_path, outputs)
    if not source_path.is_file():
        raise ValueError("canonical oaTOF source must be an existing file")
    validate_component_particle_state_csv(source_path)
    source_rows = _read_exact_csv(
        source_path, csv_columns(), "canonical oaTOF source"
    )
    if {row["frame_id"] for row in source_rows} != {EXPECTED_FRAME_ID}:
        raise ValueError("canonical source frame must be oatof_global")

    with tempfile.TemporaryDirectory(prefix="oatof-simion-input-") as temporary:
        staging = Path(temporary)
        canonical_path = staging / "canonical_component_state.csv"
        ion_path = staging / "particles.ion"
        row_map_path = staging / "row_map.csv"

        canonical_path.write_bytes(source_path.read_bytes())
        ion_rows, row_map_rows = _derived_solver_rows(source_rows)
        _write_ion11(ion_path, ion_rows)
        _write_row_map(row_map_path, row_map_rows)
        validation, canonical_rows = _validate_solver_projection(
            canonical_path, ion_path, row_map_path
        )

        for staged, destination in (
            (canonical_path, canonical_output_path),
            (ion_path, ion_output_path),
            (row_map_path, row_map_output_path),
        ):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(staged.read_bytes())

    metadata = {
        "schema_version": 1,
        "role": "oatof_simion_input_bundle",
        "status": "PASS",
        "particles": len(canonical_rows),
        "source": _reference(source_path),
        "coordinate_frame_id": EXPECTED_FRAME_ID,
        "clock": {"solver_clock": "instrument_time"},
        "outputs": {
            "canonical_handoff_csv": _reference(canonical_output_path),
            "oatof_ion": _reference(ion_output_path),
            "row_map_csv": _reference(row_map_output_path),
        },
        "validation": {
            "canonical_state": validation,
            "one_to_one_particle_identity": "PASS",
            "kinetic_energy_consistency": "PASS",
            "simion_velocity_decode_round_trip": "PASS",
        },
    }
    metadata_output_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_output_path.write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--canonical-output", required=True, type=Path)
    parser.add_argument("--ion-output", required=True, type=Path)
    parser.add_argument("--row-map-output", required=True, type=Path)
    parser.add_argument("--metadata-output", required=True, type=Path)
    args = parser.parse_args()
    metadata = write_oatof_simion_input(
        args.source,
        args.canonical_output,
        args.ion_output,
        args.row_map_output,
        args.metadata_output,
    )
    print(
        "OATOF_SIMION_INPUT=PASS "
        f"PARTICLES={metadata['particles']} FRAME={EXPECTED_FRAME_ID}"
    )


if __name__ == "__main__":
    main()
