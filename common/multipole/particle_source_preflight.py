"""Validate a canonical multipole particle source and freeze its physical metadata."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from common.contracts.particle_physics import kinetic_energy_ev
from common.contracts.particle_count_policy import validate_positive_particle_count

COLUMNS = [
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
]
ENERGY_BOUND_TOLERANCE_EV = 2e-9


def _load_operating_point(
    source_family_path: Path | None,
    operating_point_id: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    if (source_family_path is None) != (operating_point_id is None):
        raise ValueError(
            "source-family operating-point binding requires both path and point ID"
        )
    if source_family_path is None:
        return None, None, None
    family_bytes = source_family_path.read_bytes()
    family_sha256 = hashlib.sha256(family_bytes).hexdigest().upper()
    family = json.loads(family_bytes.decode("utf-8-sig"))
    if (
        family.get("schema_version") != 1
        or not isinstance(family.get("operating_points"), dict)
        or operating_point_id not in family["operating_points"]
    ):
        raise ValueError("source-family operating-point binding is invalid")
    point = family["operating_points"][operating_point_id]
    required = {"mass_amu", "charge_state", "kinetic_energy_eV"}
    if not isinstance(point, dict) or not required.issubset(point):
        raise ValueError("source-family operating point is incomplete")
    return family, point, family_sha256


def _validate_energy(
    particle_id: int,
    energy_ev: float,
    energy_model: dict[str, Any],
    *,
    operating_point: bool,
) -> None:
    if operating_point:
        distribution = energy_model.get("distribution")
        if distribution == "fixed":
            expected_energy = float(energy_model["value"])
            if not math.isfinite(expected_energy) or expected_energy < 0:
                raise ValueError(
                    "source-family fixed energy must be finite and nonnegative"
                )
            if not math.isclose(
                energy_ev, expected_energy, rel_tol=1e-9, abs_tol=1e-12
            ):
                raise ValueError(
                    f"particle {particle_id} kinetic energy differs from operating point"
                )
            return
        if distribution == "uniform":
            minimum = float(energy_model["min"])
            maximum = float(energy_model["max"])
            if (
                not math.isfinite(minimum)
                or not math.isfinite(maximum)
                or minimum < 0
                or maximum < minimum
            ):
                raise ValueError(
                    "source-family uniform energy bounds must be finite, "
                    "nonnegative, and ordered"
                )
        else:
            raise ValueError("source-family operating-point energy model is unsupported")
    elif energy_model["kind"] == "monoenergetic":
        expected_energy = float(energy_model["kinetic_energy_eV"])
        if not math.isclose(
            energy_ev, expected_energy, rel_tol=1e-9, abs_tol=1e-12
        ):
            raise ValueError(
                f"particle {particle_id} kinetic energy differs from resolved design"
            )
        return
    else:
        minimum = float(energy_model["minimum_energy_eV"])
        maximum = float(energy_model["maximum_energy_eV"])
    if (
        energy_ev < minimum - ENERGY_BOUND_TOLERANCE_EV
        or energy_ev > maximum + ENERGY_BOUND_TOLERANCE_EV
    ):
        authority = "operating point" if operating_point else "resolved closed interval"
        raise ValueError(f"particle {particle_id} kinetic energy is outside the {authority}")


def _load_volume_snapshot_receipt(
    path: Path | None, source_path: Path
) -> dict[str, Any] | None:
    """Validate the immutable authority for a non-planar ion-source snapshot.

    The legacy source contract is intentionally plane/mono-energy only.  A
    volume source is accepted only when its generator receipt is explicitly
    bound to the exact CSV; this prevents an arbitrary non-planar CSV from
    weakening the normal entrance-plane gate.
    """
    if path is None:
        return None
    try:
        receipt = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("volume-source receipt is not readable JSON") from exc
    if not isinstance(receipt, dict) or (
        receipt.get("role") != "continuous_axial_volume_ion_beam_source"
        or receipt.get("method") != "independent_spatial_velocity_ion_source_snapshot_v1"
        or receipt.get("source_region_model") != "ion_source_volume_cylinder_v1"
        or receipt.get("source_frame_id") != "multipole_cartesian_z_axis_v1"
        or receipt.get("phase_space_assumption")
        != "spatial_density_and_velocity_distribution_are_independent; no_z_vz_correlation_prescribed"
    ):
        raise ValueError("volume-source receipt identity differs")
    source = receipt.get("particle_source")
    geometry = receipt.get("geometry_mm")
    energy = receipt.get("kinetic_energy_eV")
    velocity = receipt.get("velocity_distribution")
    if not all(isinstance(value, dict) for value in (source, geometry, energy, velocity)):
        raise ValueError("volume-source receipt is incomplete")
    if (
        source.get("sha256") != hashlib.sha256(source_path.read_bytes()).hexdigest().upper()
        or source.get("particle_count") != receipt.get("particle_count")
        or receipt.get("primary_table_time_semantics") != "all_rows_are_states_at_snapshot_time_s"
        or velocity.get("components") != "independent_gaussian_with_positive_vz_truncation"
    ):
        raise ValueError("volume-source receipt does not bind the source CSV")
    required_geometry = {"center_x_mm", "center_y_mm", "center_z_mm", "radius_mm", "axial_length_mm"}
    if not required_geometry.issubset(geometry):
        raise ValueError("volume-source geometry is incomplete")
    for name in required_geometry:
        if not isinstance(geometry[name], (int, float)) or not math.isfinite(float(geometry[name])):
            raise ValueError("volume-source geometry is not finite")
    if float(geometry["radius_mm"]) <= 0 or float(geometry["axial_length_mm"]) <= 0:
        raise ValueError("volume-source geometry must be positive")
    for name in ("minimum", "maximum", "mean"):
        if not isinstance(energy.get(name), (int, float)) or not math.isfinite(float(energy[name])):
            raise ValueError("volume-source energy statistics are invalid")
    if float(energy["minimum"]) < 0 or float(energy["maximum"]) < float(energy["minimum"]):
        raise ValueError("volume-source energy bounds are invalid")
    return receipt


def validate_source(
    path: Path,
    resolved: dict[str, Any],
    *,
    source_family_path: Path | None = None,
    operating_point_id: str | None = None,
    expected_source_family_sha256: str | None = None,
    expected_kinetic_energy_ev: float | None = None,
    volume_snapshot_receipt_path: Path | None = None,
) -> dict[str, Any]:
    """Return frozen metadata after binding every source row to the resolved design."""
    if resolved.get("role") != "multipole_resolved_design_do_not_edit":
        raise ValueError("particle source requires a multipole resolved design")
    volume_receipt = _load_volume_snapshot_receipt(volume_snapshot_receipt_path, path)
    if volume_receipt is not None and (
        source_family_path is not None or expected_kinetic_energy_ev is not None
    ):
        raise ValueError("volume-source receipt cannot be combined with an energy override")
    _, operating_point, source_family_sha256 = _load_operating_point(
        source_family_path, operating_point_id
    )
    if expected_source_family_sha256 is not None:
        if source_family_sha256 is None:
            raise ValueError("expected source-family SHA-256 requires a source family")
        if source_family_sha256 != expected_source_family_sha256.upper():
            raise ValueError("source-family SHA-256 differs from the frozen runner input")
    source_plane = float(resolved["interfaces_mm"]["entrance"]["release_plane_z_mm"])
    expected_charge = int(resolved["particle_source"]["charge_state"])
    energy_model = (
        operating_point["kinetic_energy_eV"]
        if operating_point is not None
        else resolved["particle_source"]["energy_model"]
    )
    if expected_kinetic_energy_ev is not None:
        expected_kinetic_energy_ev = float(expected_kinetic_energy_ev)
        if not math.isfinite(expected_kinetic_energy_ev) or expected_kinetic_energy_ev <= 0.0:
            raise ValueError("expected kinetic energy must be finite and positive")
        if operating_point is not None:
            raise ValueError("campaign source-energy override cannot replace an operating point")
        energy_model = {
            "kind": "monoenergetic",
            "kinetic_energy_eV": expected_kinetic_energy_ev,
        }
    expected_mass = (
        float(operating_point["mass_amu"])
        if operating_point is not None
        else None
    )
    if operating_point is not None and int(operating_point["charge_state"]) != expected_charge:
        raise ValueError("source-family operating-point charge differs from resolved design")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != COLUMNS:
            raise ValueError(f"canonical particle source columns differ: {reader.fieldnames}")
        rows = list(reader)
    if not rows:
        raise ValueError("canonical particle source is empty")
    # Sample size is a run-control choice.  The source boundary only needs a
    # non-empty, fully identified particle table; formal evidence applies its
    # own standard-N qualification separately.
    validate_positive_particle_count(len(rows))
    particle_ids: set[int] = set()
    masses: set[float] = set()
    energies: list[float] = []
    for row in rows:
        particle_id = int(row["particle_id"])
        if particle_id in particle_ids:
            raise ValueError(f"duplicate particle_id: {particle_id}")
        particle_ids.add(particle_id)
        values = [float(row[name]) for name in COLUMNS[1:-1]]
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"particle {particle_id} contains a non-finite value")
        mass = float(row["mass_amu"])
        charge = int(row["charge_state"])
        if mass <= 0 or charge == 0:
            raise ValueError(f"particle {particle_id} has invalid mass or charge")
        if expected_mass is not None and mass != expected_mass:
            raise ValueError(
                f"particle {particle_id} mass differs from operating point"
            )
        if charge != expected_charge:
            raise ValueError(f"particle {particle_id} charge differs from resolved design")
        if volume_receipt is None:
            if abs(float(row["z_mm"]) - source_plane) > 1e-12:
                raise ValueError(f"particle {particle_id} source plane differs from resolved design")
        else:
            geometry = volume_receipt["geometry_mm"]
            dx = float(row["x_mm"]) - float(geometry["center_x_mm"])
            dy = float(row["y_mm"]) - float(geometry["center_y_mm"])
            half_length = float(geometry["axial_length_mm"]) / 2.0
            if (
                dx * dx + dy * dy > float(geometry["radius_mm"]) ** 2 + 1e-12
                or abs(float(row["z_mm"]) - float(geometry["center_z_mm"])) > half_length + 1e-12
                or float(row["birth_time_s"]) != float(volume_receipt["snapshot_time_s"])
            ):
                raise ValueError(f"particle {particle_id} differs from the authorized source volume")
        if float(row["birth_time_s"]) < 0:
            raise ValueError(f"particle {particle_id} has a negative source clock")
        energy_ev = kinetic_energy_ev(
            mass,
            *(float(row[name]) for name in ("vx_m_s", "vy_m_s", "vz_m_s")),
        )
        if volume_receipt is None:
            _validate_energy(
                particle_id,
                energy_ev,
                energy_model,
                operating_point=operating_point is not None,
            )
        elif not (
            float(volume_receipt["kinetic_energy_eV"]["minimum"]) - ENERGY_BOUND_TOLERANCE_EV
            <= energy_ev
            <= float(volume_receipt["kinetic_energy_eV"]["maximum"]) + ENERGY_BOUND_TOLERANCE_EV
        ):
            raise ValueError(f"particle {particle_id} energy differs from the authorized source volume")
        energies.append(energy_ev)
        masses.add(mass)
    if len(masses) != 1:
        raise ValueError("canonical particle source contains multiple masses")
    if particle_ids != set(range(1, len(rows) + 1)):
        raise ValueError("canonical particle IDs must be contiguous from 1 through N")
    return {
        "schema_version": 1,
        "role": "multipole_canonical_particle_source_metadata",
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
        "parent_resolved_design_sha256": resolved["resolved_sha256"],
        "particle_count": len(rows),
        "mass_amu": masses.pop(),
        "charge_state": expected_charge,
        "source_plane_z_mm": source_plane if volume_receipt is None else None,
        "source_volume_snapshot": volume_receipt is not None,
        "energy_model": (
            energy_model if volume_receipt is None else volume_receipt["velocity_distribution"]
        ),
        "energy_model_authority": (
            "continuous_axial_volume_source_receipt" if volume_receipt is not None else "campaign_particle_source_derivation"
            if expected_kinetic_energy_ev is not None
            else "resolved_design_or_operating_point"
        ),
        "operating_point_binding": (
            {
                "operating_point_id": operating_point_id,
                "source_family_sha256": source_family_sha256,
            }
            if source_family_path is not None
            else None
        ),
        "sample_energy_statistics_eV": {
            "minimum": min(energies),
            "maximum": max(energies),
            "mean": sum(energies) / len(energies),
        },
        "energy_validation_tolerance_eV": ENERGY_BOUND_TOLERANCE_EV,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--resolved-design", required=True, type=Path)
    parser.add_argument("--source-family", type=Path)
    parser.add_argument("--operating-point")
    parser.add_argument("--expected-source-family-sha256")
    parser.add_argument("--expected-kinetic-energy-ev", type=float)
    parser.add_argument("--volume-snapshot-receipt", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    resolved = json.loads(args.resolved_design.read_text(encoding="utf-8-sig"))
    metadata = validate_source(
        args.source,
        resolved,
        source_family_path=args.source_family,
        operating_point_id=args.operating_point,
        expected_source_family_sha256=args.expected_source_family_sha256,
        expected_kinetic_energy_ev=args.expected_kinetic_energy_ev,
        volume_snapshot_receipt_path=args.volume_snapshot_receipt,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(
        "MULTIPOLE_CANONICAL_SOURCE=PASS "
        f"PARTICLES={metadata['particle_count']} SHA256={metadata['source_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
