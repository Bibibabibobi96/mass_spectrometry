"""Derive a phase-matched canonical source with optional kinetic-energy scaling.

The module is solver independent.  It reads one governed canonical CSV, changes
``birth_time_s`` follows ``t_new = t_old * f0 / f_new``.  When requested, all
three velocity components receive one per-particle scale factor so kinetic
energy changes while direction is preserved.  The module publishes a new CSV
plus provenance metadata without modifying or overwriting existing files.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from common.contracts.particle_count_policy import (
    load_particle_count_policy,
    validate_positive_particle_count,
    validate_prefix_particle_sources,
)


COLUMNS = (
    "particle_id",
    "birth_time_s",
    "x_mm",
    "y_mm",
    "z_mm",
    "vx_m_s",
    "vy_m_s",
    "vz_m_s",
    "mass_amu",
    "charge_state",
)
PRESERVED_COLUMNS = tuple(column for column in COLUMNS if column != "birth_time_s")
ENERGY_SCALED_PRESERVED_COLUMNS = tuple(
    column
    for column in COLUMNS
    if column not in {"birth_time_s", "vx_m_s", "vy_m_s", "vz_m_s"}
)
FORMULA = "t_new = t_old * baseline_frequency_Hz / candidate_frequency_Hz"
ENERGY_FORMULA = "v_new = v_old * sqrt(target_kinetic_energy_eV / source_kinetic_energy_eV)"
PHASE_DEFINITION = "fractional_part(birth_time_s * frequency_Hz)"
METADATA_ROLE = "multipole_phase_matched_canonical_source_derivation"
SHA256_CHARACTERS = frozenset("0123456789ABCDEF")


def _validate_frequency(value: float, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite positive number")
    try:
        frequency = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be a finite positive number") from error
    if not math.isfinite(frequency) or frequency <= 0.0:
        raise ValueError(f"{label} must be a finite positive number")
    return frequency


def _load_rows_from_bytes(payload: bytes, label: str) -> list[dict[str, str]]:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError(f"{label} must be UTF-8 CSV") from error
    with io.StringIO(text, newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError(f"{label} canonical columns differ: {reader.fieldnames}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"{label} is empty")
    validate_positive_particle_count(len(rows))
    expected_ids = list(range(1, len(rows) + 1))
    observed_ids: list[int] = []
    for row_index, row in enumerate(rows, start=1):
        if None in row or any(value is None or value == "" for value in row.values()):
            raise ValueError(f"{label} row {row_index} is incomplete")
        try:
            particle_id = int(row["particle_id"])
            charge_state = int(row["charge_state"])
            numeric_values = {
                column: float(row[column]) for column in COLUMNS[1:-1]
            }
        except (TypeError, ValueError) as error:
            raise ValueError(f"{label} row {row_index} contains an invalid number") from error
        if not all(math.isfinite(value) for value in numeric_values.values()):
            raise ValueError(f"{label} particle {particle_id} contains a non-finite value")
        if numeric_values["birth_time_s"] < 0.0:
            raise ValueError(f"{label} particle {particle_id} has a negative birth time")
        if numeric_values["mass_amu"] <= 0.0 or charge_state == 0:
            raise ValueError(f"{label} particle {particle_id} has invalid mass or charge")
        observed_ids.append(particle_id)
    if observed_ids != expected_ids:
        raise ValueError(f"{label} particle IDs must be contiguous from 1 through N")
    return rows


def _render_rows(rows: list[dict[str, str]]) -> bytes:
    with io.StringIO(newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        return stream.getvalue().encode("utf-8")


def _circular_phase_error(first_cycles: float, second_cycles: float) -> float:
    first_phase = first_cycles % 1.0
    second_phase = second_cycles % 1.0
    direct_error = abs(first_phase - second_phase)
    return min(direct_error, 1.0 - direct_error)


def _derive_rows(
    rows: list[dict[str, str]],
    baseline_frequency_hz: float,
    candidate_frequency_hz: float,
    target_kinetic_energy_ev: float | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any], dict[str, Any] | None]:
    derived_rows: list[dict[str, str]] = []
    maximum_error = 0.0
    maximum_tolerance = 0.0
    source_energies: list[float] = []
    maximum_energy_error = 0.0
    for row in rows:
        old_time = float(row["birth_time_s"])
        new_time = old_time * baseline_frequency_hz / candidate_frequency_hz
        if not math.isfinite(new_time) or new_time < 0.0:
            raise ValueError(
                f"particle {row['particle_id']} produced an invalid derived birth time"
            )
        rendered_time = repr(new_time)
        reparsed_time = float(rendered_time)
        baseline_cycles = old_time * baseline_frequency_hz
        candidate_cycles = reparsed_time * candidate_frequency_hz
        error = _circular_phase_error(baseline_cycles, candidate_cycles)
        tolerance = max(
            32.0 * sys.float_info.epsilon,
            8.0 * (math.ulp(baseline_cycles) + math.ulp(candidate_cycles)),
        )
        if tolerance >= 0.25:
            raise ValueError(
                f"particle {row['particle_id']} clock magnitude cannot establish RF phase"
            )
        if error > tolerance:
            raise ValueError(
                f"particle {row['particle_id']} RF phase changed during derivation"
            )
        derived = dict(row)
        derived["birth_time_s"] = rendered_time
        if target_kinetic_energy_ev is not None:
            mass_kg = float(row["mass_amu"]) * 1.66053906660e-27
            velocities = [float(row[column]) for column in ("vx_m_s", "vy_m_s", "vz_m_s")]
            source_energy = 0.5 * mass_kg * sum(value * value for value in velocities) / 1.602176634e-19
            if not math.isfinite(source_energy) or source_energy <= 0.0:
                raise ValueError(f"particle {row['particle_id']} has nonpositive source energy")
            scale = math.sqrt(target_kinetic_energy_ev / source_energy)
            for column, velocity in zip(("vx_m_s", "vy_m_s", "vz_m_s"), velocities, strict=True):
                derived[column] = repr(velocity * scale)
            derived_energy = (
                0.5
                * mass_kg
                * sum(float(derived[column]) ** 2 for column in ("vx_m_s", "vy_m_s", "vz_m_s"))
                / 1.602176634e-19
            )
            maximum_energy_error = max(maximum_energy_error, abs(derived_energy - target_kinetic_energy_ev))
            source_energies.append(source_energy)
        derived_rows.append(derived)
        maximum_error = max(maximum_error, error)
        maximum_tolerance = max(maximum_tolerance, tolerance)
    phase = {
        "phase_definition": PHASE_DEFINITION,
        "verification_scope": "every_particle",
        "verified_particle_count": len(rows),
        "all_particles_verified": True,
        "maximum_circular_phase_error_cycles": maximum_error,
        "maximum_allowed_error_cycles": maximum_tolerance,
    }
    energy = None
    if target_kinetic_energy_ev is not None:
        energy = {
            "formula": ENERGY_FORMULA,
            "target_kinetic_energy_eV": target_kinetic_energy_ev,
            "source_energy_minimum_eV": min(source_energies),
            "source_energy_maximum_eV": max(source_energies),
            "direction_preserved_by_positive_scalar": True,
            "verified_particle_count": len(rows),
            "maximum_absolute_energy_error_eV": maximum_energy_error,
        }
    return derived_rows, phase, energy


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and set(value).issubset(SHA256_CHARACTERS)
    )


def validate_phase_matched_source_metadata(metadata: dict[str, Any]) -> None:
    """Validate version 1 phase-matched source provenance metadata."""
    if metadata.get("schema_version") not in (1, 2) or metadata.get("role") != METADATA_ROLE:
        raise ValueError("phase-matched source metadata identity is invalid")
    if metadata.get("formula") != FORMULA:
        raise ValueError("phase-matched source metadata formula is invalid")
    particle_count = metadata.get("particle_count")
    if isinstance(particle_count, bool) or not isinstance(particle_count, int):
        raise ValueError("phase-matched source particle count is invalid")
    for key in ("baseline_source_sha256", "derived_source_sha256"):
        if not _is_sha256(metadata.get(key)):
            raise ValueError(f"phase-matched source metadata {key} is invalid")
    _validate_frequency(metadata.get("baseline_frequency_Hz"), "baseline_frequency_Hz")
    _validate_frequency(metadata.get("candidate_frequency_Hz"), "candidate_frequency_Hz")
    expected_preserved = (
        ENERGY_SCALED_PRESERVED_COLUMNS
        if metadata.get("schema_version") == 2
        else PRESERVED_COLUMNS
    )
    if metadata.get("preserved_columns") != list(expected_preserved):
        raise ValueError("phase-matched source preserved columns are invalid")
    if metadata.get("schema_version") == 2:
        energy = metadata.get("kinetic_energy_scaling")
        if not isinstance(energy, dict) or energy.get("formula") != ENERGY_FORMULA:
            raise ValueError("phase-matched source energy scaling is invalid")
        target = float(energy.get("target_kinetic_energy_eV", math.nan))
        maximum_error = float(energy.get("maximum_absolute_energy_error_eV", math.nan))
        if (
            not math.isfinite(target)
            or target <= 0.0
            or not math.isfinite(maximum_error)
            or maximum_error < 0.0
            or energy.get("direction_preserved_by_positive_scalar") is not True
            or energy.get("verified_particle_count") != particle_count
        ):
            raise ValueError("phase-matched source energy verification is invalid")
    prefix = metadata.get("particle_count_policy")
    if not isinstance(prefix, dict) or prefix.get("positive_count_verified") is not True:
        raise ValueError("phase-matched source particle-count policy is invalid")
    is_standard = particle_count in load_particle_count_policy()["standard_particle_counts"]
    if prefix.get("standard_count_verified") is not is_standard:
        raise ValueError("phase-matched source standard-count classification is invalid")
    if prefix.get("row_order_preserved") is not True:
        raise ValueError("phase-matched source row-order policy is invalid")
    if particle_count == 100:
        if prefix.get("input_n100_prefix_of_n1000_verified") is not True:
            raise ValueError("N=100 phase-matched source lacks prefix verification")
        if prefix.get("derived_n100_prefix_projection_verified") is not True:
            raise ValueError("derived N=100 prefix projection is not verified")
        if not _is_sha256(prefix.get("n1000_reference_sha256")):
            raise ValueError("N=1000 reference identity is invalid")
    phase = metadata.get("rf_phase_invariance")
    if not isinstance(phase, dict):
        raise ValueError("phase-matched source phase verification is missing")
    if (
        phase.get("phase_definition") != PHASE_DEFINITION
        or phase.get("verification_scope") != "every_particle"
        or phase.get("verified_particle_count") != particle_count
        or phase.get("all_particles_verified") is not True
    ):
        raise ValueError("phase-matched source phase verification is invalid")
    maximum_error = float(phase.get("maximum_circular_phase_error_cycles", math.nan))
    tolerance = float(phase.get("maximum_allowed_error_cycles", math.nan))
    if (
        not math.isfinite(maximum_error)
        or not math.isfinite(tolerance)
        or maximum_error < 0.0
        or tolerance < 0.0
        or maximum_error > tolerance
    ):
        raise ValueError("phase-matched source phase error is invalid")


def _publish_exclusive(payload: bytes, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary_path, destination)
    except FileExistsError as error:
        raise FileExistsError(f"refusing to overwrite existing output: {destination}") from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _require_distinct_paths(paths: dict[str, Path]) -> None:
    resolved: dict[Path, str] = {}
    for label, path in paths.items():
        identity = path.resolve(strict=False)
        if identity in resolved:
            raise ValueError(f"{label} must differ from {resolved[identity]}")
        resolved[identity] = label


def derive_phase_matched_source(
    source_path: Path,
    output_csv_path: Path,
    output_metadata_path: Path,
    *,
    baseline_frequency_hz: float,
    candidate_frequency_hz: float,
    n1000_reference_path: Path | None = None,
    target_kinetic_energy_ev: float | None = None,
) -> dict[str, Any]:
    """Publish a deterministic phase-matched canonical source and metadata.

    ``source_path`` may contain any positive number of canonical rows.  N=100
    derivations additionally require the governed N=1000 source so the formal
    baseline prefix contract can be verified.  Other exploration samples do not
    acquire an unrelated prefix requirement.  Both output paths must be new and
    distinct from every input.  Existing files are never overwritten.
    """
    source_path = Path(source_path)
    output_csv_path = Path(output_csv_path)
    output_metadata_path = Path(output_metadata_path)
    baseline_frequency = _validate_frequency(
        baseline_frequency_hz, "baseline_frequency_hz"
    )
    candidate_frequency = _validate_frequency(
        candidate_frequency_hz, "candidate_frequency_hz"
    )
    if target_kinetic_energy_ev is not None:
        target_kinetic_energy_ev = float(target_kinetic_energy_ev)
        if not math.isfinite(target_kinetic_energy_ev) or target_kinetic_energy_ev <= 0.0:
            raise ValueError("target_kinetic_energy_ev must be finite and positive")
    paths = {
        "source_path": source_path,
        "output_csv_path": output_csv_path,
        "output_metadata_path": output_metadata_path,
    }
    if n1000_reference_path is not None:
        n1000_reference_path = Path(n1000_reference_path)
        paths["n1000_reference_path"] = n1000_reference_path
    _require_distinct_paths(paths)
    if output_csv_path.exists() or output_metadata_path.exists():
        existing = output_csv_path if output_csv_path.exists() else output_metadata_path
        raise FileExistsError(f"refusing to overwrite existing output: {existing}")

    source_payload = source_path.read_bytes()
    rows = _load_rows_from_bytes(source_payload, "baseline source")
    prefix_metadata: dict[str, Any] = {
        "positive_count_verified": True,
        "standard_count_verified": len(rows) in load_particle_count_policy()["standard_particle_counts"],
        "row_order_preserved": True,
        "prefixes_preserved_by_row_local_derivation": True,
    }
    reference_rows: list[dict[str, str]] | None = None
    if len(rows) == 100:
        if n1000_reference_path is None:
            raise ValueError("N=100 derivation requires n1000_reference_path")
        validate_prefix_particle_sources(source_path, n1000_reference_path)
        reference_payload = n1000_reference_path.read_bytes()
        reference_rows = _load_rows_from_bytes(reference_payload, "N=1000 reference")
        prefix_metadata.update(
            input_n100_prefix_of_n1000_verified=True,
            n1000_reference_sha256=hashlib.sha256(reference_payload).hexdigest().upper(),
        )
    elif n1000_reference_path is not None:
        raise ValueError("N=1000 derivation does not accept n1000_reference_path")

    derived_rows, phase_verification, energy_verification = _derive_rows(
        rows, baseline_frequency, candidate_frequency, target_kinetic_energy_ev
    )
    derived_payload = _render_rows(derived_rows)
    reloaded_rows = _load_rows_from_bytes(derived_payload, "derived source")
    for original, derived in zip(rows, reloaded_rows, strict=True):
        preserved_columns = (
            ENERGY_SCALED_PRESERVED_COLUMNS
            if target_kinetic_energy_ev is not None
            else PRESERVED_COLUMNS
        )
        for column in preserved_columns:
            if original[column] != derived[column]:
                raise ValueError(f"derived source changed preserved column {column}")
    if reference_rows is not None:
        projected_rows, _, _ = _derive_rows(
            reference_rows, baseline_frequency, candidate_frequency, target_kinetic_energy_ev
        )
        projected_prefix = _render_rows(projected_rows[:100])
        if projected_prefix != derived_payload:
            raise ValueError("derived N=100 source is not the N=1000 projection prefix")
        prefix_metadata["derived_n100_prefix_projection_verified"] = True

    metadata: dict[str, Any] = {
        "schema_version": 2 if target_kinetic_energy_ev is not None else 1,
        "role": METADATA_ROLE,
        "formula": FORMULA,
        "baseline_frequency_Hz": baseline_frequency,
        "candidate_frequency_Hz": candidate_frequency,
        "particle_count": len(rows),
        "baseline_source_sha256": hashlib.sha256(source_payload).hexdigest().upper(),
        "derived_source_sha256": hashlib.sha256(derived_payload).hexdigest().upper(),
        "preserved_columns": list(preserved_columns),
        "particle_count_policy": prefix_metadata,
        "rf_phase_invariance": phase_verification,
    }
    if energy_verification is not None:
        metadata["kinetic_energy_scaling"] = energy_verification
    validate_phase_matched_source_metadata(metadata)
    if file_sha256(source_path) != metadata["baseline_source_sha256"]:
        raise ValueError("baseline source changed during phase-matched derivation")
    metadata_payload = (json.dumps(metadata, indent=2) + "\n").encode("utf-8")

    csv_published = False
    try:
        _publish_exclusive(derived_payload, output_csv_path)
        csv_published = True
        _publish_exclusive(metadata_payload, output_metadata_path)
    except Exception:
        if csv_published:
            output_csv_path.unlink(missing_ok=True)
        raise
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--baseline-frequency-hz", required=True, type=float)
    parser.add_argument("--candidate-frequency-hz", required=True, type=float)
    parser.add_argument("--n1000-reference", type=Path)
    parser.add_argument("--target-kinetic-energy-ev", type=float)
    parser.add_argument("--output-csv", required=True, type=Path)
    parser.add_argument("--output-metadata", required=True, type=Path)
    args = parser.parse_args()
    metadata = derive_phase_matched_source(
        args.source,
        args.output_csv,
        args.output_metadata,
        baseline_frequency_hz=args.baseline_frequency_hz,
        candidate_frequency_hz=args.candidate_frequency_hz,
        n1000_reference_path=args.n1000_reference,
        target_kinetic_energy_ev=args.target_kinetic_energy_ev,
    )
    print(
        "PHASE_MATCHED_CANONICAL_SOURCE=PASS "
        f"PARTICLES={metadata['particle_count']} "
        f"SOURCE_SHA256={metadata['baseline_source_sha256']} "
        f"DERIVED_SHA256={metadata['derived_source_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
