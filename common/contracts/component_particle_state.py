"""Validate the version-1 cross-component canonical particle-state CSV.

The contract preserves transfer identity, lineage, species, a named spatial
frame, a named clock epoch, and one complete three-dimensional state. It does
not propagate particles, transform coordinates, or derive phase. Serialized
energy and mass-to-charge are consistency checked from the primary mass,
charge, and velocity fields using shared contract math. Spatial transforms
remain the responsibility of :mod:`rigid_transform`; component physics remains
the responsibility of the producing solver.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

try:
    from common.contracts.particle_physics import kinetic_energy_ev, mass_to_charge_th
    from common.contracts.rigid_transform import PhaseSpaceState
except ModuleNotFoundError:
    from particle_physics import kinetic_energy_ev, mass_to_charge_th
    from rigid_transform import PhaseSpaceState


SCHEMA_VERSION = 1
SCHEMA_PATH = Path(__file__).with_name("schemas") / "component_particle_state.schema.json"
TIME_TOLERANCE_US = 1e-9
DERIVED_RELATIVE_TOLERANCE = 1e-9
DERIVED_ABSOLUTE_TOLERANCE = 1e-12

INTEGER_FIELDS = {
    "particle_id", "parent_particle_id", "generation", "charge_state",
}
NUMBER_FIELDS = {
    "instrument_time_us", "lineage_age_us", "particle_age_us",
    "last_component_elapsed_time_us", "lineage_birth_time_us",
    "particle_birth_time_us", "particle_weight", "mass_to_charge_Th", "mass_amu",
    "position_x_mm", "position_y_mm", "position_z_mm", "velocity_x_m_s",
    "velocity_y_m_s", "velocity_z_m_s", "kinetic_energy_eV",
    "phase_rad",
}


def load_schema() -> dict[str, Any]:
    """Load and check the bundled JSON Schema defining CSV version 1."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    if schema.get("x-csv-schema-version") != SCHEMA_VERSION:
        raise ValueError(
            "component particle-state schema version differs from validator version"
        )
    return schema


def csv_columns() -> list[str]:
    """Return the exact, versioned CSV column order."""
    return list(load_schema()["x-csv-column-order"])


def _parse_integer(value: str, field: str, row_number: int) -> int | None:
    if field == "parent_particle_id" and value == "":
        return None
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(
            f"row {row_number} field {field} is not an integer: {value!r}"
        ) from error
    if str(parsed) != value.strip():
        raise ValueError(
            f"row {row_number} field {field} is not a canonical integer: {value!r}"
        )
    return parsed


def _parse_number(value: str, field: str, row_number: int) -> float | None:
    if field == "phase_rad" and value == "":
        return None
    try:
        parsed = float(value)
    except ValueError as error:
        raise ValueError(
            f"row {row_number} field {field} is not numeric: {value!r}"
        ) from error
    if not math.isfinite(parsed):
        raise ValueError(f"row {row_number} field {field} must be finite")
    return parsed


def _parse_row(row: dict[str, str], row_number: int) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for field, value in row.items():
        if field in INTEGER_FIELDS:
            parsed[field] = _parse_integer(value, field, row_number)
        elif field in NUMBER_FIELDS:
            parsed[field] = _parse_number(value, field, row_number)
        else:
            parsed[field] = None if field == "phase_reference_id" and value == "" else value
    return parsed


def _validate_lineage(row: dict[str, Any], row_number: int) -> None:
    parent = row["parent_particle_id"]
    generation = row["generation"]
    if generation == 0 and parent is not None:
        raise ValueError(f"row {row_number} generation 0 must not have a parent")
    if generation > 0 and parent is None:
        raise ValueError(f"row {row_number} generation {generation} requires a parent")
    if parent == row["particle_id"]:
        raise ValueError(f"row {row_number} particle cannot be its own parent")


def _validate_clock(row: dict[str, Any], row_number: int) -> None:
    instrument_time = row["instrument_time_us"]
    relationships = (
        ("lineage", row["lineage_birth_time_us"], row["lineage_age_us"]),
        ("particle", row["particle_birth_time_us"], row["particle_age_us"]),
    )
    for label, birth_time, age in relationships:
        residual = instrument_time - birth_time - age
        if abs(residual) > TIME_TOLERANCE_US:
            raise ValueError(
                f"row {row_number} {label} clock residual {residual:.15g} us "
                f"exceeds {TIME_TOLERANCE_US:.15g} us"
            )
    if row["last_component_elapsed_time_us"] > row["particle_age_us"] + TIME_TOLERANCE_US:
        raise ValueError(
            f"row {row_number} last-component elapsed time exceeds particle age"
        )
    if row["generation"] == 0:
        if (
            abs(row["lineage_birth_time_us"] - row["particle_birth_time_us"])
            > TIME_TOLERANCE_US
            or abs(row["lineage_age_us"] - row["particle_age_us"])
            > TIME_TOLERANCE_US
        ):
            raise ValueError(
                f"row {row_number} root particle clock must equal lineage clock"
            )
    elif row["lineage_birth_time_us"] > (
        row["particle_birth_time_us"] + TIME_TOLERANCE_US
    ):
        raise ValueError(
            f"row {row_number} descendant cannot be born before its lineage"
        )


def _validate_derived_quantities(row: dict[str, Any], row_number: int) -> None:
    expected_mass_to_charge = mass_to_charge_th(
        row["mass_amu"], row["charge_state"]
    )
    if not math.isclose(
        row["mass_to_charge_Th"],
        expected_mass_to_charge,
        rel_tol=DERIVED_RELATIVE_TOLERANCE,
        abs_tol=DERIVED_ABSOLUTE_TOLERANCE,
    ):
        raise ValueError(
            f"row {row_number} mass_to_charge_Th is inconsistent with mass_amu "
            "and charge_state"
        )
    expected_energy = kinetic_energy_ev(
        row["mass_amu"],
        row["velocity_x_m_s"],
        row["velocity_y_m_s"],
        row["velocity_z_m_s"],
    )
    if not math.isclose(
        row["kinetic_energy_eV"],
        expected_energy,
        rel_tol=DERIVED_RELATIVE_TOLERANCE,
        abs_tol=DERIVED_ABSOLUTE_TOLERANCE,
    ):
        raise ValueError(
            f"row {row_number} kinetic_energy_eV is inconsistent with mass_amu "
            "and velocity"
        )


def validate_component_particle_state_csv(path: Path) -> dict[str, Any]:
    """Validate one CSV and return a compact identity report.

    Version 1 is a transfer-state table: each particle ID appears exactly once.
    Device-specific event details belong in separate tables joined by
    ``particle_id`` and must not be appended to this exact CSV schema.
    """
    schema = load_schema()
    expected_columns = list(schema["x-csv-column-order"])
    validator = Draft202012Validator(schema)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != expected_columns:
            raise ValueError(
                f"component particle-state columns differ: {reader.fieldnames}; "
                f"expected {expected_columns}"
            )
        raw_rows = list(reader)
    if not raw_rows:
        raise ValueError("component particle-state CSV must contain at least one row")

    particle_ids: set[int] = set()
    frames: set[str] = set()
    epochs: set[str] = set()
    for row_number, raw_row in enumerate(raw_rows, start=2):
        row = _parse_row(raw_row, row_number)
        errors = sorted(validator.iter_errors(row), key=lambda item: list(item.path))
        if errors:
            location = ".".join(str(item) for item in errors[0].path)
            raise ValueError(
                f"row {row_number} field {location or '<row>'}: {errors[0].message}"
            )
        particle_id = row["particle_id"]
        if particle_id in particle_ids:
            raise ValueError(f"duplicate particle_id: {particle_id}")
        particle_ids.add(particle_id)
        _validate_lineage(row, row_number)
        _validate_clock(row, row_number)
        _validate_derived_quantities(row, row_number)
        PhaseSpaceState(
            frame_id=row["frame_id"],
            position_mm=tuple(row[f"position_{axis}_mm"] for axis in "xyz"),
            velocity_m_s=tuple(row[f"velocity_{axis}_m_s"] for axis in "xyz"),
            instrument_time_us=row["instrument_time_us"],
        )
        frames.add(row["frame_id"])
        epochs.add(row["clock_epoch_id"])

    return {
        "schema_version": SCHEMA_VERSION,
        "role": "component_particle_state_validation",
        "status": "PASS",
        "rows": len(raw_rows),
        "particles": len(particle_ids),
        "frame_ids": sorted(frames),
        "clock_epoch_ids": sorted(epochs),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = validate_component_particle_state_csv(args.state)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        "COMPONENT_PARTICLE_STATE=PASS "
        f"SCHEMA_VERSION={report['schema_version']} PARTICLES={report['particles']}"
    )


if __name__ == "__main__":
    main()
