"""Validate fixed-N=100 COMSOL release-construction diagnostic artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256


PARTICLE_COUNT = 100
ELEMENTARY_CHARGE_C = 1.602176634e-19
ATOMIC_MASS_KG = 1.66053906660e-27
PHASES = (
    "before_create",
    "after_create",
    "after_label",
    "after_set_filename",
    "after_set_icolp",
    "after_set_velocity_specification",
    "after_set_initial_velocity",
    "after_set_icolv",
    "after_set_rt",
    "after_import",
)


def _load_ion11(path: Path) -> tuple[list[list[float]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = [[float(value) for value in row] for row in csv.reader(stream)]
    if len(rows) != PARTICLE_COUNT or any(len(row) != 11 for row in rows):
        raise ValueError("Gate source must be exactly 100-by-11 ION11.")
    if any(not math.isfinite(value) for row in rows for value in row):
        raise ValueError("Gate source must contain only finite values.")
    birth_times = [row[0] for row in rows]
    if len(set(birth_times)) != PARTICLE_COUNT:
        raise ValueError("Gate source must contain 100 unique birth times.")
    expressions = [f"{value:.12g}[us]" for value in birth_times]
    if len(set(expressions)) != PARTICLE_COUNT:
        raise ValueError("Gate source must contain 100 unique formatted release times.")
    return rows, expressions


def _required_finite_number(parent: dict[str, Any], field: str) -> float:
    value = parent.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Frozen run config field {field!r} must be numeric.")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError(f"Frozen run config field {field!r} must be finite.")
    return converted


def _load_run_config(
    path: Path, particle_table: Path, particle_sha256: str
) -> float:
    document = _load_json_object(path)
    if (
        document.get("role") != "rf_quadrupole_comsol_run_config"
        or document.get("particles") != PARTICLE_COUNT
    ):
        raise ValueError("Frozen run config is not the fixed-N=100 COMSOL contract.")
    inputs = document.get("inputs")
    provenance = document.get("provenance")
    scientific_spec = document.get("compiled_scientific_spec")
    if not all(isinstance(value, dict) for value in (inputs, provenance, scientific_spec)):
        raise ValueError("Frozen run config is missing Gate A contract objects.")
    assert isinstance(inputs, dict)
    assert isinstance(provenance, dict)
    assert isinstance(scientific_spec, dict)
    if (
        scientific_spec.get("role")
        != "rf_quadrupole_comsol_interface_scientific_spec"
    ):
        raise ValueError("Frozen compiled scientific-spec role is unsupported.")
    configured_particle_table = inputs.get("particle_table")
    if not isinstance(configured_particle_table, str) or not _same_path(
        configured_particle_table, particle_table
    ):
        raise ValueError("Validator particle table differs from frozen run config.")
    frozen_sha256 = provenance.get("particle_source_sha256")
    if (
        not isinstance(frozen_sha256, str)
        or frozen_sha256.lower() != particle_sha256
    ):
        raise ValueError("Frozen particle-table SHA-256 differs from run provenance.")
    return _required_finite_number(scientific_spec, "source_axial_offset_mm")


def _expected_release_state(row: list[float], axial_offset_mm: float) -> list[float]:
    mass_amu = row[1]
    energy_ev = row[8]
    if mass_amu <= 0 or energy_ev < 0:
        raise ValueError("ION11 mass must be positive and energy must be non-negative.")
    speed = math.sqrt(
        2 * energy_ev * ELEMENTARY_CHARGE_C / (mass_amu * ATOMIC_MASS_KG)
    )
    azimuth = math.radians(row[6])
    elevation = math.radians(row[7])
    velocity_simion = (
        speed * math.cos(elevation) * math.cos(azimuth),
        speed * math.cos(elevation) * math.sin(azimuth),
        speed * math.sin(elevation),
    )
    return [
        row[5],
        -row[4],
        row[3] + axial_offset_mm,
        -velocity_simion[1],
        -velocity_simion[2],
        velocity_simion[0],
    ]


def _load_release_files(
    runtime_dir: Path, ion_rows: list[list[float]], axial_offset_mm: float
) -> tuple[list[Path], list[str]]:
    expected_names = [f"particle_{index:03d}.txt" for index in range(1, 101)]
    files = sorted(runtime_dir.glob("particle_*.txt"), key=lambda path: path.name)
    if [path.name for path in files] != expected_names:
        raise ValueError("Runtime must contain exactly particle_001..particle_100.")
    hashes: list[str] = []
    for index, path in enumerate(files):
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            rows = [[float(value) for value in row] for row in csv.reader(stream, delimiter="\t")]
        if (
            len(rows) != 1
            or len(rows[0]) != 6
            or any(not math.isfinite(value) for value in rows[0])
        ):
            raise ValueError(f"Release file is not one finite six-column row: {path.name}")
        expected = _expected_release_state(ion_rows[index], axial_offset_mm)
        for column, (actual, reference) in enumerate(zip(rows[0], expected), 1):
            if not math.isclose(actual, reference, rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError(
                    f"Release file {path.name} column {column} differs from "
                    "the frozen ION11/scientific-spec state."
                )
        hashes.append(file_sha256(path).lower())
    return files, hashes


def _load_json_object(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(document, dict):
        raise ValueError(f"Expected one JSON object: {path}")
    return document


def _same_path(left: str, right: Path) -> bool:
    return os.path.normcase(str(Path(left).resolve())) == os.path.normcase(
        str(right.resolve())
    )


def _validate_result(
    result: dict[str, Any],
    particle_sha256: str,
    release_hashes: list[str],
) -> None:
    expected_scalars: dict[str, Any] = {
        "schema_version": 1,
        "role": "rf_release_construction_gate_result",
        "status": "success",
        "particles": PARTICLE_COUNT,
        "release_tag_count": PARTICLE_COUNT,
        "release_file_count": PARTICLE_COUNT,
        "birth_time_count": PARTICLE_COUNT,
        "unique_birth_time_count": PARTICLE_COUNT,
        "unique_release_time_expression_count": PARTICLE_COUNT,
        "first_release_tag": "rel001",
        "last_release_tag": "rel100",
        "breadcrumb_count": PARTICLE_COUNT * len(PHASES),
        "stationary_study_present": True,
        "stationary_solver_present": True,
        "electric_force_present": False,
        "particle_study_present": False,
        "particle_solver_present": False,
    }
    for key, expected in expected_scalars.items():
        if result.get(key) != expected:
            raise ValueError(f"Gate result field {key!r} differs from {expected!r}.")
    if str(result.get("particle_table_sha256", "")).lower() != particle_sha256:
        raise ValueError("Gate result particle-table SHA-256 differs from frozen input.")
    entries = result.get("release_files")
    if not isinstance(entries, list) or len(entries) != PARTICLE_COUNT:
        raise ValueError("Gate result must inventory all 100 release files.")
    for index, (entry, expected_hash) in enumerate(zip(entries, release_hashes), 1):
        expected_relative = f"runtime/particle_{index:03d}.txt"
        if not isinstance(entry, dict):
            raise ValueError("Gate result release-file inventory entry is not an object.")
        if (
            entry.get("particle_index") != index
            or entry.get("relative_path") != expected_relative
            or str(entry.get("sha256", "")).lower() != expected_hash
            or entry.get("row_count") != 1
            or entry.get("column_count") != 6
        ):
            raise ValueError(f"Gate result release-file inventory differs at {index}.")


def _validate_breadcrumbs(
    path: Path,
    release_files: list[Path],
    release_hashes: list[str],
    birth_times: list[float],
    expressions: list[str],
) -> None:
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    if len(records) != PARTICLE_COUNT * len(PHASES):
        raise ValueError("Gate breadcrumb stream must contain exactly 1000 records.")
    for sequence, record in enumerate(records, 1):
        if not isinstance(record, dict) or record.get("sequence") != sequence:
            raise ValueError(f"Gate breadcrumb sequence differs at record {sequence}.")
        particle_index = (sequence - 1) // len(PHASES) + 1
        phase_index = (sequence - 1) % len(PHASES)
        phase = PHASES[phase_index]
        expected_tag = f"rel{particle_index:03d}"
        expected_relative = f"runtime/particle_{particle_index:03d}.txt"
        expected_count = particle_index - 1 if phase == "before_create" else particle_index
        if (
            record.get("schema_version") != 1
            or record.get("role") != "rf_release_construction_breadcrumb"
            or record.get("particle_index") != particle_index
            or record.get("release_tag") != expected_tag
            or record.get("phase") != phase
            or record.get("release_tag_count") != expected_count
            or record.get("file_relative_path") != expected_relative
            or str(record.get("file_sha256", "")).lower()
            != release_hashes[particle_index - 1]
            or record.get("row_count") != 1
            or record.get("column_count") != 6
            or record.get("release_time_us") != birth_times[particle_index - 1]
            or record.get("release_time_expression") != expressions[particle_index - 1]
        ):
            raise ValueError(
                f"Gate breadcrumb identity/content differs at sequence {sequence}."
            )
        expected_filename = (
            ""
            if phase_index < PHASES.index("after_set_filename")
            else str(release_files[particle_index - 1])
        )
        actual_filename = str(record.get("actual_filename", ""))
        if expected_filename:
            if not _same_path(actual_filename, release_files[particle_index - 1]):
                raise ValueError(
                    f"Gate breadcrumb Filename differs at sequence {sequence}."
                )
        elif actual_filename:
            raise ValueError(
                f"Gate breadcrumb Filename appeared too early at sequence {sequence}."
            )
        expected_rt = (
            expressions[particle_index - 1]
            if phase_index >= PHASES.index("after_set_rt")
            else ""
        )
        if record.get("actual_release_time_expression", "") != expected_rt:
            raise ValueError(f"Gate breadcrumb rt differs at sequence {sequence}.")


def validate_release_construction_gate(
    *,
    run_config_path: Path,
    particle_table: Path,
    breadcrumbs: Path,
    result_path: Path,
    runtime_dir: Path,
) -> dict[str, Any]:
    """Validate the independent files, attributes, and event stream for Gate A."""
    rows, expressions = _load_ion11(particle_table)
    particle_sha256 = file_sha256(particle_table).lower()
    axial_offset_mm = _load_run_config(
        run_config_path, particle_table, particle_sha256
    )
    release_files, release_hashes = _load_release_files(
        runtime_dir, rows, axial_offset_mm
    )
    result = _load_json_object(result_path)
    _validate_result(result, particle_sha256, release_hashes)
    _validate_breadcrumbs(
        breadcrumbs,
        release_files,
        release_hashes,
        [row[0] for row in rows],
        expressions,
    )
    return {
        "schema_version": 1,
        "role": "rf_release_construction_gate_validation",
        "status": "success",
        "particles": PARTICLE_COUNT,
        "release_files": PARTICLE_COUNT,
        "release_tags": PARTICLE_COUNT,
        "release_time_expressions": PARTICLE_COUNT,
        "breadcrumbs": PARTICLE_COUNT * len(PHASES),
        "particle_table_sha256": particle_sha256,
        "source_axial_offset_mm": axial_offset_mm,
    }


def _write_json_atomically(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
    written = temporary.write_text(payload, encoding="utf-8")
    if written != len(payload):
        raise OSError(f"Incomplete validation report write: {temporary}")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-config", type=Path, required=True)
    parser.add_argument("--particle-table", type=Path, required=True)
    parser.add_argument("--breadcrumbs", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    validation = validate_release_construction_gate(
        run_config_path=arguments.run_config,
        particle_table=arguments.particle_table,
        breadcrumbs=arguments.breadcrumbs,
        result_path=arguments.result,
        runtime_dir=arguments.runtime_dir,
    )
    _write_json_atomically(arguments.output, validation)
    print("RELEASE_CONSTRUCTION_GATE_VALIDATION=PASS PARTICLES=100 BREADCRUMBS=1000")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
