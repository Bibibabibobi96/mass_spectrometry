"""Load multipole run evidence and derive solver-independent observables."""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from common.contracts.particle_physics import kinetic_energy_ev
COMSOL_PRIMARY_STATE_FILE = "particle_state__primary.csv"
SUPPORTED_SOLVERS = ("COMSOL", "SIMION")
CELL_AXES = ("x", "y", "z")
PHYSICS_IDENTITY_FIELDS = (
    "model_level",
    "design_profile_id",
    "operating_mode_id",
    "operating_point_id",
)
PARTICLE_ENVELOPE_FIELDS = (
    "transverse_x_mm",
    "transverse_y_mm",
    "velocity_x_m_s",
    "velocity_y_m_s",
    "elapsed_time_us",
    "kinetic_energy_eV",
)
CANDIDATE_OBSERVABLE_FIELDS = (
    "rms_radius",
    "rms_divergence",
    "mean_energy",
    "mean_tof",
)


def normalize_simion_solver_numerics(
    numerics: dict[str, Any],
) -> dict[str, Any]:
    """Normalize SIMION spacing while keeping this frozen analysis module portable."""

    has_legacy = "cell_mm" in numerics
    has_canonical = "cell_mm_xyz" in numerics
    if has_legacy == has_canonical:
        raise ValueError(
            "SIMION numerics must define exactly one of cell_mm or cell_mm_xyz"
        )
    result = dict(numerics)
    spacing = result.pop("cell_mm") if has_legacy else result["cell_mm_xyz"]
    if has_legacy:
        spacing = {axis: spacing for axis in CELL_AXES}
    if not isinstance(spacing, dict) or set(spacing) != set(CELL_AXES):
        raise ValueError("cell_mm_xyz must contain exactly x, y, and z")
    normalized: dict[str, float] = {}
    for axis in CELL_AXES:
        value = spacing[axis]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("SIMION cell spacing must be positive finite numbers")
        normalized[axis] = float(value)
        if not math.isfinite(normalized[axis]) or normalized[axis] <= 0:
            raise ValueError("SIMION cell spacing must be positive finite numbers")
    result["cell_mm_xyz"] = normalized
    return result
SPATIAL_COMPARISON_AXES = (
    "spatial",
    "spatial_radial",
    "spatial_axial",
    "spatial_isotropic",
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _load_hashed_json(path: Path) -> tuple[dict[str, Any], str]:
    payload = path.read_bytes()
    document = json.loads(payload.decode("utf-8-sig"))
    if not isinstance(document, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return document, hashlib.sha256(payload).hexdigest().upper()


def physical_resolved_design_sha256(resolved: dict[str, Any]) -> str:
    """Hash compiled physics while excluding compiler and authority provenance."""
    payload = copy.deepcopy(resolved)
    for field in ("compiler", "governance", "sources", "resolved_sha256"):
        payload.pop(field, None)
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


def solver_name(manifest: dict[str, Any]) -> str:
    software = " ".join(str(item) for item in manifest.get("software", []))
    matches = [name for name in SUPPORTED_SOLVERS if name in software.upper()]
    if len(matches) != 1:
        raise ValueError("manifest must identify exactly one supported solver")
    return matches[0]


def manifest_record(manifest: dict[str, Any], filename: str) -> Path:
    matches = [
        Path(record["path"])
        for record in manifest.get("outputs", [])
        if Path(record["path"]).name == filename
    ]
    if len(matches) != 1 or not matches[0].is_file():
        raise ValueError(f"manifest must contain exactly one existing {filename}")
    return matches[0]


def primary_case_id(manifest: dict[str, Any]) -> str:
    """Resolve the named primary case from retained machine-readable outputs."""
    case_ids: set[str] = set()
    for record in manifest.get("outputs", []):
        path = Path(record["path"])
        if path.suffix.lower() != ".json" or not path.is_file():
            continue
        try:
            value = load_json(path).get("primary_case_id")
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if value:
            case_ids.add(str(value))
    if len(case_ids) != 1:
        raise ValueError("manifest outputs must identify exactly one primary_case_id")
    return case_ids.pop()


def primary_state_filename(manifest: dict[str, Any], solver: str) -> str:
    if solver == "COMSOL":
        return COMSOL_PRIMARY_STATE_FILE
    return f"particle_states__{primary_case_id(manifest)}.csv"


def mean_source_energy_from_particle_input(path: Path) -> float:
    """Calculate the normalization energy from the frozen solver-neutral source."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("particle source input is empty")
    particle_ids = [int(row["particle_id"]) for row in rows]
    if particle_ids != list(range(1, len(rows) + 1)):
        raise ValueError("particle source IDs must be contiguous, ordered, and one-based")
    energies = [
        kinetic_energy_ev(
            float(row["mass_amu"]),
            float(row["vx_m_s"]),
            float(row["vy_m_s"]),
            float(row["vz_m_s"]),
        )
        for row in rows
    ]
    return sum(energies) / len(energies)


def _finite_row_value(row: dict[str, Any], field: str) -> float:
    try:
        value = float(row[field])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"handoff state has invalid {field}") from exc
    if not math.isfinite(value):
        raise ValueError(f"handoff state has non-finite {field}")
    return value


def handoff_observables(values: list[dict[str, Any]]) -> dict[str, float]:
    """Derive beam observables from canonical particle-state primitives."""
    if not values:
        raise ValueError("run has no transmitted handoff states")
    positions: list[tuple[float, float]] = []
    directions: list[tuple[float, float, float]] = []
    elapsed_times: list[float] = []
    energies: list[float] = []
    divergence_angles: list[float] = []
    for row in values:
        x = _finite_row_value(row, "transverse_x_mm")
        y = _finite_row_value(row, "transverse_y_mm")
        vx = _finite_row_value(row, "velocity_x_m_s")
        vy = _finite_row_value(row, "velocity_y_m_s")
        vz = _finite_row_value(row, "velocity_axial_m_s")
        speed = math.sqrt(vx * vx + vy * vy + vz * vz)
        if speed <= 0:
            raise ValueError("handoff state has zero velocity magnitude")
        positions.append((x, y))
        directions.append((vx / speed, vy / speed, vz / speed))
        divergence_angles.append(
            math.degrees(math.atan2(math.hypot(vx, vy), vz))
        )
        elapsed_times.append(_finite_row_value(row, "elapsed_time_us"))
        energies.append(_finite_row_value(row, "kinetic_energy_eV"))

    count = len(values)
    centroid_x = math.fsum(point[0] for point in positions) / count
    centroid_y = math.fsum(point[1] for point in positions) / count
    centered_spatial_spread = math.sqrt(
        math.fsum(
            (x - centroid_x) ** 2 + (y - centroid_y) ** 2
            for x, y in positions
        )
        / count
    )
    mean_direction = tuple(
        math.fsum(direction[index] for direction in directions) / count
        for index in range(3)
    )
    mean_direction_norm = math.sqrt(
        math.fsum(component * component for component in mean_direction)
    )
    if mean_direction_norm <= 0:
        raise ValueError("handoff states have undefined mean beam direction")
    mean_direction_unit = tuple(
        component / mean_direction_norm for component in mean_direction
    )
    angular_offsets = [
        math.degrees(
            math.acos(
                max(
                    -1.0,
                    min(
                        1.0,
                        math.fsum(
                            direction[index] * mean_direction_unit[index]
                            for index in range(3)
                        ),
                    ),
                )
            )
        )
        for direction in directions
    ]
    mean_energy = math.fsum(energies) / count
    return {
        "transverse_centroid_x_mm": centroid_x,
        "transverse_centroid_y_mm": centroid_y,
        "centered_spatial_rms_spread_mm": centered_spatial_spread,
        "mean_beam_direction_unit_x": mean_direction_unit[0],
        "mean_beam_direction_unit_y": mean_direction_unit[1],
        "mean_beam_direction_unit_z": mean_direction_unit[2],
        "centered_angular_rms_spread_deg": math.sqrt(
            math.fsum(offset * offset for offset in angular_offsets) / count
        ),
        "mean_energy": mean_energy,
        "centered_rms_energy_spread_eV": math.sqrt(
            math.fsum((energy - mean_energy) ** 2 for energy in energies) / count
        ),
        "mean_tof": math.fsum(elapsed_times) / count,
        # Historical, uncentered observables retained for existing contracts.
        "rms_radius": math.sqrt(
            math.fsum(x * x + y * y for x, y in positions) / count
        ),
        "rms_divergence": math.sqrt(
            math.fsum(angle * angle for angle in divergence_angles) / count
        ),
    }


def run_data(manifest_path: Path) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    if manifest.get("status") != "success":
        raise ValueError(f"source run is not successful: {manifest_path}")
    solver = solver_name(manifest)
    config = load_json(Path(manifest["run_config"]["path"]))
    numerics = load_json(Path(manifest["inputs"]["solver_numerics"]["path"]))
    if solver == "SIMION":
        numerics = normalize_simion_solver_numerics(numerics)
    resolved = load_json(Path(manifest["inputs"]["multipole_resolved_design"]["path"]))
    state_path = manifest_record(manifest, primary_state_filename(manifest, solver))
    with state_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    handoff_rows = [
        row
        for row in rows
        if row["event"] == "handoff" and row["status"] == "transmitted"
    ]
    handoff_ids = [int(row["particle_id"]) for row in handoff_rows]
    if len(handoff_ids) != len(set(handoff_ids)):
        raise ValueError("transmitted handoff particle IDs must be unique")
    handoff = dict(zip(handoff_ids, handoff_rows, strict=True))
    if not handoff:
        raise ValueError("run has no transmitted handoff states")
    source_rows = [row for row in rows if row["event"] == "source"]
    source_ids = [int(row["particle_id"]) for row in source_rows]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("source particle IDs must be unique")
    source = dict(zip(source_ids, source_rows, strict=True))
    if set(source) != set(range(1, len(source) + 1)):
        raise ValueError("source particle IDs must be contiguous and one-based")
    values = list(handoff.values())
    derived_observables = handoff_observables(values)
    exit_interface = resolved["interfaces_mm"]["exit"]
    aperture_radius = float(exit_interface["aperture_radius_mm"])
    projection_distance = float(exit_interface["census_plane_z_mm"]) - float(
        exit_interface["handoff_plane_z_mm"]
    )
    if aperture_radius <= 0 or projection_distance < 0:
        raise ValueError("exit aperture or handoff-to-census distance is invalid")
    rf_period_us = 1e6 / float(resolved["drive"]["frequency_Hz"])
    particle_source_path = Path(manifest["inputs"]["particle_source"]["path"])
    if not particle_source_path.is_file():
        raise ValueError("manifest particle_source input does not exist")
    mean_source_energy = mean_source_energy_from_particle_input(particle_source_path)
    rms_radius = derived_observables["rms_radius"]
    rms_divergence = derived_observables["rms_divergence"]
    mean_tof = derived_observables["mean_tof"]
    mean_energy = derived_observables["mean_energy"]
    maximum_rod_radius = max(
        _finite_row_value(row, "max_rod_radius_mm") for row in rows
    )
    working_radius = float(resolved["geometry_mm"]["enclosure"]["working_region_radius_mm"])
    margin_fraction = (working_radius - maximum_rod_radius) / working_radius
    return {
        "manifest": manifest,
        "config": config,
        "numerics": numerics,
        "solver": solver,
        "run_id": manifest["run_id"],
        "project": manifest["project"],
        "resolved_design_sha256": config["provenance"]["parent_resolved_design_sha256"],
        "physical_resolved_design_sha256": physical_resolved_design_sha256(
            resolved
        ),
        "particle_source_sha256": config["provenance"]["particle_source_sha256"],
        "scales": {
            "exit_aperture_radius_mm": aperture_radius,
            "handoff_to_census_distance_mm": projection_distance,
            "rf_period_us": rf_period_us,
            "mean_source_energy_eV": mean_source_energy,
        },
        "handoff_particle_ids": sorted(handoff),
        "source_particle_ids": sorted(source),
        "lost_particle_ids": sorted(set(source) - set(handoff)),
        "_handoff": handoff,
        "observables": {
            **derived_observables,
            "transmission": len(handoff) / len(source),
            "transmitted_particle_count": len(handoff),
            "maximum_rod_radius": maximum_rod_radius,
            "minimum_working_radius_margin_fraction": margin_fraction,
            "rms_radius_exit_aperture_fraction": rms_radius / aperture_radius,
            "projected_divergence_exit_aperture_fraction": (
                projection_distance
                * math.tan(math.radians(rms_divergence))
                / aperture_radius
            ),
            "mean_tof_rf_periods": mean_tof / rf_period_us,
            "mean_energy_source_fraction": mean_energy / mean_source_energy,
        },
    }


def symmetric_relative(a: float, b: float) -> float:
    scale = (abs(a) + abs(b)) / 2
    return abs(a - b) / scale if scale else 0.0


def optional_absolute_difference(
    a: float | int | None, b: float | int | None
) -> float | None:
    """Return a finite absolute difference, or None for an unavailable metric."""
    if a is None or b is None:
        return None
    left = float(a)
    right = float(b)
    if not math.isfinite(left) or not math.isfinite(right):
        return None
    return abs(left - right)


def optional_direction_separation(
    a: dict[str, Any], b: dict[str, Any]
) -> float | None:
    """Return the angle between finite unit mean-direction vectors."""
    fields = (
        "mean_beam_direction_unit_x",
        "mean_beam_direction_unit_y",
        "mean_beam_direction_unit_z",
    )
    try:
        left = tuple(float(a[field]) for field in fields)
        right = tuple(float(b[field]) for field in fields)
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (*left, *right)):
        return None
    left_norm = math.sqrt(math.fsum(value * value for value in left))
    right_norm = math.sqrt(math.fsum(value * value for value in right))
    if left_norm <= 0 or right_norm <= 0:
        return None
    cosine = math.fsum(
        left[index] * right[index] for index in range(3)
    ) / (left_norm * right_norm)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def optional_centroid_separation(
    a: dict[str, Any], b: dict[str, Any]
) -> float | None:
    """Return transverse centroid-vector separation for finite components."""
    fields = ("transverse_centroid_x_mm", "transverse_centroid_y_mm")
    try:
        left = tuple(float(a[field]) for field in fields)
        right = tuple(float(b[field]) for field in fields)
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (*left, *right)):
        return None
    return math.hypot(left[0] - right[0], left[1] - right[1])


def observable_differences(
    a: dict[str, Any], b: dict[str, Any]
) -> dict[str, float | None]:
    ao = a["observables"]
    bo = b["observables"]
    differences = {
        "transmitted_particle_count_difference": abs(
            ao["transmitted_particle_count"] - bo["transmitted_particle_count"]
        ),
        "rms_radius_exit_aperture_fraction_difference": abs(
            ao["rms_radius_exit_aperture_fraction"]
            - bo["rms_radius_exit_aperture_fraction"]
        ),
        "projected_divergence_exit_aperture_fraction_difference": abs(
            ao["projected_divergence_exit_aperture_fraction"]
            - bo["projected_divergence_exit_aperture_fraction"]
        ),
        "mean_tof_rf_period_difference": abs(
            ao["mean_tof_rf_periods"] - bo["mean_tof_rf_periods"]
        ),
        "mean_energy_source_fraction_difference": abs(
            ao["mean_energy_source_fraction"]
            - bo["mean_energy_source_fraction"]
        ),
        "transmission_absolute_difference": abs(
            ao["transmission"] - bo["transmission"]
        ),
        "mean_tof_relative_difference": symmetric_relative(ao["mean_tof"], bo["mean_tof"]),
        "rms_radius_relative_difference": symmetric_relative(ao["rms_radius"], bo["rms_radius"]),
        "rms_divergence_relative_difference": symmetric_relative(
            ao["rms_divergence"], bo["rms_divergence"]
        ),
        "mean_energy_relative_difference": symmetric_relative(
            ao["mean_energy"], bo["mean_energy"]
        ),
        "rms_radius_absolute_difference_mm": optional_absolute_difference(
            ao["rms_radius"], bo["rms_radius"]
        ),
        "rms_divergence_absolute_difference_deg": optional_absolute_difference(
            ao["rms_divergence"], bo["rms_divergence"]
        ),
        "mean_energy_absolute_difference_eV": optional_absolute_difference(
            ao["mean_energy"], bo["mean_energy"]
        ),
        "rms_energy_spread_absolute_difference_eV": optional_absolute_difference(
            ao.get("rms_energy_spread"), bo.get("rms_energy_spread")
        ),
        "sample_std_energy_spread_absolute_difference_eV": (
            optional_absolute_difference(
                ao.get("sample_std_energy_spread"),
                bo.get("sample_std_energy_spread"),
            )
        ),
        "transverse_centroid_vector_difference_mm": optional_centroid_separation(
            ao, bo
        ),
        "centered_spatial_rms_spread_absolute_difference_mm": (
            optional_absolute_difference(
                ao.get("centered_spatial_rms_spread_mm"),
                bo.get("centered_spatial_rms_spread_mm"),
            )
        ),
        "mean_beam_direction_separation_deg": optional_direction_separation(
            ao, bo
        ),
        "centered_angular_rms_spread_absolute_difference_deg": (
            optional_absolute_difference(
                ao.get("centered_angular_rms_spread_deg"),
                bo.get("centered_angular_rms_spread_deg"),
            )
        ),
        "centered_rms_energy_spread_absolute_difference_eV": (
            optional_absolute_difference(
                ao.get("centered_rms_energy_spread_eV"),
                bo.get("centered_rms_energy_spread_eV"),
            )
        ),
    }
    common_ids = sorted(set(a["_handoff"]) & set(b["_handoff"]))
    if common_ids:
        def paired_rms(fields: tuple[str, ...]) -> float:
            return math.sqrt(
                sum(
                    sum(
                        (
                            float(a["_handoff"][particle_id][field])
                            - float(b["_handoff"][particle_id][field])
                        )
                        ** 2
                        for field in fields
                    )
                    for particle_id in common_ids
                )
                / len(common_ids)
            )

        differences.update(
            paired_transverse_position_rms_difference_mm=paired_rms(
                ("transverse_x_mm", "transverse_y_mm")
            ),
            paired_transverse_velocity_rms_difference_m_s=paired_rms(
                ("velocity_x_m_s", "velocity_y_m_s")
            ),
            paired_elapsed_time_rms_difference_us=paired_rms(("elapsed_time_us",)),
            paired_energy_rms_difference_eV=paired_rms(("kinetic_energy_eV",)),
        )
    return differences
