"""Project a frozen SIMION checkpoint cohort into a Cartesian COMSOL release."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from common.contracts.particle_physics import kinetic_energy_ev
REQUIRED_COLUMNS = {
    "particle_id",
    "event",
    "instrument_time_us",
    "x_mm",
    "y_mm",
    "z_mm",
    "vx_mm_per_us",
    "vy_mm_per_us",
    "vz_mm_per_us",
    "kinetic_energy_eV",
    "pulse_eligibility",
}


def _finite(row: dict[str, str], name: str) -> float:
    value = float(row[name])
    if not math.isfinite(value):
        raise ValueError(f"checkpoint {name} must be finite")
    return value


def _load_geometry(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if (
        document.get("schema_version") != 1
        or document.get("role") != "oa_tof_resolved_contract_do_not_edit"
    ):
        raise ValueError("oaTOF resolved geometry identity is invalid")
    return document


def build_comsol_prepulse_replay(
    checkpoints_path: Path,
    geometry_path: Path,
    ion_output_path: Path,
    metadata_output_path: Path,
    *,
    mass_amu: float,
    charge_state: int,
    event: str = "pre_pulse_state",
    eligibility: str = "eligible",
    limit: int | None = None,
) -> dict[str, Any]:
    """Write the selected states in the global Cartesian frame.

    ``ion_output_path`` is retained as the Python API parameter name for callers
    created during the diagnostic investigation.  The file is now a canonical
    headed CSV, not a SIMION local-angle ION table.
    """
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive when supplied")
    geometry = _load_geometry(geometry_path)
    stage1_min = float(geometry["geometry_mm"]["accelerator_repeller_z"])
    stage1_max = float(geometry["geometry_mm"]["accelerator_grid1_z"])
    if not math.isfinite(mass_amu) or mass_amu <= 0:
        raise ValueError("mass_amu must be positive and finite")
    if charge_state == 0:
        raise ValueError("charge_state must be nonzero")

    with checkpoints_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"checkpoint table is missing columns: {sorted(missing)}")
        selected = [
            row
            for row in reader
            if row["event"] == event and row["pulse_eligibility"] == eligibility
        ]
    if limit is not None:
        selected = selected[:limit]
    if not selected:
        raise ValueError("checkpoint selection is empty")

    particle_ids = [int(row["particle_id"]) for row in selected]
    if len(set(particle_ids)) != len(particle_ids):
        raise ValueError("checkpoint selection contains duplicate particle_id")
    pulse_times = {_finite(row, "instrument_time_us") for row in selected}
    if len(pulse_times) != 1:
        raise ValueError("selected pre-pulse particles do not share one pulse time")

    release_rows: list[list[str]] = []
    maximum_energy_error = 0.0
    for particle_id, row in zip(particle_ids, selected, strict=True):
        position = tuple(_finite(row, f"{axis}_mm") for axis in "xyz")
        velocity = tuple(
            1.0e3 * _finite(row, f"v{axis}_mm_per_us") for axis in "xyz"
        )
        if not stage1_min <= position[2] <= stage1_max:
            raise ValueError(
                f"particle {particle_id} is outside accelerator stage 1"
            )
        energy = _finite(row, "kinetic_energy_eV")
        recomputed = kinetic_energy_ev(mass_amu, *velocity)
        maximum_energy_error = max(maximum_energy_error, abs(recomputed - energy))
        if not math.isclose(recomputed, energy, rel_tol=2.0e-6, abs_tol=1.0e-6):
            raise ValueError(
                f"particle {particle_id} velocity and kinetic energy disagree"
            )
        values = (
            particle_id,
            mass_amu,
            charge_state,
            *position,
            *velocity,
            energy,
        )
        release_rows.append(
            [str(value) if isinstance(value, int) else format(value, ".17g") for value in values]
        )

    ion_output_path.parent.mkdir(parents=True, exist_ok=True)
    with ion_output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            (
                "particle_id",
                "mass_amu",
                "charge_state",
                "x_mm",
                "y_mm",
                "z_mm",
                "vx_m_per_s",
                "vy_m_per_s",
                "vz_m_per_s",
                "kinetic_energy_eV",
            )
        )
        writer.writerows(release_rows)

    with ion_output_path.open(encoding="utf-8", newline="") as handle:
        serialized = list(csv.DictReader(handle))
    maximum_velocity_serialization_error = max(
        abs(float(output[f"v{axis}_m_per_s"]) - velocity_component)
        for output, source in zip(serialized, selected, strict=True)
        for axis, velocity_component in zip(
            "xyz",
            (1.0e3 * _finite(source, f"v{axis}_mm_per_us") for axis in "xyz"),
            strict=True,
        )
    )
    if maximum_velocity_serialization_error >= 1.0e-6:
        raise ValueError("Cartesian velocity serialization exceeds 1e-6 m/s")
    metadata = {
        "schema_version": 1,
        "role": "rf_oatof_comsol_cartesian_retrace_release",
        "status": "PASS",
        "selection": {
            "event": event,
            "pulse_eligibility": eligibility,
            "particles": len(selected),
            "particle_id_min": min(particle_ids),
            "particle_id_max": max(particle_ids),
            "pulse_time_us": next(iter(pulse_times)),
        },
        "species": {"mass_amu": mass_amu, "charge_state": charge_state},
        "stage1_z_interval_mm": {"minimum": stage1_min, "maximum": stage1_max},
        "maximum_energy_round_trip_error_eV": maximum_energy_error,
        "coordinate_frame": "shared_global_cartesian",
        "velocity_columns": ["vx_m_per_s", "vy_m_per_s", "vz_m_per_s"],
        "maximum_velocity_serialization_error_m_per_s": (
            maximum_velocity_serialization_error
        ),
        "velocity_error_limit_m_per_s": 1.0e-6,
        "inputs": {
            "checkpoints_sha256": file_sha256(checkpoints_path),
            "resolved_geometry_sha256": file_sha256(geometry_path),
        },
        "output": {
            "path": str(ion_output_path.resolve()),
            "sha256": file_sha256(ion_output_path),
            "bytes": ion_output_path.stat().st_size,
        },
    }
    metadata_output_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_output_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoints", required=True, type=Path)
    parser.add_argument("--geometry", required=True, type=Path)
    parser.add_argument(
        "--release-output", "--ion-output", dest="ion_output", required=True, type=Path
    )
    parser.add_argument("--metadata-output", required=True, type=Path)
    parser.add_argument("--mass-amu", required=True, type=float)
    parser.add_argument("--charge-state", required=True, type=int)
    parser.add_argument("--event", default="pre_pulse_state")
    parser.add_argument("--eligibility", default="eligible")
    parser.add_argument("--limit", type=int)
    arguments = parser.parse_args()
    metadata = build_comsol_prepulse_replay(
        arguments.checkpoints,
        arguments.geometry,
        arguments.ion_output,
        arguments.metadata_output,
        mass_amu=arguments.mass_amu,
        charge_state=arguments.charge_state,
        event=arguments.event,
        eligibility=arguments.eligibility,
        limit=arguments.limit,
    )
    print(
        "COMSOL_PREPULSE_REPLAY_INPUT=PASS "
        f"PARTICLES={metadata['selection']['particles']}"
    )


if __name__ == "__main__":
    main()
