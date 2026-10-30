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
from common.contracts.particle_physics import speed_m_s_from_kinetic_energy_ev


PARTICLE_COUNT = 100
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
    if any(value < 0 for value in birth_times):
        raise ValueError("Gate birth times must be nonnegative.")
    expressions = [f"{value * 1e-6:.17g}[s]" for value in birth_times]
    return rows, expressions


def _required_finite_number(parent: dict[str, Any], field: str) -> float:
    value = parent.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Frozen run config field {field!r} must be numeric.")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError(f"Frozen run config field {field!r} must be finite.")
    return converted


def _load_run_config(path: Path, particle_table: Path, particle_sha256: str) -> float:
    document = _load_json_object(path)
    if (
        document.get("role") != "rf_quadrupole_comsol_run_config"
        or document.get("particles") != PARTICLE_COUNT
    ):
        raise ValueError("Frozen run config is not the fixed-N=100 COMSOL contract.")
    inputs = document.get("inputs")
    provenance = document.get("provenance")
    scientific_spec = document.get("compiled_scientific_spec")
    if not all(
        isinstance(value, dict) for value in (inputs, provenance, scientific_spec)
    ):
        raise ValueError("Frozen run config is missing Gate A contract objects.")
    assert isinstance(inputs, dict)
    assert isinstance(provenance, dict)
    assert isinstance(scientific_spec, dict)
    if scientific_spec.get("role") != "rf_quadrupole_comsol_interface_scientific_spec":
        raise ValueError("Frozen compiled scientific-spec role is unsupported.")
    configured_particle_table = inputs.get("particle_table")
    if not isinstance(configured_particle_table, str) or not _same_path(
        configured_particle_table, particle_table
    ):
        raise ValueError("Validator particle table differs from frozen run config.")
    frozen_sha256 = provenance.get("particle_source_sha256")
    if not isinstance(frozen_sha256, str) or frozen_sha256.lower() != particle_sha256:
        raise ValueError("Frozen particle-table SHA-256 differs from run provenance.")
    return _required_finite_number(scientific_spec, "source_axial_offset_mm")


def _expected_release_state(row: list[float], axial_offset_mm: float) -> list[float]:
    mass_amu = row[1]
    energy_ev = row[8]
    if mass_amu <= 0 or energy_ev < 0:
        raise ValueError("ION11 mass must be positive and energy must be non-negative.")
    speed = speed_m_s_from_kinetic_energy_ev(mass_amu, energy_ev)
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


def _load_json_object(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(document, dict):
        raise ValueError(f"Expected one JSON object: {path}")
    return document


def _same_path(left: str, right: Path) -> bool:
    return os.path.normcase(str(Path(left).resolve())) == os.path.normcase(
        str(right.resolve())
    )


def _groups(rows: list[list[float]]) -> list[list[int]]:
    groups: dict[float, list[int]] = {}
    for index, row in enumerate(rows, 1):
        if row[1:3] != rows[0][1:3]:
            raise ValueError("Current RF release requires homogeneous mass and charge.")
        if row[2] == 0 or row[2] != int(row[2]):
            raise ValueError("Charge must be a nonzero integer.")
        groups.setdefault(row[0] * 1e-6, []).append(index)
    return list(groups.values())


def validate_release_construction_gate(
    *,
    run_config_path: Path,
    particle_table: Path,
    breadcrumbs: Path,
    result_path: Path,
    runtime_dir: Path,
) -> dict[str, Any]:
    """Validate version2 exact-birth grouped release evidence; sealed v1 is unchanged."""
    rows, expressions = _load_ion11(particle_table)
    particle_sha = file_sha256(particle_table).lower()
    offset = _load_run_config(run_config_path, particle_table, particle_sha)
    groups = _groups(rows)
    result = _load_json_object(result_path)
    group_count = len(groups)
    expected = dict(
        schema_version=2,
        role="rf_release_construction_gate_result",
        status="success",
        particles=PARTICLE_COUNT,
        release_tag_count=group_count,
        release_file_count=group_count,
        birth_time_count=PARTICLE_COUNT,
        unique_birth_time_count=len({r[0] for r in rows}),
        unique_release_time_expression_count=len(set(expressions)),
        first_release_tag="rel001",
        last_release_tag=f"rel{group_count:03d}",
        breadcrumb_count=group_count * len(PHASES),
        stationary_study_present=True,
        stationary_solver_present=True,
        electric_force_present=False,
        particle_study_present=False,
        particle_solver_present=False,
    )
    for key, value in expected.items():
        if result.get(key) != value:
            raise ValueError(f"Gate result field {key!r} differs from grouped source.")
    if str(result.get("particle_table_sha256", "")).lower() != particle_sha:
        raise ValueError("Particle-table identity differs.")
    native_order = [index for group in groups for index in group]
    if result.get("native_order") != native_order:
        raise ValueError("Native source order differs.")
    entries = result.get("release_files")
    if not isinstance(entries, list) or len(entries) != group_count:
        raise ValueError("Release group inventory differs.")
    expected_names = [f"particle_{i:03d}.txt" for i in range(1, group_count + 1)]
    if sorted(p.name for p in runtime_dir.glob("particle_*.txt")) != expected_names:
        raise ValueError("Release file set differs.")
    hashes = []
    for index, (group, entry) in enumerate(zip(groups, entries), 1):
        path = runtime_dir / expected_names[index - 1]
        with path.open(encoding="utf-8-sig", newline="") as stream:
            actual = [
                [float(v) for v in line] for line in csv.reader(stream, delimiter="\t")
            ]
        if len(actual) != len(group) or any(
            len(r) != 6 or any(not math.isfinite(v) for v in r) for r in actual
        ):
            raise ValueError("Grouped release 6D shape/finite facts differ.")
        for source_index, state in zip(group, actual):
            reference = _expected_release_state(rows[source_index - 1], offset)
            if any(
                not math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12)
                for a, b in zip(state, reference)
            ):
                raise ValueError("Grouped release 6D differs from frozen source.")
        digest = file_sha256(path).lower()
        hashes.append(digest)
        expected_entry = dict(
            group_index=index,
            source_rows=group,
            particle_ids=group,
            birth_s=rows[group[0] - 1][0] * 1e-6,
            relative_path=f"runtime/{path.name}",
            sha256=digest,
            row_count=len(group),
            column_count=6,
        )
        if isinstance(entry, dict):
            entry = dict(entry)
            for key in ("source_rows", "particle_ids"):
                if isinstance(entry.get(key), int):
                    entry[key] = [entry[key]]
        if entry != expected_entry:
            raise ValueError("Grouped release identity/clock/source binding differs.")
    records = [
        json.loads(line)
        for line in breadcrumbs.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    if len(records) != group_count * len(PHASES):
        raise ValueError("Grouped breadcrumb count differs.")
    for sequence, record in enumerate(records, 1):
        ordinal, phase_index = divmod(sequence - 1, len(PHASES))
        group = groups[ordinal]
        phase = PHASES[phase_index]
        path = runtime_dir / expected_names[ordinal]
        expected_record = dict(
            schema_version=2,
            role="rf_release_construction_breadcrumb",
            sequence=sequence,
            group_index=ordinal + 1,
            source_rows=group,
            release_tag=f"rel{ordinal + 1:03d}",
            phase=phase,
            release_tag_count=ordinal if phase == "before_create" else ordinal + 1,
            file_relative_path=f"runtime/{path.name}",
            file_sha256=hashes[ordinal],
            row_count=len(group),
            column_count=6,
            birth_s=rows[group[0] - 1][0] * 1e-6,
            release_time_expression=expressions[group[0] - 1],
        )
        if isinstance(record.get("source_rows"), int):
            record["source_rows"] = [record["source_rows"]]
        if any(record.get(k) != v for k, v in expected_record.items()):
            raise ValueError(f"Grouped breadcrumb binding differs at {sequence}.")
        filename = record.get("actual_filename", "")
        if phase_index >= PHASES.index("after_set_filename"):
            if not isinstance(filename, str) or not _same_path(filename, path):
                raise ValueError("Breadcrumb Filename differs.")
        elif filename:
            raise ValueError("Breadcrumb Filename appeared too early.")
        expected_rt = (
            expressions[group[0] - 1]
            if phase_index >= PHASES.index("after_set_rt")
            else ""
        )
        if record.get("actual_release_time_expression", "") != expected_rt:
            raise ValueError("Breadcrumb rt differs.")
    return dict(
        schema_version=2,
        role="rf_release_construction_gate_validation",
        status="success",
        particles=PARTICLE_COUNT,
        release_files=group_count,
        release_tags=group_count,
        release_time_expressions=len(set(expressions)),
        breadcrumbs=len(records),
        native_order=native_order,
        particle_table_sha256=particle_sha,
        source_axial_offset_mm=offset,
    )


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
    print(
        f"RELEASE_CONSTRUCTION_GATE_VALIDATION=PASS PARTICLES={validation['particles']} "
        f"GROUPS={validation['release_tags']} BREADCRUMBS={validation['breadcrumbs']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
